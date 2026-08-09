from django_scopes import scope
from pretalx.mail.models import MailTemplate

from ..models import OnboardingTask, ReminderReceipt


def queue_reminders(event, tasks=None, reminder_key="onboarding-due"):
    if tasks is None:
        tasks = OnboardingTask.objects.filter(
            event=event, status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED)
        ).select_related("speaker", "submission", "definition")
    queued = 0
    with scope(event=event):
        template, _ = MailTemplate.objects.get_or_create(
            event=event,
            role=None,
            defaults={
                "subject": "Speaker action needed: {event_name}",
                "text": "Please complete {task_name} for {submission_title}.",
            },
        )
        for task in tasks:
            receipt, created = ReminderReceipt.objects.get_or_create(
                event=event,
                task=task,
                speaker=task.speaker,
                reminder_key=reminder_key,
            )
            if not created:
                continue
            mail = template.to_mail(
                task.speaker,
                event,
                context_kwargs={"submission": task.submission},
                context={
                    "task_name": task.definition.name,
                    "submission_title": task.submission.title,
                },
            )
            receipt.queued_mail_id = mail.pk
            receipt.save(update_fields=["queued_mail_id", "updated"])
            queued += 1
    return queued
