from datetime import date

from celery import shared_task
from celery.schedules import crontab
from django.utils import timezone
from django_scopes import scope
from pretalx.celery_app import app
from pretalx.event.models import Event

from .models import OnboardingTask
from .onboarding.reminders import ReminderOutcomeAmbiguous, queue_reminders


def send_due_speaker_reminders(event_slug=None, as_of=None):
    """Queue one reminder per overdue task/day for every enabled event.

    The day is part of the durable receipt key, so worker retry and a second
    scheduler invocation cannot send the same reminder twice.
    """

    today = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    today = today or timezone.localdate()
    events = Event.objects.filter(slug=event_slug) if event_slug else Event.objects.all()
    result = {}
    for event in events:
        if "pretalx_speakerops" not in event.plugin_list:
            continue
        with scope(event=event):
            tasks = OnboardingTask.objects.filter(
                event=event,
                due_date__lt=today,
                status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
            ).select_related("speaker", "submission", "definition")
            result[event.slug] = queue_reminders(
                event,
                tasks=tasks,
                reminder_key=f"onboarding-overdue:{today.isoformat()}",
            )
    return result


@shared_task(
    name="speakerops.send_due_speaker_reminders",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def send_due_speaker_reminders_task():
    try:
        return send_due_speaker_reminders()
    except ReminderOutcomeAmbiguous as error:
        # The durable claim means the broker may already have accepted the
        # message. A retry would risk duplicate mail, so surface and stop.
        return {
            "status": "ambiguous",
            "task_id": error.receipt.task_id,
            "reminder_receipt_id": error.receipt.pk,
            "retry_suppressed": True,
        }


app.conf.beat_schedule.setdefault(
    "speakerops-due-speaker-reminders-daily",
    {
        "task": "speakerops.send_due_speaker_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
)
