import io
import json
from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from django_scopes import scope

from pretalx_speakerops.models import OnboardingTask, SpeakerCommunicationLog
from pretalx_speakerops.tasks import send_due_speaker_reminders


@pytest.mark.django_db(transaction=True)
def test_reminder_evidence_command_proves_sanitized_correlated_history(event, users):
    today = timezone.localdate()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.due_date = today - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])

    with patch("pretalx.common.mail.mail_send_task.apply_async"):
        assert send_due_speaker_reminders(
            event.slug,
            as_of=today,
            celery_task_id="scheduled-test-task",
            started_at=datetime.combine(today, time(hour=9, minute=1), tzinfo=UTC),
        ) == {event.slug: 1}

    output = io.StringIO()
    call_command(
        "speakerops_verify_reminder_evidence",
        event=event.slug,
        as_of=today.isoformat(),
        stdout=output,
    )
    result = json.loads(output.getvalue())
    assert result == {
        "as_of": today.isoformat(),
        "celery_task_ids": ["scheduled-test-task"],
        "completed_run_count": 1,
        "criteria": {
            "all_receipts_are_date_scoped_and_accepted": True,
            "all_tasks_were_overdue_at_dispatch": True,
            "one_completed_run_in_schedule_window": True,
            "run_counts_are_nonzero_and_exact": True,
            "sent_mail_set_exactly_matches_receipts": True,
            "sent_system_history_set_exactly_matches_receipts": True,
        },
        "event_slug": event.slug,
        "receipt_count": 1,
        "reminder_key": f"onboarding-overdue:{today.isoformat()}",
        "schema": "speakerops.reminder-evidence.v1",
        "sent_queued_mail_count": 1,
        "system_communication_count": 1,
        "verified": True,
    }
    assert users["speaker"].email not in output.getvalue()
    assert task.definition.name not in output.getvalue()


@pytest.mark.django_db
def test_reminder_evidence_command_fails_closed_without_daily_receipt(event):
    with pytest.raises(CommandError, match="evidence is incomplete"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of=timezone.localdate().isoformat(),
            stdout=io.StringIO(),
        )


@pytest.mark.django_db
def test_reminder_evidence_command_rejects_invalid_date(event):
    with pytest.raises(CommandError, match="ISO date"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of="not-a-date",
            stdout=io.StringIO(),
        )


@pytest.mark.django_db(transaction=True)
def test_reminder_evidence_command_requires_system_authored_history(event, users):
    today = timezone.localdate()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.due_date = today - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])

    with patch("pretalx.common.mail.mail_send_task.apply_async"):
        send_due_speaker_reminders(
            event.slug,
            as_of=today,
            celery_task_id="scheduled-test-task",
            started_at=datetime.combine(today, time(hour=9, minute=1), tzinfo=UTC),
        )
    with scope(event=event):
        SpeakerCommunicationLog.objects.filter(
            event=event, kind=SpeakerCommunicationLog.AUTOMATED_REMINDER
        ).update(actor=users["chair"])

    with pytest.raises(CommandError, match="evidence is incomplete"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of=today.isoformat(),
            stdout=io.StringIO(),
        )


@pytest.mark.django_db(transaction=True)
def test_reminder_evidence_command_rejects_manual_invocation(event, users):
    today = timezone.localdate()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.due_date = today - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])
    with patch("pretalx.common.mail.mail_send_task.apply_async"):
        send_due_speaker_reminders(event.slug, as_of=today)
    with pytest.raises(CommandError, match="evidence is incomplete"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of=today.isoformat(),
            stdout=io.StringIO(),
        )


@pytest.mark.django_db(transaction=True)
def test_reminder_evidence_command_rejects_partial_correlation(event, users):
    today = timezone.localdate()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        tasks = list(
            OnboardingTask.objects.filter(
                event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
            )[:2]
        )
        assert len(tasks) == 2
        for task in tasks:
            task.due_date = today - timedelta(days=1)
            task.save(update_fields=["due_date", "updated"])
    with patch("pretalx.common.mail.mail_send_task.apply_async"):
        send_due_speaker_reminders(
            event.slug,
            as_of=today,
            celery_task_id="scheduled-two-task-run",
            started_at=datetime.combine(today, time(hour=9, minute=1), tzinfo=UTC),
        )
    with scope(event=event):
        SpeakerCommunicationLog.objects.filter(
            event=event, kind=SpeakerCommunicationLog.AUTOMATED_REMINDER
        ).order_by("pk").last().delete()
    with pytest.raises(CommandError, match="evidence is incomplete"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of=today.isoformat(),
            stdout=io.StringIO(),
        )


@pytest.mark.django_db(transaction=True)
def test_reminder_evidence_command_rejects_ineligible_due_date_snapshot(event, users):
    today = timezone.localdate()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.due_date = today - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])
    with patch("pretalx.common.mail.mail_send_task.apply_async"):
        send_due_speaker_reminders(
            event.slug,
            as_of=today,
            celery_task_id="scheduled-ineligible-test",
            started_at=datetime.combine(today, time(hour=9, minute=1), tzinfo=UTC),
        )
    with scope(event=event):
        receipt = event.reminderreceipt_set.get()
        receipt.due_date_at_dispatch = today
        receipt.save(update_fields=["due_date_at_dispatch", "updated"])
    with pytest.raises(CommandError, match="evidence is incomplete"):
        call_command(
            "speakerops_verify_reminder_evidence",
            event=event.slug,
            as_of=today.isoformat(),
            stdout=io.StringIO(),
        )
