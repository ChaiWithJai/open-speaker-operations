from datetime import timedelta

from django.utils import timezone

from ..models import OnboardingTask, TaskDefinition


def ensure_acceptance_plan(submission):
    event = submission.event
    definition, _ = TaskDefinition.objects.get_or_create(
        event=event,
        slug="speaker-acknowledgement",
        defaults={
            "name": "Acknowledge speaker participation",
            "instructions": "Confirm that you will participate in the session.",
            "completion_criteria": "Click the acknowledgement button.",
        },
    )
    for speaker in submission.speakers.all():
        OnboardingTask.objects.get_or_create(
            event=event,
            submission=submission,
            speaker=speaker,
            definition=definition,
            defaults={"due_date": timezone.localdate() + timedelta(days=14)},
        )
