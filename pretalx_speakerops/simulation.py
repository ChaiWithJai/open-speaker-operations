import hashlib
import math
from dataclasses import dataclass
from time import perf_counter

from django.db import transaction
from django_scopes import scope
from pretalx.person.models import User
from pretalx.submission.models import Answer, Review, Submission, SubmissionStates

from .cfp import SESSION_FORMATS, configure_demo_cfp
from .models import AcceptanceWave, OnboardingTask, ProgramDecision
from .onboarding.services import ensure_acceptance_plan
from .program.decisions import (
    finalize_rejections,
    release_acceptance_wave,
    stage_program_decision,
)
from .program.reviews import configure_review_rounds


@dataclass(frozen=True)
class SimulationResult:
    speakers: int
    proposals: int
    reviewers: int
    reviews: int
    accepted: int
    waitlisted: int
    rejected: int
    onboarding_tasks: int
    elapsed_seconds: float


def _code(event_pk, index):
    return hashlib.sha256(f"speakerops:{event_pk}:{index}".encode()).hexdigest()[:6].upper()


def _ensure_users(event, speaker_count, reviewer_count):
    speaker_emails = [
        f"speakerops-sim-speaker-{event.pk}-{index:04d}@invalid.example"
        for index in range(speaker_count)
    ]
    reviewer_emails = [
        f"speakerops-sim-reviewer-{event.pk}-{index:03d}@invalid.example"
        for index in range(reviewer_count)
    ]
    existing = set(
        User.objects.filter(email__in=[*speaker_emails, *reviewer_emails]).values_list(
            "email", flat=True
        )
    )
    User.objects.bulk_create(
        [
            User(email=email, name=f"Simulated Speaker {index + 1}", password="!")
            for index, email in enumerate(speaker_emails)
            if email not in existing
        ]
        + [
            User(email=email, name=f"Simulated Reviewer {index + 1}", password="!")
            for index, email in enumerate(reviewer_emails)
            if email not in existing
        ],
        batch_size=500,
    )
    speakers = list(User.objects.filter(email__in=speaker_emails).order_by("email"))
    reviewers = list(User.objects.filter(email__in=reviewer_emails).order_by("email"))
    return speakers, reviewers


def _ensure_cfp_answers(event, proposals):
    questions = {
        str(question.question): question
        for question in event.questions.filter(
            question__in=(
                "Audience level",
                "Key takeaway",
                "Topics",
                "Commercial relationship",
                "Session abstract",
            )
        ).prefetch_related("options")
    }
    for proposal in proposals:
        chosen = {
            "Audience level": "Intermediate",
            "Key takeaway": "A measurable technique attendees can apply immediately.",
            "Topics": "AI agents",
            "Commercial relationship": "No commercial relationship",
            "Session abstract": (
                "A deterministic scale-test abstract with an observable audience outcome."
            ),
        }
        for label, value in chosen.items():
            question = questions[label]
            answer, _ = Answer.objects.get_or_create(question=question, submission=proposal)
            if question.options.exists():
                answer.options.set(question.options.filter(answer=value))
            else:
                answer.answer = value
                answer.save(update_fields=["answer", "updated"])


@transaction.atomic
def simulate_cfp(
    event,
    speaker_count=1500,
    acceptance_rate=0.10,
    *,
    proposal_count=None,
    reviewer_count=None,
):
    """Create a deterministic scale fixture through CFP, review, decision and onboarding."""
    if speaker_count < 1:
        raise ValueError("speaker_count must be positive")
    proposal_count = proposal_count or speaker_count
    if proposal_count < speaker_count:
        raise ValueError("proposal_count must be at least speaker_count")
    if not 0 < acceptance_rate < 1:
        raise ValueError("acceptance_rate must be between zero and one")
    reviewer_count = reviewer_count or max(1, math.ceil(proposal_count / 40))
    if reviewer_count < 1:
        raise ValueError("reviewer_count must be positive")

    started = perf_counter()
    with scope(event=event):
        configure_demo_cfp(event)
        configure_review_rounds(event)
        speakers, reviewers = _ensure_users(event, speaker_count, reviewer_count)
        submission_types = list(
            event.submission_types.filter(name__in=[name for name, _ in SESSION_FORMATS]).order_by(
                "name"
            )
        )
        tracks = list(event.tracks.order_by("position", "pk"))

        codes = [_code(event.pk, index) for index in range(proposal_count)]
        existing_codes = set(
            Submission.objects.filter(event=event, code__in=codes).values_list("code", flat=True)
        )
        Submission.objects.bulk_create(
            [
                Submission(
                    event=event,
                    code=code,
                    title=f"Scale proposal {index + 1:04d}",
                    submission_type=submission_types[index % len(submission_types)],
                    track=tracks[index % len(tracks)],
                    state=SubmissionStates.SUBMITTED,
                    abstract=(
                        "A deterministic scale-test proposal with a concrete audience outcome."
                    ),
                    description=(
                        "Exercises review assignment, decisions, and onboarding at AIE scale."
                    ),
                    content_locale=event.locale,
                )
                for index, code in enumerate(codes)
                if code not in existing_codes
            ],
            batch_size=500,
        )
        proposals_by_code = {
            proposal.code: proposal
            for proposal in Submission.objects.filter(event=event, code__in=codes)
        }
        proposals = [proposals_by_code[code] for code in codes]

        speaker_role = Submission.speakers.through
        speaker_role.objects.bulk_create(
            [
                speaker_role(submission=proposal, user=speaker)
                for index, proposal in enumerate(proposals)
                for speaker in (speakers[index % speaker_count],)
            ],
            ignore_conflicts=True,
            batch_size=500,
        )
        reviewer_assignment = Submission.assigned_reviewers.through
        reviewer_assignment.objects.bulk_create(
            [
                reviewer_assignment(submission=proposal, user=reviewers[index % reviewer_count])
                for index, proposal in enumerate(proposals)
            ],
            ignore_conflicts=True,
            batch_size=500,
        )
        existing_reviews = set(
            Review.objects.filter(submission__in=proposals).values_list("submission_id", flat=True)
        )
        Review.objects.bulk_create(
            [
                Review(
                    submission=proposal,
                    user=reviewers[index % reviewer_count],
                    text="Deterministic human-review simulation.",
                    score=4,
                )
                for index, proposal in enumerate(proposals)
                if proposal.pk not in existing_reviews
            ],
            batch_size=500,
        )
        _ensure_cfp_answers(event, proposals)

        accepted_count = max(1, round(proposal_count * acceptance_rate))
        waitlisted_count = max(1, round(proposal_count * 0.05))
        waves = list(AcceptanceWave.objects.filter(event=event).order_by("position"))
        decision_actor = User.objects.filter(email="chair@example.org").first() or reviewers[0]
        for index, proposal in enumerate(proposals):
            if index < accepted_count:
                status = ProgramDecision.ACCEPT
                wave = waves[index % len(waves)]
            elif index < accepted_count + waitlisted_count:
                status = ProgramDecision.WAITLIST
                wave = None
            else:
                status = ProgramDecision.REJECT
                wave = None
            stage_program_decision(
                proposal,
                status,
                decision_actor,
                wave=wave,
                rationale="Deterministic program-scale simulation.",
            )

        accepted = proposals[:accepted_count]
        for wave in waves:
            release_acceptance_wave(wave, decision_actor)
        finalize_rejections(event, decision_actor)
        for proposal in accepted:
            proposal.refresh_from_db(fields=["state"])
            ensure_acceptance_plan(proposal)

        return SimulationResult(
            speakers=len(speakers),
            proposals=len(proposals),
            reviewers=len(reviewers),
            reviews=Review.objects.filter(submission__in=proposals).count(),
            accepted=accepted_count,
            waitlisted=waitlisted_count,
            rejected=proposal_count - accepted_count - waitlisted_count,
            onboarding_tasks=OnboardingTask.objects.filter(
                event=event, submission__in=accepted
            ).count(),
            elapsed_seconds=perf_counter() - started,
        )
