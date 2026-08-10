#!/usr/bin/env python3
"""Refresh the five recoverable first-party GOTO schedule snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from pretalx_speakerops.history_sources import (
    GOTO_SCHEDULE_SOURCES,
    extract_goto_schedule_data,
    normalize_goto_schedule,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pretalx_speakerops/data/conferences/goto.json"
USER_AGENT = "speakerops-history/1"


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read()
    return body.decode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retrieved-at",
        help="ISO-8601 retrieval time; defaults to the current UTC time",
    )
    args = parser.parse_args()
    retrieved_at = args.retrieved_at or datetime.now(UTC).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    series = document["series"][0]
    editions = {edition["external_key"]: edition for edition in series["editions"]}

    for edition_key, config in GOTO_SCHEDULE_SOURCES.items():
        page = fetch(config["schedule_url"])
        payload = extract_goto_schedule_data(page)
        canonical_payload = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        digest = hashlib.sha256(canonical_payload).hexdigest()
        recovered = normalize_goto_schedule(
            edition_key,
            payload,
            retrieved_at=retrieved_at,
            source_sha256=digest,
        )
        existing = editions[edition_key]
        retained = [
            talk
            for talk in existing.get("talks", [])
            if talk.get("session_format") == "Masterclass"
        ]
        recovered["talks"] = sorted(
            retained + recovered["talks"], key=lambda row: row["external_key"]
        )
        editions[edition_key] = recovered
        recovered_credits = sum(
            len(talk["speakers"]) for talk in recovered["talks"]
        ) - sum(len(talk["speakers"]) for talk in retained)
        print(
            f"{edition_key}: {len(recovered['talks']) - len(retained)} recovered talks, "
            f"{recovered_credits} credits; "
            f"retained {len(retained)} masterclasses"
        )

    series["editions"] = [editions[row["external_key"]] for row in series["editions"]]
    document["generated_at"] = retrieved_at
    CATALOG.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
