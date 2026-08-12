from datetime import UTC, date, datetime, time

from celery import shared_task
from celery.schedules import crontab
from django.utils import timezone
from django_scopes import scope
from pretalx.celery_app import app
from pretalx.event.models import Event

from .models import OnboardingTask, ScheduledReminderRun
from .onboarding.reminders import ReminderOutcomeAmbiguous, queue_reminders

REMINDER_SCHEDULE_NAME = "speakerops-due-speaker-reminders-daily"
REMINDER_BEAT_HEADER = "speakerops.reminder.beat.v1"


def send_due_speaker_reminders(
    event_slug=None,
    as_of=None,
    *,
    celery_task_id=None,
    started_at=None,
    dispatch_origin=None,
    schedule_name=None,
):
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
            scheduled_run = None
            if (
                celery_task_id
                and dispatch_origin == ScheduledReminderRun.ORIGIN_BEAT
                and schedule_name == REMINDER_SCHEDULE_NAME
            ):
                scheduled_run, created = ScheduledReminderRun.objects.get_or_create(
                    event=event,
                    schedule_date=today,
                    scheduled_for=datetime.combine(today, time(hour=9), tzinfo=UTC),
                    celery_task_id=celery_task_id,
                    defaults={
                        "dispatch_origin": dispatch_origin,
                        "schedule_name": schedule_name,
                        "started_at": started_at or timezone.now(),
                        "eligible_count": tasks.count(),
                    },
                )
                if not created and scheduled_run.status == ScheduledReminderRun.COMPLETED:
                    result[event.slug] = scheduled_run.accepted_count
                    continue
            try:
                result[event.slug] = queue_reminders(
                    event,
                    tasks=tasks,
                    reminder_key=f"onboarding-overdue:{today.isoformat()}",
                    scheduled_run=scheduled_run,
                )
            except ReminderOutcomeAmbiguous:
                if scheduled_run:
                    scheduled_run.status = ScheduledReminderRun.AMBIGUOUS
                    scheduled_run.completed_at = timezone.now()
                    scheduled_run.save(update_fields=["status", "completed_at", "updated"])
                raise
            except Exception:
                if scheduled_run:
                    scheduled_run.status = ScheduledReminderRun.FAILED
                    scheduled_run.completed_at = timezone.now()
                    scheduled_run.save(update_fields=["status", "completed_at", "updated"])
                raise
            if scheduled_run:
                scheduled_run.status = ScheduledReminderRun.COMPLETED
                scheduled_run.completed_at = timezone.now()
                scheduled_run.accepted_count = scheduled_run.receipts.filter(
                    delivery_status="accepted"
                ).count()
                scheduled_run.save(
                    update_fields=[
                        "status",
                        "completed_at",
                        "accepted_count",
                        "updated",
                    ]
                )
    return result


@shared_task(
    bind=True,
    name="speakerops.send_due_speaker_reminders",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def send_due_speaker_reminders_task(self):
    try:
        if not self.request.id:
            return {"status": "rejected", "reason": "missing_celery_task_id"}
        headers = self.request.headers or {}
        dispatch_origin = (
            ScheduledReminderRun.ORIGIN_BEAT
            if headers.get("speakerops_dispatch_origin") == REMINDER_BEAT_HEADER
            else None
        )
        schedule_name = headers.get("speakerops_schedule_name")
        return send_due_speaker_reminders(
            celery_task_id=self.request.id,
            started_at=timezone.now(),
            dispatch_origin=dispatch_origin,
            schedule_name=schedule_name,
        )
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
    REMINDER_SCHEDULE_NAME,
    {
        "task": "speakerops.send_due_speaker_reminders",
        "schedule": crontab(hour=9, minute=0),
        "options": {
            "headers": {
                "speakerops_dispatch_origin": REMINDER_BEAT_HEADER,
                "speakerops_schedule_name": REMINDER_SCHEDULE_NAME,
            }
        },
    },
)
