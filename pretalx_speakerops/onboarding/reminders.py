from django.db import transaction
from django_scopes import scope
from pretalx.mail.models import QueuedMail

from ..models import OnboardingTask, ReminderReceipt


def queue_reminders(event, tasks=None, reminder_key="onboarding-due"):
    if tasks is None:
        tasks = OnboardingTask.objects.filter(
            event=event, status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED)
        ).select_related("speaker", "submission", "definition")
    queued = 0
    with scope(event=event):
        for task in tasks:
            with transaction.atomic():
                receipt, created = ReminderReceipt.objects.select_for_update().get_or_create(
                    event=event,
                    task=task,
                    speaker=task.speaker,
                    reminder_key=reminder_key,
                )
                if not created:
                    if not receipt.queued_mail_id:
                        continue
                    mail = (
                        QueuedMail.objects.select_for_update()
                        .filter(
                            event=event,
                            pk=receipt.queued_mail_id,
                            sent__isnull=True,
                        )
                        .first()
                    )
                    if not mail:
                        continue
                else:
                    submission_title = (
                        task.submission.title if task.submission else "your speaker action list"
                    )
                    due_date = task.due_date.isoformat() if task.due_date else "date not set"
                    mail = QueuedMail.objects.create(
                        event=event,
                        subject=f"Speaker action needed: {task.definition.name} · {event.name}"[
                            :200
                        ],
                        text=(
                            f"Please complete {task.definition.name} for {submission_title}. "
                            f"Due {due_date}."
                        ),
                    )
                    mail.to_users.add(task.speaker)
                    if task.submission:
                        mail.submissions.add(task.submission)
                    receipt.queued_mail_id = mail.pk
                    receipt.save(update_fields=["queued_mail_id", "updated"])
                # QueuedMail.send publishes to pretalx's Celery delivery task and
                # marks the native mail history. The enclosing transaction makes a
                # broker failure retryable instead of leaving a suppressing receipt.
                mail.send(orga=False)
                queued += 1
    return queued
