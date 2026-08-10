import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.management import BaseCommand, call_command
from django.db import transaction
from django.utils import timezone
from django_scopes import scope
from pretalx.common.models import ActivityLog
from pretalx.event.models import Event, Team
from pretalx.person.models import SpeakerProfile, User
from pretalx.schedule.models import TalkSlot
from pretalx.submission.models import Answer, Question, Review, Submission, SubmissionStates
from pretalx.submission.models.question import QuestionRequired, QuestionTarget, QuestionVariant

from ...cfp import AIE_TRACKS, configure_demo_cfp, configure_demo_cfp_routing
from ...domain.commands import Command as DomainCommand
from ...domain.commands import execute
from ...domain.state import StateMachine, Transition
from ...integrations.sync import fingerprint
from ...models import (
    AcceleventsConnection,
    ExternalIdentity,
    OnboardingTask,
    ReminderReceipt,
    Resource,
    ResourceVersion,
    ReviewRecommendation,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
    TaskDefinition,
)
from ...onboarding.reminders import queue_reminders
from ...onboarding.services import (
    ensure_acceptance_plan,
    get_or_create_default_template,
    record_evidence,
)
from ...program.policy import release_schedule
from ...program.reviews import configure_review_rounds

TASK_MACHINE = StateMachine(
    states=frozenset(
        {
            OnboardingTask.PENDING,
            OnboardingTask.REOPENED,
            OnboardingTask.COMPLETE,
            OnboardingTask.WAIVED,
        }
    ),
    transitions=(
        Transition(OnboardingTask.PENDING, OnboardingTask.COMPLETE, frozenset({"speaker"})),
        Transition(OnboardingTask.REOPENED, OnboardingTask.COMPLETE, frozenset({"speaker"})),
        Transition(OnboardingTask.PENDING, OnboardingTask.WAIVED, frozenset({"organiser"})),
        Transition(OnboardingTask.REOPENED, OnboardingTask.WAIVED, frozenset({"organiser"})),
    ),
)

CURATED_PROGRAM = (
    (
        "Maya Chen",
        "Designing Calm Systems for High-Stakes Work",
        "How teams can reduce cognitive load without hiding consequential decisions.",
    ),
    (
        "Jordan Okafor",
        "From Spreadsheet Chaos to Program Readiness",
        "A practical operating model for coordinating speakers, reviewers, and schedules.",
    ),
    (
        "Priya Raman",
        "Trustworthy AI Needs Operational Guardrails",
        "Patterns that turn responsible-AI principles into observable delivery controls.",
    ),
    (
        "Luis Alvarez",
        "The Human Side of Reliable Integrations",
        "Designing previews, retries, and audit trails that operators can understand.",
    ),
    (
        "Amina Yusuf",
        "Accessibility Is a Systems Requirement",
        "Making inclusive choices visible from content collection through publication.",
    ),
    (
        "Noah Williams",
        "Decision Quality in Distributed Review Teams",
        "A shared rubric and explicit handoffs for faster, fairer program decisions.",
    ),
    (
        "Elena Petrova",
        "Designing for the Moment Something Goes Wrong",
        "Recovery paths that preserve context, confidence, and completed work.",
    ),
    (
        "Marcus Reed",
        "Own the Workflow, Not Just the Infrastructure",
        "Balancing open-source ownership, continuity, and operating cost.",
    ),
    (
        "Sofia Kim",
        "Content Models That Make the Next Action Obvious",
        "Turning status inventories into clear, role-specific operating queues.",
    ),
    (
        "David Mensah",
        "Release Gates Without Release Theater",
        "How server-enforced checks prevent unsafe publication without slowing teams down.",
    ),
    (
        "Leila Haddad",
        "Measuring Flow Across Human and Technical Systems",
        "Useful measures for readiness, handoff latency, recovery, and operator confidence.",
    ),
    (
        "Theo Martin",
        "A Better Final Mile for Event Operations",
        "A closing blueprint for moving an accepted idea safely into the hands of attendees.",
    ),
)

# Five sessions intentionally demonstrate a meaningful public track filter while the
# remaining seven keep the broader human-centered program visible.
CURATED_RELIABLE_TRACK_INDICES = frozenset({2, 3, 4, 6, 9})

CURATED_SPEAKER_ROLES = (
    ("Principal Product Designer", "Calm Systems Lab"),
    ("Program Operations Lead", "Open Program Collective"),
    ("Responsible AI Director", "Latticework Systems"),
    ("Integration Architect", "Reliable Interfaces"),
    ("Accessibility Engineering Lead", "Inclusive Systems Studio"),
    ("Research Director", "Distributed Decisions Lab"),
    ("Resilience Designer", "Recovery Works"),
    ("Open Infrastructure Lead", "Portable Operations"),
    ("Content Systems Designer", "Clear Next Action"),
    ("Release Engineering Director", "Guardrail Labs"),
    ("Operations Researcher", "Human Flow Institute"),
    ("Conference Program Director", "Final Mile Events"),
)

CONFLICT_FIXTURE_TITLES = (
    "WIP fixture: Main Stage room collision",
    "WIP fixture: Maya Chen double-booking",
)

DEMO_START = date(2026, 8, 10)
DEMO_END = date(2026, 8, 12)
CFP_OPENING = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("America/New_York"))
CFP_DEADLINE = datetime(2026, 6, 30, 23, 59, tzinfo=ZoneInfo("America/New_York"))
DEMO_WALKTHROUGH_AT = datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("America/New_York"))
JOURNEY_PROGRAM = (
    (SubmissionStates.DRAFT, "Draft: Responsible AI in Practice"),
    (SubmissionStates.SUBMITTED, "Review: Designing Trustworthy Systems"),
    (SubmissionStates.ACCEPTED, "Accepted: Operations That Scale"),
)
EVALUATOR_SIGNUP_EMAIL = "priya.raman-cfp@example.invalid"


class Command(BaseCommand):
    help = "Create or update the Speaker Operations judge dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--open-cfp-for-rehearsal",
            action="store_true",
            help=(
                "Temporarily open the local demo CFP so the real speaker form can be "
                "exercised. Run the command again without this flag to restore the "
                "canonical historical dates."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        demo_password = os.environ.get("SPEAKEROPS_DEMO_PASSWORD", "speakerops-demo")
        administrator_password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", demo_password)
        connector_key = os.environ.get("SPEAKEROPS_MOCK_KEY", "demo-key")
        administrator, _ = User.objects.get_or_create(
            email="admin@example.org",
            defaults={"name": "SpeakerOps Administrator", "is_administrator": True},
        )
        administrator.is_administrator = True
        administrator.is_staff = True
        administrator.set_password(administrator_password)
        administrator.save()
        if not Event.objects.filter(slug="speakerops-demo").exists():
            call_command(
                "create_test_event",
                slug="speakerops-demo",
                stage="schedule",
                seed=42,
                verbosity=0,
            )
        event = Event.objects.get(slug="speakerops-demo")
        # Browser acceptance creates this reserved throwaway account through the
        # real public registration flow. Removing it here keeps every seeded run
        # deterministic without touching any non-demo identity.
        with scope(event=event):
            ActivityLog.objects.filter(person__email=EVALUATOR_SIGNUP_EMAIL).delete()
        User.objects.filter(email=EVALUATOR_SIGNUP_EMAIL).delete()
        event.enable_plugin("pretalx_speakerops")
        event.name = "DemoCon 2026"
        event.email = "program@democon.test"
        event.timezone = "America/New_York"
        event.date_from = DEMO_START
        event.date_to = DEMO_END
        event.feature_flags = {**(event.feature_flags or {}), "use_tracks": True}
        event.landing_page_text = (
            "<p>A three-day program about humane, reliable technology operations. "
            "Explore practical sessions from the people building calmer systems.</p>"
            '<p><a href="/speakerops-demo/speaker-operations/embed/">Browse the released '
            "schedule by list, day, or week</a>, or use the detailed conference schedule "
            "below for session pages and exports.</p>"
        )
        event.save(
            update_fields=[
                "plugins",
                "name",
                "email",
                "timezone",
                "date_from",
                "date_to",
                "feature_flags",
                "landing_page_text",
                "updated",
            ]
        )
        administrator.timezone = event.timezone
        administrator.save(update_fields=["timezone"])
        users = {}
        for role, email, name in (
            ("chair", "chair@example.org", "Program Chair"),
            ("reviewer", "reviewer@example.org", "Reviewer"),
            ("reviewer_systems", "reviewer-systems@democon.test", "Systems Reviewer"),
            ("speaker", "speaker@example.org", "Maya Chen"),
            ("speaker2", "speaker2@example.org", "Marcus Okafor"),
        ):
            user, created = User.objects.get_or_create(email=email, defaults={"name": name})
            user.name = name
            user.timezone = event.timezone
            user.set_password(demo_password)
            user.save(update_fields=["name", "timezone", "password"])
            users[role] = user

        teams = (
            (
                "SpeakerOps organisers",
                {"can_change_event_settings": True, "can_change_submissions": True},
            ),
            (
                "SpeakerOps program chair",
                {
                    "can_change_submissions": True,
                    "can_change_event_settings": True,
                    "can_change_teams": True,
                },
            ),
            ("SpeakerOps reviewers", {"can_change_submissions": False, "is_reviewer": True}),
        )
        for name, permissions in teams:
            team, _ = Team.objects.get_or_create(organiser=event.organiser, name=name)
            team.all_events = False
            team.save()
            team.limit_events.add(event)
            for field, value in permissions.items():
                setattr(team, field, value)
            team.save(update_fields=list(permissions))
        Team.objects.get(organiser=event.organiser, name="SpeakerOps organisers").members.add(
            administrator
        )
        Team.objects.get(organiser=event.organiser, name="SpeakerOps program chair").members.add(
            users["chair"]
        )
        Team.objects.get(organiser=event.organiser, name="SpeakerOps reviewers").members.add(
            users["reviewer"], users["reviewer_systems"]
        )

        with scope(event=event):
            configure_demo_cfp(event)
            public_speaker_questions = {}
            for label in ("Job title", "Company"):
                question = Question.all_objects.filter(event=event, question=label).first()
                if not question:
                    question = Question(event=event, question=label)
                question.variant = QuestionVariant.STRING
                question.target = QuestionTarget.SPEAKER
                question.question_required = QuestionRequired.OPTIONAL
                question.active = True
                question.is_public = True
                question.position = 900 + len(public_speaker_questions)
                question.save()
                public_speaker_questions[label] = question
            configure_review_rounds(event, second_round=True)
            get_or_create_default_template(event)
            if options["open_cfp_for_rehearsal"]:
                event.cfp.opening = timezone.now() - timedelta(days=1)
                event.cfp.deadline = timezone.now() + timedelta(days=1)
            else:
                event.cfp.opening = CFP_OPENING
                event.cfp.deadline = CFP_DEADLINE
            event.cfp.headline = "Share your idea with DemoCon"
            event.cfp.text = (
                "Bring us a practical story about building responsible, humane technology. "
                "Save a draft, return when you are ready, and submit it for review."
            )
            event.cfp.save(update_fields=["opening", "deadline", "headline", "text", "updated"])
            event.submission_types.update(deadline=event.cfp.deadline)
            canonical_track_names = (
                "Human-Centered Operations",
                "Reliable AI Systems",
                *AIE_TRACKS,
            )
            tracks = list(event.tracks.order_by("position", "pk"))
            if len(tracks) < len(canonical_track_names):
                raise RuntimeError("The deterministic demo needs its complete track taxonomy.")
            # create_test_event ships a broad taxonomy whose names may overlap with the
            # CFP taxonomy created above. Converge it by identity, not by name, so seed
            # replay cannot leave duplicate buyer-facing filters behind.
            for track in tracks:
                track.name = f"SpeakerOps seed track {track.pk}"
                track.save(update_fields=["name", "updated"])
            canonical_tracks = tracks[: len(canonical_track_names)]
            for position, (track, name) in enumerate(
                zip(canonical_tracks, canonical_track_names, strict=True)
            ):
                track.name = name
                track.position = position
                track.save(update_fields=["name", "position", "updated"])
            extra_tracks = tracks[len(canonical_track_names) :]
            if extra_tracks:
                Submission.all_objects.filter(
                    event=event, track_id__in=[track.pk for track in extra_tracks]
                ).update(track=canonical_tracks[0])
                event.tracks.filter(pk__in=[track.pk for track in extra_tracks]).delete()
            configure_demo_cfp_routing(event, (users["reviewer"], users["reviewer_systems"]))

            existing_journey = {
                proposal.title: proposal
                for proposal in Submission.all_objects.filter(
                    event=event,
                    title__in=[title for _state, title in JOURNEY_PROGRAM],
                )
            }
            if len(existing_journey) == len(JOURNEY_PROGRAM):
                journey_submissions = [existing_journey[title] for _state, title in JOURNEY_PROGRAM]
            else:
                journey_submissions = list(
                    Submission.all_objects.filter(event=event)
                    .exclude(state=SubmissionStates.DELETED)
                    .order_by("pk")[:3]
                )
            if len(journey_submissions) < 3:
                raise RuntimeError("The deterministic demo needs at least three seeded proposals.")
            draft, queued, accepted = journey_submissions
            for proposal, (state, title) in zip(
                journey_submissions,
                JOURNEY_PROGRAM,
                strict=True,
            ):
                proposal.state = state
                proposal.title = title
                proposal.save(update_fields=["state", "title", "updated"])
                proposal.speakers.set([users["speaker"]])
            queued.assigned_reviewers.add(users["reviewer"])
            Review.objects.filter(submission=queued).exclude(user=users["reviewer"]).delete()
            Review.objects.update_or_create(
                submission=queued,
                user=users["reviewer"],
                defaults={
                    "text": (
                        "Strong operational framing and concrete recovery examples. "
                        "Clarify how the audit trail supports a program chair during a live change."
                    )
                },
            )
            ReviewRecommendation.objects.filter(event=event, reviewer=users["reviewer"]).delete()
            draft.abstract = (
                "A field guide to introducing AI into consequential workflows without "
                "removing human judgment or accountability."
            )
            draft.description = (
                "Attendees leave with a lightweight decision framework, practical review "
                "questions, and examples of responsible escalation paths."
            )
            draft.save(update_fields=["abstract", "description", "updated"])
            queued.abstract = (
                "Trust is designed through visible state, bounded automation, and recovery "
                "paths—not through reassuring copy alone."
            )
            queued.description = (
                "We examine interface patterns for autosave, high-stakes confirmation, audit "
                "history, and failure recovery using real operational scenarios."
            )
            queued.save(update_fields=["abstract", "description", "updated"])
            accepted.abstract = (
                "How a small team replaced scattered spreadsheets and reminders with one "
                "measurable readiness-to-publish workflow."
            )
            accepted.description = (
                "A concrete case study covering ownership, handoffs, release gates, and safe "
                "synchronization with downstream event systems."
            )
            accepted.save(update_fields=["abstract", "description", "updated"])
            submission = accepted
            if submission:
                OnboardingTask.objects.filter(
                    event=event,
                    submission=submission,
                    speaker=users["speaker"],
                ).delete()
                ensure_acceptance_plan(submission)
                OnboardingTask.objects.filter(event=event).exclude(
                    submission=submission, speaker=users["speaker"]
                ).delete()
                definition = TaskDefinition.objects.filter(event=event).first()
                if definition:
                    OnboardingTask.objects.get_or_create(
                        event=event,
                        submission=submission,
                        speaker=users["speaker"],
                        definition=definition,
                        defaults={"due_date": date(2026, 8, 8)},
                    )
                tasks = list(
                    OnboardingTask.objects.filter(
                        event=event, submission=submission, speaker=users["speaker"]
                    ).order_by("definition__position")
                )
                if tasks:
                    tasks[0].due_date = date(2026, 8, 7)
                    tasks[0].save(update_fields=["due_date", "updated"])
                if len(tasks) > 1 and tasks[1].status != OnboardingTask.COMPLETE:
                    record_evidence(tasks[1], users["speaker"], "acknowledgement")
                    execute(
                        DomainCommand(
                            event=event,
                            aggregate_model=OnboardingTask,
                            aggregate_id=tasks[1].pk,
                            action="onboarding.complete",
                            target_state=OnboardingTask.COMPLETE,
                            state_machine=TASK_MACHINE,
                            actor_role="speaker",
                        ),
                        users["speaker"],
                        key=f"seed:task:{tasks[1].pk}:complete",
                        expected_version=tasks[1].version,
                    )
                if len(tasks) > 2 and tasks[2].status != OnboardingTask.WAIVED:
                    execute(
                        DomainCommand(
                            event=event,
                            aggregate_model=OnboardingTask,
                            aggregate_id=tasks[2].pk,
                            action="onboarding.waive",
                            target_state=OnboardingTask.WAIVED,
                            state_machine=TASK_MACHINE,
                            actor_role="organiser",
                            payload={"reason": "Covered during speaker briefing"},
                        ),
                        administrator,
                        key=f"seed:task:{tasks[2].pk}:waive",
                        expected_version=tasks[2].version,
                    )
                    tasks[2].waiver_reason = "Covered during speaker briefing"
                    tasks[2].save(update_fields=["waiver_reason", "updated"])
            schedule = event.wip_schedule
            journey_submission_ids = {draft.pk, queued.pk, accepted.pk}
            scheduled_talks = TalkSlot.objects.filter(
                schedule=schedule, submission__isnull=False
            ).exclude(submission_id__in=journey_submission_ids)
            curated_slots = list(
                scheduled_talks.select_related("submission").order_by("pk")[: len(CURATED_PROGRAM)]
            )
            curated_submission_ids = [slot.submission_id for slot in curated_slots]
            conflict_slots = list(
                scheduled_talks.select_related("submission").order_by("pk")[
                    len(CURATED_PROGRAM) : len(CURATED_PROGRAM) + len(CONFLICT_FIXTURE_TITLES)
                ]
            )
            if len(conflict_slots) != len(CONFLICT_FIXTURE_TITLES):
                raise RuntimeError("The deterministic demo needs two WIP conflict fixtures.")
            conflict_submission_ids = [slot.submission_id for slot in conflict_slots]
            operational_submission_ids = {
                *curated_submission_ids,
                *conflict_submission_ids,
            }
            # create_test_event intentionally generates a broad scheduling fixture. Keep its
            # submissions as deleted seed history, but remove their slots from every schedule:
            # pretalx's native editor requests all talk slots (including invisible/deleted
            # proposals), which otherwise floods the buyer-facing planning surface with
            # overnight and irrelevant sessions. Historical conference backfill lives in the
            # Speaker Operations catalog models and is unaffected by this cleanup.
            TalkSlot.objects.filter(schedule__event=event).exclude(
                submission_id__in=operational_submission_ids
            ).delete()
            Submission.all_objects.filter(event=event).exclude(
                pk__in={
                    draft.pk,
                    queued.pk,
                    accepted.pk,
                    *curated_submission_ids,
                    *conflict_submission_ids,
                }
            ).update(state=SubmissionStates.DELETED)
            program_by_submission = {
                slot.submission_id: program
                for slot, program in zip(curated_slots, CURATED_PROGRAM, strict=True)
            }
            for index, (slot, (speaker_name, title, abstract)) in enumerate(
                zip(curated_slots, CURATED_PROGRAM, strict=True)
            ):
                proposal = slot.submission
                proposal.title = title
                proposal.abstract = abstract
                proposal.description = (
                    f"{abstract} This session includes a concrete operating pattern and a "
                    "take-home checklist."
                )
                proposal.track = canonical_tracks[
                    1 if index in CURATED_RELIABLE_TRACK_INDICES else 0
                ]
                proposal.state = SubmissionStates.CONFIRMED
                proposal.save(
                    update_fields=[
                        "title",
                        "abstract",
                        "description",
                        "track",
                        "state",
                        "updated",
                    ]
                )
                if index == 0:
                    speaker = users["speaker"]
                else:
                    speaker, _ = User.objects.get_or_create(
                        email=f"curated-speaker-{index + 1}@democon.test",
                        defaults={"name": speaker_name},
                    )
                speaker.name = speaker_name
                for image_field in (
                    speaker.avatar,
                    speaker.avatar_thumbnail,
                    speaker.avatar_thumbnail_tiny,
                ):
                    if image_field:
                        image_field.delete(save=False)
                # Fictional public-demo portraits are packaged static assets. Native
                # media uploads remain the normal product path, but local production-mode
                # Django intentionally does not expose the entire private media tree.
                speaker.avatar = None
                speaker.avatar_thumbnail = None
                speaker.avatar_thumbnail_tiny = None
                speaker.get_gravatar = False
                speaker.save(
                    update_fields=[
                        "name",
                        "avatar",
                        "avatar_thumbnail",
                        "avatar_thumbnail_tiny",
                        "get_gravatar",
                    ],
                    skip_gravatar_processing=True,
                )
                SpeakerProfile.objects.update_or_create(
                    event=event,
                    user=speaker,
                    defaults={
                        "biography": (
                            f"{speaker_name} helps teams turn complex technology work into "
                            "clear, humane operating practices."
                        )
                    },
                )
                job_title, company = CURATED_SPEAKER_ROLES[index]
                Answer.objects.update_or_create(
                    question=public_speaker_questions["Job title"],
                    person=speaker,
                    defaults={"answer": job_title},
                )
                Answer.objects.update_or_create(
                    question=public_speaker_questions["Company"],
                    person=speaker,
                    defaults={"answer": company},
                )
                proposal.speakers.set([speaker])

            room_fixture_speaker, _ = User.objects.get_or_create(
                email="conflict-room@democon.test",
                defaults={"name": "Room Fixture Speaker"},
            )
            conflict_speakers = (room_fixture_speaker, users["speaker"])
            for slot, title, speaker in zip(
                conflict_slots, CONFLICT_FIXTURE_TITLES, conflict_speakers, strict=True
            ):
                proposal = slot.submission
                proposal.title = title
                proposal.abstract = (
                    "A deliberately unpublished proposal used to demonstrate the WIP release gate."
                )
                proposal.description = (
                    "This fixture remains outside every released schedule while preserving a "
                    "deterministic room and speaker conflict for operators to resolve."
                )
                proposal.state = SubmissionStates.DELETED
                proposal.save(
                    update_fields=["title", "abstract", "description", "state", "updated"]
                )
                proposal.speakers.set([speaker])

            rooms = list(event.rooms.order_by("position", "pk")[:2])
            for room, name in zip(rooms, ("Main Stage", "Studio"), strict=False):
                room.name = name
                room.save(update_fields=["name", "updated"])
            event_zone = ZoneInfo(event.timezone)
            for demo_schedule in event.schedules.all():
                demo_slots = list(
                    TalkSlot.objects.filter(
                        schedule=demo_schedule,
                        submission__isnull=False,
                    ).order_by("pk")
                )
                TalkSlot.objects.filter(schedule=demo_schedule).exclude(
                    submission_id__in=curated_submission_ids
                ).update(is_visible=False)
                visible_slots = {}
                for slot in demo_slots:
                    if slot.submission_id in program_by_submission:
                        visible_slots.setdefault(slot.submission_id, slot)
                    elif slot.submission_id:
                        slot.is_visible = False
                for index, submission_id in enumerate(curated_submission_ids):
                    slot = visible_slots.get(submission_id)
                    if not slot:
                        continue
                    day = event.date_from + timedelta(days=index // 4)
                    hour = (9, 11, 14, 16)[index % 4]
                    start = timezone.make_aware(datetime.combine(day, time(hour=hour)), event_zone)
                    slot.start = start
                    slot.end = start + timedelta(minutes=45)
                    slot.room = rooms[index % len(rooms)] if rooms else None
                    slot.is_visible = True
                    slot.save(update_fields=["start", "end", "room", "is_visible", "updated"])
            if not schedule.version and not event.schedules.filter(version="m3-demo").exists():
                release_schedule(schedule, "m3-demo", administrator, notify_speakers=False)

            # Conflict fixtures belong only to the mutable WIP schedule. Speaker assignments
            # are submission-level in pretalx, so using curated submissions here would leak Maya
            # into the already released public schedule as an additional co-speaker.
            demo_wip = event.wip_schedule
            wip_conflicts = list(
                demo_wip.talks.filter(submission_id__in=conflict_submission_ids).order_by(
                    "submission_id"
                )
            )
            if len(wip_conflicts) != len(CONFLICT_FIXTURE_TITLES):
                raise RuntimeError("The deterministic WIP conflict fixtures are missing.")
            conflict_start = timezone.make_aware(
                datetime.combine(DEMO_START, time(hour=10)), event_zone
            )
            for slot, start, room in zip(
                wip_conflicts,
                (conflict_start, conflict_start),
                (rooms[0] if rooms else None, rooms[0] if rooms else None),
                strict=True,
            ):
                slot.room = room
                slot.start = start
                slot.end = start + timedelta(minutes=30)
                slot.is_visible = True
                slot.save(update_fields=["room", "start", "end", "is_visible", "updated"])
            # Make the two warnings genuinely independent: the fixture pair is a room-only
            # collision, while Maya's conflict fixture overlaps her curated WIP slot in the
            # other room. The already-frozen public schedule retains the canonical 09:00 slot.
            maya_wip_slot = demo_wip.talks.get(submission_id=curated_submission_ids[0])
            maya_wip_slot.room = rooms[1] if len(rooms) > 1 else (rooms[0] if rooms else None)
            maya_wip_slot.start = conflict_start
            maya_wip_slot.end = conflict_start + timedelta(minutes=45)
            maya_wip_slot.save(update_fields=["room", "start", "end", "updated"])
            resource, _ = Resource.objects.get_or_create(
                event=event, slug="speaker-guide", defaults={"title": "Speaker guide"}
            )
            ResourceVersion.objects.get_or_create(
                event=event,
                resource=resource,
                version=1,
                defaults={
                    "body_html": "<p>Published speaker guidance.</p>",
                    "published_at": timezone.now(),
                    "created_by": administrator,
                },
            )
            ReminderReceipt.objects.filter(event=event).delete()
            queue_reminders(event, reminder_key="seed-onboarding-reminder")
            connection, _ = AcceleventsConnection.objects.get_or_create(
                event=event,
                defaults={
                    "base_url": "http://mock-accelevents:9000",
                    "event_url": event.slug,
                    "credential_ref": connector_key,
                    "status": AcceleventsConnection.STATUS_CONNECTED,
                },
            )
            connection.credential_ref = connector_key
            connection.save(update_fields=["credential_ref", "updated"])
            accepted = event.submissions.filter(state=SubmissionStates.ACCEPTED).first()
            if accepted:
                SyncRun.objects.filter(event=event).delete()
                SyncPreview.objects.filter(event=event).delete()
                ExternalIdentity.objects.filter(event=event).delete()
                speaker = accepted.speakers.first()
                payload = {
                    "firstName": (speaker.name or "Demo").split(" ", 1)[0],
                    "lastName": (speaker.name or "Speaker").split(" ", 1)[-1],
                    "email": speaker.email,
                }
                digest = fingerprint(payload)
                ExternalIdentity.objects.get_or_create(
                    event=event,
                    local_type="speaker",
                    local_id=speaker.pk,
                    defaults={
                        "external_id": "101",
                        "request_fingerprint": digest,
                    },
                )
                body = {
                    "items": [
                        {
                            "local_type": "speaker",
                            "local_id": speaker.pk,
                            "payload": payload,
                            "fingerprint": digest,
                            "action": "noop",
                            "external_id": "101",
                        },
                        {
                            "local_type": "speaker",
                            "local_id": speaker.pk + 100000,
                            "payload": {
                                **payload,
                                "email": f"new-{speaker.email}",
                            },
                            "fingerprint": fingerprint(
                                {**payload, "email": f"new-{speaker.email}"}
                            ),
                            "action": "create",
                            "external_id": "",
                        },
                        {
                            "local_type": "session",
                            "local_id": accepted.pk,
                            "payload": {"title": f"{accepted.title} updated"},
                            "fingerprint": fingerprint({"title": f"{accepted.title} updated"}),
                            "action": "update",
                            "external_id": "201",
                        },
                        {
                            "local_type": "speaker",
                            "local_id": speaker.pk + 200000,
                            "payload": {
                                **payload,
                                "email": f"failed-{speaker.email}",
                            },
                            "fingerprint": fingerprint(
                                {**payload, "email": f"failed-{speaker.email}"}
                            ),
                            "action": "create",
                            "external_id": "",
                        },
                    ]
                }
                ExternalIdentity.objects.get_or_create(
                    event=event,
                    local_type="session",
                    local_id=accepted.pk,
                    defaults={
                        "external_id": "201",
                        "request_fingerprint": body["items"][2]["fingerprint"],
                    },
                )
                sync_preview, _ = SyncPreview.objects.get_or_create(
                    event=event,
                    fingerprint=fingerprint(body),
                    defaults={"payload": body, "status": SyncPreview.EXECUTED},
                )
                sync_run, _ = SyncRun.objects.get_or_create(
                    event=event,
                    preview=sync_preview,
                    defaults={
                        "status": SyncRun.PARTIAL,
                        "started_at": timezone.now(),
                        "finished_at": timezone.now(),
                    },
                )
                for item in body["items"]:
                    status = (
                        SyncItem.NOOP
                        if item["action"] == "noop"
                        else SyncItem.FAILED
                        if item["local_id"] == speaker.pk + 200000
                        else SyncItem.SUCCEEDED
                    )
                    sync_item, _ = SyncItem.objects.get_or_create(
                        event=event,
                        run=sync_run,
                        local_type=item["local_type"],
                        local_id=item["local_id"],
                        defaults={
                            "action": item["action"],
                            "payload": item["payload"],
                            "request_fingerprint": item["fingerprint"],
                            "status": status,
                            "external_id": item["external_id"],
                            "attempts": 2 if status == SyncItem.SUCCEEDED else 1,
                            "error": (
                                "Destination rate limit reached; this record is safe to retry."
                                if status == SyncItem.FAILED
                                else ""
                            ),
                        },
                    )
                    if status == SyncItem.SUCCEEDED:
                        SyncAttempt.objects.get_or_create(
                            event=event,
                            item=sync_item,
                            number=1,
                            defaults={
                                "status": "failed",
                                "error": "Destination rate limit reached; retry was safe.",
                                "finished_at": timezone.now(),
                            },
                        )
                        SyncAttempt.objects.get_or_create(
                            event=event,
                            item=sync_item,
                            number=2,
                            defaults={
                                "status": "succeeded",
                                "request_id": "demo-retry-request",
                                "response": {"external_id": sync_item.external_id},
                                "finished_at": timezone.now(),
                            },
                        )
                    elif status == SyncItem.FAILED:
                        SyncAttempt.objects.get_or_create(
                            event=event,
                            item=sync_item,
                            number=1,
                            defaults={
                                "status": "failed",
                                "error": sync_item.error,
                                "finished_at": timezone.now(),
                            },
                        )
                connection.last_error = ""
                connection.save(update_fields=["last_error", "updated"])
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded speakerops-demo. Accounts: chair@example.org, "
                "reviewer@example.org, speaker@example.org, speaker2@example.org; "
                "password loaded from SPEAKEROPS_DEMO_PASSWORD."
            )
        )
