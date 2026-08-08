from datetime import date, timedelta

from django.core.management import BaseCommand, call_command
from django.db import transaction
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import User
from pretalx.submission.models import SubmissionStates

from ...models import OnboardingTask, PreviewRun, TaskDefinition
from ...onboarding.services import ensure_acceptance_plan


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

        with scope(event=event):
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
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded speakerops-demo. Accounts: chair@example.org, "
                "reviewer@example.org, speaker@example.org; password speakerops-demo."
            )
        )
