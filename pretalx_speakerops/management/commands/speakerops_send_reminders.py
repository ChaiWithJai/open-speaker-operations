import json

from django.core.management.base import BaseCommand, CommandError

from ...tasks import send_due_speaker_reminders


class Command(BaseCommand):
    help = "Queue idempotent reminders for every overdue Speaker Operations task."

    def add_arguments(self, parser):
        parser.add_argument("--event", help="Limit processing to one event slug.")
        parser.add_argument(
            "--as-of",
            help="Evaluate overdue tasks on this ISO date (deterministic rehearsal/testing).",
        )

    def handle(self, *args, **options):
        try:
            result = send_due_speaker_reminders(
                event_slug=options.get("event"), as_of=options.get("as_of")
            )
        except ValueError as exc:
            raise CommandError("--as-of must be an ISO date (YYYY-MM-DD).") from exc
        if options.get("event") and options["event"] not in result:
            raise CommandError("No enabled Speaker Operations event matched that slug.")
        self.stdout.write(json.dumps(result, sort_keys=True))
