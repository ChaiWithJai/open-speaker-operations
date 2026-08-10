import json
from pathlib import Path

import pytest

from pretalx_speakerops.history_sources import normalize_aie_worldsfair_2026

ROOT = Path(__file__).resolve().parents[1]
AIE_CATALOG = ROOT / "pretalx_speakerops/data/conferences/ai_engineer.json"


def _feeds():
    sessions = {
        "conference": "AI Engineer World's Fair 2026",
        "dates": "June 29 - July 2, 2026",
        "location": "San Francisco, CA",
        "scheduleVersion": 4945,
        "totalSessions": 3,
        "sessions": [
            {
                "title": "Same title",
                "description": "Licensed source prose is not republished.",
                "day": "Day 2",
                "time": "10:00am-10:20am",
                "room": "One",
                "type": "session",
                "track": "Agents",
                "status": "confirmed",
                "speakers": ["Ada Example"],
            },
            {
                "title": "Same title",
                "description": "Different source prose.",
                "day": "Day 3",
                "time": "11:00am-11:20am",
                "room": "Two",
                "type": "keynote",
                "track": None,
                "status": "confirmed",
                "speakers": ["TBD — Sponsor"],
            },
            {
                "title": "Uncredited schedule block",
                "description": "Not a speaker-history record.",
                "day": "Day 4",
                "time": "12:00pm",
                "room": "Three",
                "type": "session",
                "track": None,
                "status": "confirmed",
                "speakers": [],
            },
        ],
    }
    speakers = {
        "conference": sessions["conference"],
        "dates": sessions["dates"],
        "location": sessions["location"],
        "scheduleVersion": sessions["scheduleVersion"],
        "totalSpeakers": 1,
        "speakers": [
            {
                "name": "Ada Example",
                "bio": "Licensed source biography is not republished.",
                "sessions": [],
            }
        ],
    }
    return sessions, speakers


def test_worldsfair_2026_normalizer_is_complete_stable_and_provenance_backed():
    sessions, speakers = _feeds()
    edition = normalize_aie_worldsfair_2026(sessions, speakers, retrieved_at="2026-08-10T01:54:00Z")

    assert edition["source_version"] == "scheduleVersion:4945"
    assert (edition["published_session_count"], edition["uncredited_session_count"]) == (3, 1)
    assert edition["unresolved_speaker_references"] == ["TBD — Sponsor"]
    assert edition["expected_missing_speaker_credit_count"] == 2
    assert len(edition["talks"]) == 3
    assert len({talk["external_key"] for talk in edition["talks"]}) == 3
    assert all(talk["external_key"].startswith("wf26-") for talk in edition["talks"])
    assert edition["talks"][0]["abstract"] == ""
    assert edition["talks"][0]["speakers"][0]["biography"] == ""
    assert edition["talks"][1]["speakers"] == []
    assert edition["talks"][2]["speakers"] == []


def test_worldsfair_2026_normalizer_rejects_feed_version_drift():
    sessions, speakers = _feeds()
    speakers["scheduleVersion"] += 1

    with pytest.raises(ValueError, match="different schedule versions"):
        normalize_aie_worldsfair_2026(sessions, speakers, retrieved_at="2026-08-10T01:54:00Z")


def test_committed_aie_snapshot_covers_current_program_and_records_source_conflicts():
    series = json.loads(AIE_CATALOG.read_text(encoding="utf-8"))["series"][0]
    editions = {row["external_key"]: row for row in series["editions"]}
    current = editions["worldsfair-2026"]

    assert current["source_version"] == "scheduleVersion:4945"
    assert (
        current["published_session_count"],
        len(current["talks"]),
        sum(len(talk["speakers"]) for talk in current["talks"]),
    ) == (561, 561, 668)
    assert current["expected_missing_speaker_credit_count"] == 16
    assert current["unresolved_speaker_references"] == ["TBD — Sonar"]
    assert [source["sha256"] for source in current["source_snapshot"]["sources"]] == [
        "d4e52d6fad9fe08f9852a4c83577f27ea5122f23bcfaa79354334a156861d610",
        "f28556235e945aabc435b6b883a201918f34c9a25dffd294d4fba6cfb91a3905",
    ]
    assert (editions["worldsfair-2025"]["date_from"], editions["worldsfair-2025"]["date_to"]) == (
        "2025-06-03",
        "2025-06-05",
    )
    assert (editions["worldsfair-2027"]["date_from"], editions["worldsfair-2027"]["date_to"]) == (
        "",
        "",
    )
    assert any(
        gap["item"] == "AI Engineer World's Fair 2025 dates" and gap["scope"] == "metadata_conflict"
        for gap in series["source_policy"]["known_gaps"]
    )
