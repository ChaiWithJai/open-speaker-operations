import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django_scopes import scope
from pretalx.submission.models import Answer, Review, Submission, SubmissionStates

from pretalx_speakerops.models import AcceptanceWave, ProgramDecision
from pretalx_speakerops.program.decisions import (
    finalize_rejections,
    release_acceptance_wave,
    stage_program_decision,
)
from pretalx_speakerops.program.reviews import configure_review_rounds


def proposal_with_policy_answers(event, speaker, *, session_format, relationship, context=None):
    proposal = Submission.objects.create(
        event=event,
        title=f"Policy test {session_format}",
        submission_type=event.submission_types.get(name=session_format),
        state=SubmissionStates.SUBMITTED,
        abstract="A concrete abstract for a human reviewer.",
        description="A concrete description for a human reviewer.",
        content_locale=event.locale,
    )
    proposal.speakers.add(speaker)
    answer_values = {
        "Topics": ["AI agents"],
        "Commercial relationship": [relationship],
    }
    if context:
        answer_values["Proposed session context"] = [context]
    for label, values in answer_values.items():
        question = event.questions.get(question=label)
        answer = Answer.objects.create(question=question, submission=proposal)
        answer.options.set(question.options.filter(answer__in=values))
    return proposal


@pytest.mark.django_db(transaction=True)
def test_chair_stages_acceptance_wave_without_changing_native_state(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        proposal = proposal_with_policy_answers(
            event,
            users["speaker"],
            session_format="Workshop",
            relationship="No commercial relationship",
        )
        wave = AcceptanceWave.objects.filter(event=event).order_by("position").first()

    client.force_login(users["chair"])
    url = reverse(
        "plugins:speakerops:speakerops_review",
        kwargs={"event": event.slug, "pk": proposal.pk},
    )
    response = client.post(
        url,
        {
            "decision_action": "stage",
            "program_decision": "accept",
            "wave": wave.pk,
            "decision_rationale": "Strong fit for the workshop program.",
        },
    )

    assert response.status_code == 302
    proposal.refresh_from_db()
    assert proposal.state == SubmissionStates.SUBMITTED
    with scope(event=event):
        decision = ProgramDecision.objects.get(submission=proposal)
        assert decision.status == ProgramDecision.ACCEPT
    assert decision.wave == wave
    assert decision.decided_by == users["chair"]

    decisions_page = client.get(
        reverse(
            "plugins:speakerops:speakerops_program_decisions",
            kwargs={"event": event.slug},
        )
    )
    assert decisions_page.status_code == 200
    assert proposal.title.encode() in decisions_page.content
    assert b"Wave 1" in decisions_page.content


@pytest.mark.django_db(transaction=True)
def test_vendor_only_mainstage_acceptance_is_blocked_server_side(event, users):
    with scope(event=event):
        proposal = proposal_with_policy_answers(
            event,
            users["speaker"],
            session_format="Stage Talk",
            relationship="I work for or represent a vendor discussed in this session",
            context="Main stage",
        )
        wave = AcceptanceWave.objects.filter(event=event).first()
        with pytest.raises(ValidationError, match="not eligible for the main stage"):
            stage_program_decision(proposal, ProgramDecision.ACCEPT, users["chair"], wave=wave)

    with scope(event=event):
        assert not ProgramDecision.objects.filter(submission=proposal).exists()


@pytest.mark.django_db(transaction=True)
def test_reviewer_cannot_stage_program_decision(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        proposal = event.submissions.first()
        proposal.state = SubmissionStates.SUBMITTED
        proposal.save(update_fields=["state", "updated"])
        proposal.assigned_reviewers.add(users["reviewer"])

    client.force_login(users["reviewer"])
    response = client.post(
        reverse(
            "plugins:speakerops:speakerops_review",
            kwargs={"event": event.slug, "pk": proposal.pk},
        ),
        {"decision_action": "stage", "program_decision": "waitlist"},
    )

    assert response.status_code == 404
    with scope(event=event):
        assert not ProgramDecision.objects.filter(submission=proposal).exists()


@pytest.mark.django_db(transaction=True)
def test_explicit_wave_release_applies_staged_acceptance(event, users):
    with scope(event=event):
        proposal = proposal_with_policy_answers(
            event,
            users["speaker"],
            session_format="Workshop",
            relationship="No commercial relationship",
        )
        wave = AcceptanceWave.objects.filter(event=event).first()
        stage_program_decision(proposal, ProgramDecision.ACCEPT, users["chair"], wave=wave)

        released = release_acceptance_wave(wave, users["chair"])

        proposal.refresh_from_db()
        decision = ProgramDecision.objects.get(submission=proposal)
        assert released == 1
        assert proposal.state == SubmissionStates.ACCEPTED
        assert decision.applied_at is not None
        assert decision.applied_by == users["chair"]
        assert release_acceptance_wave(wave, users["chair"]) == 0
        with pytest.raises(ValidationError, match="already been applied"):
            stage_program_decision(
                proposal, ProgramDecision.WAITLIST, users["chair"], rationale="Changed mind"
            )


@pytest.mark.django_db(transaction=True)
def test_waitlist_stays_submitted_while_rejection_requires_explicit_finalize(event, users):
    with scope(event=event):
        waitlisted = proposal_with_policy_answers(
            event,
            users["speaker"],
            session_format="Online Talk",
            relationship="No commercial relationship",
        )
        rejected = proposal_with_policy_answers(
            event,
            users["speaker"],
            session_format="Lightning Talk",
            relationship="No commercial relationship",
        )
        stage_program_decision(waitlisted, ProgramDecision.WAITLIST, users["chair"])
        stage_program_decision(rejected, ProgramDecision.REJECT, users["chair"])

        waitlisted.refresh_from_db()
        rejected.refresh_from_db()
        assert waitlisted.state == SubmissionStates.SUBMITTED
        assert rejected.state == SubmissionStates.SUBMITTED

        finalized = finalize_rejections(event, users["chair"])

        waitlisted.refresh_from_db()
        rejected.refresh_from_db()
        rejected_decision = ProgramDecision.objects.get(submission=rejected)
        assert finalized == 1
        assert waitlisted.state == SubmissionStates.SUBMITTED
        assert rejected.state == SubmissionStates.REJECTED
        assert rejected_decision.applied_at is not None
        assert rejected_decision.applied_by == users["chair"]
        assert finalize_rejections(event, users["chair"]) == 0


@pytest.mark.django_db(transaction=True)
def test_chair_sees_sorted_normalized_weighted_results_and_csv(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        proposal = event.submissions.first()
        _phases, criteria = configure_review_rounds(event)
        review = Review.objects.create(submission=proposal, user=users["reviewer"])
        review.scores.set(
            [
                criterion.scores.order_by("value").get(value=value)
                for criterion, value in zip(criteria, (5, 3, 2), strict=True)
            ]
        )
        review.save()

    client.force_login(users["chair"])
    url = reverse("plugins:speakerops:speakerops_program_decisions", kwargs={"event": event.slug})
    page = client.get(f"{url}?sort=desc")
    assert page.status_code == 200
    assert b"Weighted review results" in page.content
    assert b"3.75" in page.content
    assert b"inform" in page.content and b"chair" in page.content

    exported = client.get(f"{url}?export=csv")
    assert exported.status_code == 200
    assert exported["Content-Type"] == "text/csv"
    assert b"weighted_average" in exported.content
    assert b"3.75" in exported.content
