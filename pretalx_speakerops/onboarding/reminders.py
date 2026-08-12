from django.db import transaction
from django_scopes import scope
from pretalx.mail.models import QueuedMail

from ..models import OnboardingTask, ReminderReceipt, SpeakerCommunicationLog


class ReminderOutcomeAmbiguous(RuntimeError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(f"Reminder outcome is ambiguous for task {receipt.task_id}")


def queue_reminder_task(event, task, reminder_key="onboarding-due", *, scheduled_run=None):
    """Persist the task/day claim and native outbox before broker handoff."""
    with scope(event=event):
        with transaction.atomic():
            receipt, created = ReminderReceipt.objects.select_for_update().get_or_create(
                event=event,
                task=task,
                speaker=task.speaker,
                reminder_key=reminder_key,
                defaults={
                    "scheduled_run": scheduled_run,
                    "due_date_at_dispatch": task.due_date,
                },
            )
            if not created:
                if receipt.delivery_status == ReminderReceipt.ACCEPTED:
                    return "already_accepted", receipt
                # A prior process may have reached the broker without recording
                # acceptance. Never blind-retry this task/day claim.
                if receipt.delivery_status != ReminderReceipt.AMBIGUOUS:
                    receipt.delivery_status = ReminderReceipt.AMBIGUOUS
                    receipt.save(update_fields=["delivery_status", "updated"])
                raise ReminderOutcomeAmbiguous(receipt)

            submission_title = (
                task.submission.title if task.submission else "your speaker action list"
            )
            due_date = task.due_date.isoformat() if task.due_date else "date not set"
            mail = QueuedMail.objects.create(
                event=event,
                subject=f"Speaker action needed: {task.definition.name} · {event.name}"[:200],
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
            communication = SpeakerCommunicationLog.objects.create(
                event=event,
                speaker=task.speaker,
                kind=SpeakerCommunicationLog.AUTOMATED_REMINDER,
                subject=mail.subject,
                rendered_body=mail.text,
                outcome=SpeakerCommunicationLog.FAILED,
                outcome_detail="Delivery was not attempted.",
                queued_mail_id=mail.pk,
                actor=None,
            )

        try:
            mail.send(orga=False)
        except Exception:
            ReminderReceipt.objects.filter(pk=receipt.pk).update(
                delivery_status=ReminderReceipt.AMBIGUOUS
            )
            SpeakerCommunicationLog.objects.filter(pk=communication.pk).update(
                outcome=SpeakerCommunicationLog.FAILED,
                outcome_detail="Broker outcome is ambiguous; automatic retry suppressed.",
            )
            receipt.delivery_status = ReminderReceipt.AMBIGUOUS
            raise ReminderOutcomeAmbiguous(receipt) from None
        ReminderReceipt.objects.filter(pk=receipt.pk).update(
            delivery_status=ReminderReceipt.ACCEPTED
        )
        SpeakerCommunicationLog.objects.filter(pk=communication.pk).update(
            outcome=SpeakerCommunicationLog.SENT,
            outcome_detail="Pretalx accepted the automated reminder for delivery.",
        )
        receipt.delivery_status = ReminderReceipt.ACCEPTED
        return "queued", receipt


def queue_reminders(event, tasks=None, reminder_key="onboarding-due", *, scheduled_run=None):
    if tasks is None:
        tasks = OnboardingTask.objects.filter(
            event=event, status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED)
        ).select_related("speaker", "submission", "definition")
    queued = 0
    with scope(event=event):
        for task in tasks:
            outcome, _receipt = queue_reminder_task(
                event, task, reminder_key, scheduled_run=scheduled_run
            )
            if outcome == "queued":
                queued += 1
    return queued
