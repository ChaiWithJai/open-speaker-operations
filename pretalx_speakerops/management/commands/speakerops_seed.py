from datetime import date, timedelta

from django.core.management import BaseCommand, call_command
from django.db import transaction
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event, Team
from pretalx.person.models import User
from pretalx.schedule.models import TalkSlot
from pretalx.submission.models import Review, SubmissionStates

from ...domain.commands import Command as DomainCommand
from ...domain.commands import execute
from ...domain.state import StateMachine, Transition
from ...models import OnboardingTask, PreviewRun, Resource, ResourceVersion, TaskDefinition
from ...onboarding.reminders import queue_reminders
from ...onboarding.services import ensure_acceptance_plan, record_evidence

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
            if created:
                user.set_password("speakerops-demo")
                user.save(update_fields=["password"])
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
            assigned_review = Review.objects.filter(submission__event=event).first()
            if assigned_review and assigned_review.user_id != users["reviewer"].pk:
                assigned_review.user = users["reviewer"]
                assigned_review.save(update_fields=["user", "updated"])
            submission = event.submissions.filter(state=SubmissionStates.ACCEPTED).first()
            if submission:
                submission.speakers.add(users["speaker"])
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
            PreviewRun.objects.get_or_create(
                event=event,
                status="previewed",
                defaults={
                    "payload": {
                        "adapter": "mock",
                        "items": [{"action": "create", "external_id": "demo-session"}],
                    }
                },
            )
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
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded speakerops-demo. Accounts: chair@example.org, "
                "reviewer@example.org, speaker@example.org; password speakerops-demo."
            )
        )
