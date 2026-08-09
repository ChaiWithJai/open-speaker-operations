import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pretalx_speakerops.history_coverage import analyze_catalog, build_contract


class Command(BaseCommand):
    help = "Audit conference history catalog completeness and provenance"

    def add_arguments(self, parser):
        parser.add_argument("source", help="Catalog directory or normalized JSON file")
        parser.add_argument("--contract", help="Expected full-corpus contract JSON")
        parser.add_argument(
            "--write-contract",
            help="Write observed expectations for explicit review after a source refresh",
        )
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        report = analyze_catalog(options["source"], contract=options["contract"])
        self.stdout.write(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        if options["write_contract"]:
            if report.errors or report.incomplete_scopes:
                raise CommandError("Cannot write a contract for an incomplete catalog")
            Path(options["write_contract"]).write_text(
                json.dumps(build_contract(report), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if options["strict"] and not report.structurally_complete:
            raise CommandError("Conference history catalog is not structurally complete")
