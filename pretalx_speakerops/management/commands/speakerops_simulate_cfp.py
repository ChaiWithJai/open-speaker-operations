from django.core.management.base import BaseCommand
from django.db import transaction
from pretalx.event.models import Event

from pretalx_speakerops.simulation import simulate_cfp


class Command(BaseCommand):
    help = "Simulate the CFP-to-onboarding path at conference scale"

    def add_arguments(self, parser):
        parser.add_argument("event", help="Event slug")
        parser.add_argument("--speakers", type=int, default=1500)
        parser.add_argument(
            "--proposals",
            type=int,
            help="Proposal count; defaults to one proposal per speaker",
        )
        parser.add_argument(
            "--reviewers",
            type=int,
            help="Reviewer count; defaults to one reviewer per 40 proposals",
        )
        parser.add_argument("--acceptance-rate", type=float, default=0.10)
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Persist the synthetic fixture (the default rolls it back)",
        )

    def handle(self, *args, **options):
        event = Event.objects.get(slug=options["event"])
        with transaction.atomic():
            result = simulate_cfp(
                event,
                speaker_count=options["speakers"],
                proposal_count=options["proposals"],
                reviewer_count=options["reviewers"],
                acceptance_rate=options["acceptance_rate"],
            )
            if not options["commit"]:
                transaction.set_rollback(True)
        disposition = "committed" if options["commit"] else "rolled back"
        self.stdout.write(
            self.style.SUCCESS(
                f"CFP simulation {disposition}: {result.speakers} speakers, "
                f"{result.proposals} proposals, {result.reviewers} reviewers, "
                f"{result.reviews} reviews, {result.accepted} accepted, "
                f"{result.waitlisted} waitlisted, {result.rejected} rejected, "
                f"{result.onboarding_tasks} onboarding tasks in "
                f"{result.elapsed_seconds:.2f}s."
            )
        )
