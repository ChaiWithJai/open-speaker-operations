import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pretalx_speakerops.conference_memory import (
    import_document,
    load_documents,
    verify_imported_catalog,
)
from pretalx_speakerops.history_coverage import analyze_catalog


class Command(BaseCommand):
    help = "Import provenance-backed conference history from JSON"

    def add_arguments(self, parser):
        parser.add_argument("source", help="Local JSON path, catalog directory, or HTTPS URL")
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete talks absent from imported editions (requires --confirm-prune)",
        )
        parser.add_argument("--confirm-prune", action="store_true")
        parser.add_argument("--contract", help="Expected full-corpus contract JSON")
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Fail unless database identities exactly match the contracted catalog",
        )
        parser.add_argument("--report", help="Write the successful verification JSON here")

    def handle(self, *args, **options):
        try:
            if options["prune"] and not options["confirm_prune"]:
                raise CommandError("--prune requires --confirm-prune")
            if options["verify"] and not options["contract"]:
                raise CommandError("--verify requires --contract")
            if options["report"] and not options["verify"]:
                raise CommandError("--report requires --verify")
            coverage = analyze_catalog(options["source"], contract=options["contract"])
            if options["contract"] and not coverage.structurally_complete:
                raise CommandError("Conference history catalog does not match its contract")
            totals = {
                "series": 0,
                "editions": 0,
                "talks": 0,
                "speakers": 0,
                "source_identities": 0,
                "deleted_talks": 0,
            }
            with transaction.atomic():
                for _source, document in load_documents(options["source"]):
                    result = import_document(document, prune=options["prune"])
                    for field in totals:
                        totals[field] += getattr(result, field)
                verification = (
                    verify_imported_catalog(options["source"]) if options["verify"] else None
                )
                if verification and not verification.complete:
                    raise CommandError("Imported conference history does not match its catalog")
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        report = {
            "catalog": coverage.as_dict(),
            "database": verification.as_dict() if verification else None,
            "imported": totals,
        }
        if options["report"]:
            Path(options["report"]).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Imported "
                f"{totals['series']} series, {totals['editions']} editions, "
                f"{totals['talks']} talks, and {totals['speakers']} speakers; "
                f"created {totals['source_identities']} source identities; "
                f"deleted {totals['deleted_talks']} stale talks."
            )
        )
        if verification:
            self.stdout.write(
                self.style.SUCCESS(
                    "Verified exact corpus: "
                    f"{verification.series} series, {verification.editions} editions, "
                    f"{verification.talks} talks, {verification.speaker_credits} credits, "
                    f"{verification.speakers} speakers, and "
                    f"{verification.source_identities} source identities."
                )
            )
