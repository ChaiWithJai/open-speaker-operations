import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.mail.models import QueuedMail

from ...models import ScheduledReminderRun, SpeakerCommunicationLog


class Command(BaseCommand):
    help = "Verify sanitized, correlated evidence for the daily automated speaker reminder."

    def add_arguments(self, parser):
        parser.add_argument("--event", required=True, help="Event slug to verify.")
        parser.add_argument(
            "--as-of",
            help="ISO date used by the daily reminder idempotency key (defaults to today).",
        )

    def handle(self, *args, **options):
        try:
            as_of = date.fromisoformat(options["as_of"]) if options.get("as_of") else None
        except ValueError as exc:
            raise CommandError("--as-of must be an ISO date (YYYY-MM-DD).") from exc
        as_of = as_of or timezone.localdate()

        try:
            event = Event.objects.get(slug=options["event"])
        except Event.DoesNotExist as exc:
            raise CommandError("No event matched that slug.") from exc

        reminder_key = f"onboarding-overdue:{as_of.isoformat()}"
        with scope(event=event):
            runs = list(
                ScheduledReminderRun.objects.filter(event=event, schedule_date=as_of)
                .prefetch_related("receipts")
                .order_by("pk")
            )
            completed_runs = [
                run
                for run in runs
                if run.status == ScheduledReminderRun.COMPLETED
                and run.dispatch_origin == ScheduledReminderRun.ORIGIN_BEAT
                and run.schedule_name == "speakerops-due-speaker-reminders-daily"
                and run.completed_at
                and run.scheduled_for <= run.started_at <= run.scheduled_for + timedelta(hours=1)
            ]
            receipts = [receipt for run in completed_runs for receipt in run.receipts.all()]
            receipt_pairs = {
                (receipt.speaker_id, receipt.queued_mail_id)
                for receipt in receipts
                if receipt.queued_mail_id
            }
            queued_mail_ids = {mail_id for _speaker_id, mail_id in receipt_pairs}
            sent_mail_ids = set(
                QueuedMail.objects.filter(
                    event=event, pk__in=queued_mail_ids, sent__isnull=False
                ).values_list("pk", flat=True)
            )
            system_logs = list(
                SpeakerCommunicationLog.objects.filter(
                    event=event,
                    kind=SpeakerCommunicationLog.AUTOMATED_REMINDER,
                    queued_mail_id__in=queued_mail_ids,
                    actor__isnull=True,
                ).values("speaker_id", "queued_mail_id", "outcome")
            )
            sent_log_pairs = {
                (row["speaker_id"], row["queued_mail_id"])
                for row in system_logs
                if row["outcome"] == SpeakerCommunicationLog.SENT
            }
        run_task_ids = [run.celery_task_id for run in completed_runs]
        exact_run_counts = bool(completed_runs) and all(
            run.eligible_count == run.accepted_count == run.receipts.count() > 0
            for run in completed_runs
        )
        criteria = {
            "one_completed_run_in_schedule_window": len(completed_runs) == 1,
            "run_counts_are_nonzero_and_exact": exact_run_counts,
            "all_receipts_are_date_scoped_and_accepted": bool(receipts)
            and all(
                receipt.reminder_key == reminder_key and receipt.delivery_status == "accepted"
                for receipt in receipts
            ),
            "all_tasks_were_overdue_at_dispatch": bool(receipts)
            and all(
                receipt.due_date_at_dispatch is not None and receipt.due_date_at_dispatch < as_of
                for receipt in receipts
            ),
            "sent_mail_set_exactly_matches_receipts": queued_mail_ids == sent_mail_ids
            and len(queued_mail_ids) == len(receipts),
            "sent_system_history_set_exactly_matches_receipts": (
                receipt_pairs == sent_log_pairs
                and len(receipt_pairs) == len(receipts) == len(system_logs)
            ),
        }
        result = {
            "schema": "speakerops.reminder-evidence.v1",
            "event_slug": event.slug,
            "as_of": as_of.isoformat(),
            "reminder_key": reminder_key,
            "completed_run_count": len(completed_runs),
            "celery_task_ids": run_task_ids,
            "receipt_count": len(receipts),
            "system_communication_count": len(system_logs),
            "sent_queued_mail_count": len(sent_mail_ids),
            "criteria": criteria,
            "verified": all(criteria.values()),
        }
        self.stdout.write(json.dumps(result, sort_keys=True))
        if not result["verified"]:
            raise CommandError("Automated reminder evidence is incomplete.")
