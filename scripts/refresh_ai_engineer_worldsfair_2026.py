#!/usr/bin/env python3
"""Refresh the committed AI Engineer World's Fair 2026 history snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from pretalx_speakerops.history_sources import (
    AIE_WF26_SESSIONS_URL,
    AIE_WF26_SPEAKERS_URL,
    normalize_aie_worldsfair_2026,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pretalx_speakerops/data/conferences/ai_engineer.json"
USER_AGENT = "speakerops-history/1"


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read()
        return (
            json.loads(body),
            {
                "url": url,
                "etag": response.headers.get("ETag", ""),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
        )


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
    session_feed, session_snapshot = fetch(AIE_WF26_SESSIONS_URL)
    speaker_feed, speaker_snapshot = fetch(AIE_WF26_SPEAKERS_URL)
    edition = normalize_aie_worldsfair_2026(session_feed, speaker_feed, retrieved_at=retrieved_at)
    edition["source_snapshot"] = {
        "retrieved_at": retrieved_at,
        "schedule_version": session_feed["scheduleVersion"],
        "sources": [session_snapshot, speaker_snapshot],
    }
    series = document["series"][0]
    series["source_policy"]["scope"] = (
        "all issue-41 AI Engineer editions; the complete first-party World's Fair 2026 "
        "schedule and every published credited session recovered from legacy editions"
    )
    editions = [row for row in series["editions"] if row["external_key"] != edition["external_key"]]
    editions.append(edition)
    editions.sort(key=lambda row: (row.get("date_from") or "9999", row["external_key"]))
    series["editions"] = editions

    # The 2027 page has no published dates. Earlier values mirrored the 2026
    # dates one year forward without first-party support.
    future = next(row for row in editions if row["external_key"] == "worldsfair-2027")
    future["date_from"] = ""
    future["date_to"] = ""

    gap_item = "AI Engineer World's Fair 2026 missing speaker identities"
    conflict_item = "AI Engineer World's Fair 2025 dates"
    gaps = [
        row
        for row in series["source_policy"]["known_gaps"]
        if row["item"] not in (gap_item, conflict_item)
    ]
    gaps.append(
        {
            "scope": "identity",
            "item": gap_item,
            "reason": (
                f"Official schedule JSON publishes {edition['uncredited_session_count']} confirmed "
                "entries without speaker names and one TBD — Sonar placeholder absent from the "
                "speaker directory. All sessions are retained, but no identities are invented."
            ),
            "source_url": AIE_WF26_SESSIONS_URL,
        }
    )
    gaps.append(
        {
            "scope": "metadata_conflict",
            "item": conflict_item,
            "reason": (
                "The global first-party llms.txt says June 25–27, 2025, while the "
                "event-specific page and every dated row in the official 271-session JSON say "
                "June 3–5. The edition uses the more specific event sources."
            ),
            "source_url": "https://www.ai.engineer/llms.txt",
        }
    )
    series["source_policy"]["known_gaps"] = gaps
    document["generated_at"] = retrieved_at
    CATALOG.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Refreshed {edition['external_key']} at {edition['source_version']}: "
        f"{len(edition['talks'])} sessions, "
        f"{sum(len(talk['speakers']) for talk in edition['talks'])} credits, "
        f"{edition['uncredited_session_count']} uncredited entries and "
        f"{len(edition['unresolved_speaker_references'])} unresolved placeholders."
    )


if __name__ == "__main__":
    main()
