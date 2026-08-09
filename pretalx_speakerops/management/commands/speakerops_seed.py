from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.management import BaseCommand, call_command
from django.db import transaction
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event, Team
from pretalx.person.models import User
from pretalx.schedule.models import TalkSlot
from pretalx.submission.models import Review, Submission, SubmissionStates

from ...cfp import configure_demo_cfp
from ...domain.commands import Command as DomainCommand
from ...domain.commands import execute
from ...domain.state import StateMachine, Transition
from ...integrations.sync import fingerprint
from ...models import (
    AcceleventsConnection,
    ExternalIdentity,
    OnboardingTask,
    Resource,
    ResourceVersion,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
    TaskDefinition,
)
from ...onboarding.reminders import queue_reminders
from ...onboarding.services import ensure_acceptance_plan, record_evidence
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


class Command(BaseCommand):
    help = "Create or update the Speaker Operations judge dataset."

    @transaction.atomic
    def handle(self, *args, **options):
        administrator, _ = User.objects.get_or_create(
            email="admin@example.org",
            defaults={"name": "SpeakerOps Administrator", "is_administrator": True},
        )
        administrator.is_administrator = True
        administrator.is_staff = True
        administrator.set_password("speakerops-demo")
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
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins", "updated"])
        users = {}
        for role, email, name in (
            ("chair", "chair@example.org", "Program Chair"),
            ("reviewer", "reviewer@example.org", "Reviewer"),
            ("speaker", "speaker@example.org", "Demo Speaker"),
        ):
            user, created = User.objects.get_or_create(email=email, defaults={"name": name})
            user.name = name
            user.set_password("speakerops-demo")
            user.save(update_fields=["name", "password"])
            users[role] = user

        teams = (
            (
                "SpeakerOps organisers",
                {"can_change_event_settings": True, "can_change_submissions": True},
            ),
            ("SpeakerOps program chair", {"can_change_submissions": True}),
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
            users["reviewer"]
        )

        with scope(event=event):
            configure_demo_cfp(event)
            configure_review_rounds(event, second_round=True)
            event.cfp.opening = timezone.now() - timedelta(days=1)
            event.cfp.deadline = timezone.now() + timedelta(days=90)
            event.cfp.headline = "Share your idea with DemoCon"
            event.cfp.text = (
                "Bring us a practical story about building responsible, humane technology. "
                "Save a draft, return when you are ready, and submit it for review."
            )
            event.cfp.save(update_fields=["opening", "deadline", "headline", "text", "updated"])
            event.submission_types.update(deadline=timezone.now() + timedelta(days=90))

            journey_submissions = list(
                Submission.all_objects.filter(event=event)
                .exclude(state=SubmissionStates.DELETED)
                .order_by("pk")[:3]
            )
            if len(journey_submissions) < 3:
                raise RuntimeError("The deterministic demo needs at least three seeded proposals.")
            draft, queued, accepted = journey_submissions
            for proposal, state, title in (
                (draft, SubmissionStates.DRAFT, "Draft: Responsible AI in Practice"),
                (queued, SubmissionStates.SUBMITTED, "Review: Designing Trustworthy Systems"),
                (accepted, SubmissionStates.ACCEPTED, "Accepted: Operations That Scale"),
            ):
                proposal.state = state
                proposal.title = title
                proposal.save(update_fields=["state", "title", "updated"])
                proposal.speakers.add(users["speaker"])
            queued.assigned_reviewers.add(users["reviewer"])
            Review.objects.filter(submission=queued).exclude(user=users["reviewer"]).delete()
            submission = accepted
            if submission:
                ensure_acceptance_plan(submission)
                definition = TaskDefinition.objects.filter(event=event).first()
                if definition:
                    OnboardingTask.objects.get_or_create(
                        event=event,
                        submission=submission,
                        speaker=users["speaker"],
                        definition=definition,
                        defaults={"due_date": date.today() + timedelta(days=14)},
                    )
                tasks = list(
                    OnboardingTask.objects.filter(
                        event=event, submission=submission, speaker=users["speaker"]
                    ).order_by("definition__position")
                )
                if tasks:
                    tasks[0].due_date = date.today() - timedelta(days=2)
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
            conflicting_slots = list(
                TalkSlot.objects.filter(schedule=schedule, submission__isnull=False)
                .select_related("submission")
                .order_by("pk")[:2]
            )
            if len(conflicting_slots) == 2:
                room = event.rooms.order_by("pk").first()
                start = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
                for slot in conflicting_slots:
                    slot.room = room
                    slot.start = start
                    slot.end = start + timedelta(minutes=30)
                    slot.submission.speakers.add(users["speaker"])
                    slot.save(update_fields=["room", "start", "end", "updated"])
                if not schedule.version and not event.schedules.filter(version="m3-demo").exists():
                    try:
                        release_schedule(schedule, "m3-demo", administrator, notify_speakers=False)
                    except ValidationError:
                        for index, slot in enumerate(
                            schedule.talks.filter(submission__isnull=False).order_by("pk")
                        ):
                            slot.room = event.rooms.order_by("pk")[index % event.rooms.count()]
                            slot.start = start + timedelta(hours=2 * index)
                            slot.end = slot.start + timedelta(minutes=30)
                            slot.save(update_fields=["room", "start", "end", "updated"])
                        release_schedule(schedule, "m3-demo", administrator, notify_speakers=False)
                        demo_wip = event.wip_schedule
                        wip_conflicts = list(
                            demo_wip.talks.filter(submission__isnull=False).order_by("pk")[:2]
                        )
                        if len(wip_conflicts) == 2:
                            for slot in wip_conflicts:
                                slot.room = event.rooms.order_by("pk").first()
                                slot.start = start
                                slot.end = start + timedelta(minutes=30)
                                slot.submission.speakers.add(users["speaker"])
                                slot.save(update_fields=["room", "start", "end", "updated"])
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
            queue_reminders(event, reminder_key="seed-onboarding-reminder")
            connection, _ = AcceleventsConnection.objects.get_or_create(
                event=event,
                defaults={
                    "base_url": "http://mock-accelevents:9000",
                    "event_url": event.slug,
                    "credential_ref": "demo-key",
                    "status": AcceleventsConnection.STATUS_CONNECTED,
                },
            )
            accepted = event.submissions.filter(state=SubmissionStates.ACCEPTED).first()
            if accepted:
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
                                "Injected demo failure; retry this item."
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
                                "error": "Injected demo failure; retry was safe.",
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
                "reviewer@example.org, speaker@example.org; password speakerops-demo."
            )
        )
