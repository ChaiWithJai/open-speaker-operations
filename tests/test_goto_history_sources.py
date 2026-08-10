import json
from pathlib import Path

from pretalx_speakerops.history_sources import (
    GOTO_SCHEDULE_SOURCES,
    extract_goto_schedule_data,
    normalize_goto_schedule,
)

ROOT = Path(__file__).resolve().parents[1]
GOTO_CATALOG = ROOT / "pretalx_speakerops/data/conferences/goto.json"


def test_schedule_payload_extraction_and_furniture_exclusion():
    sessions = []
    for index in range(28):
        speaker_count = 2 if index < 3 else 1
        sessions.append(
            {
                "id": 5000 + index,
                "title": f"Session {index}",
                "type": "Session",
                "details_url": f"/ai-days-2023/sessions/{5000 + index}",
                "track": None,
                "tags": ["ai"],
                "speakers": [
                    {"id": 6000 + index * 2 + offset, "name": f"Speaker {index}-{offset}"}
                    for offset in range(speaker_count)
                ],
            }
        )
    sessions.extend(
        [
            {
                "id": 7000,
                "title": "CTO Breakfast",
                "type": "Session",
                "details_url": "/ai-days-2023/sessions/7000",
                "tags": [],
                "speakers": [{"id": 7001, "name": "Host"}],
            },
            {
                "id": 7002,
                "title": "Event Kickoff",
                "type": "Session",
                "details_url": "/ai-days-2023/sessions/7002",
                "tags": [],
                "speakers": [],
            },
        ]
    )
    payload = {
        "conference_id": 78,
        "schedule_data": {
            "days": [
                {
                    "date": "2023-10-24",
                    "time_slots": [{"sessions": sessions}],
                }
            ]
        },
    }
    html = (
        '<div id="schedule-container" data-schedule-data="'
        + json.dumps(payload).replace('"', "&quot;")
        + '"></div>'
    )

    edition = normalize_goto_schedule(
        "goto-community-day-chicago-2023",
        extract_goto_schedule_data(html),
        retrieved_at="2026-08-10T07:21:01Z",
        source_sha256="a" * 64,
    )

    assert len(edition["talks"]) == 28
    assert sum(len(talk["speakers"]) for talk in edition["talks"]) == 31
    assert edition["excluded_schedule_rows"] == {"furniture": 1, "speakerless": 1}
    assert all(talk["abstract"] == "" for talk in edition["talks"])
    assert all(
        speaker["biography"] == "" for talk in edition["talks"] for speaker in talk["speakers"]
    )


def test_committed_goto_recovery_counts_exclusions_and_provenance():
    series = json.loads(GOTO_CATALOG.read_text(encoding="utf-8"))["series"][0]
    editions = {row["external_key"]: row for row in series["editions"]}
    expected = {
        "goto-amsterdam-2020": (54, 52, 60, 0, {"tba": 2}),
        "goto-copenhagen-2020": (66, 27, 30, 0, {"speakerless": 23}),
        "goto-community-day-chicago-2023": (
            30,
            28,
            31,
            0,
            {"furniture": 1, "speakerless": 1},
        ),
        "goto-copenhagen-2026": (
            85,
            42,
            44,
            25,
            {"outside_main_program": 32, "speakerless": 11},
        ),
        "accelerate-chicago-2026": (
            31,
            28,
            31,
            2,
            {"outside_main_program": 2, "speakerless": 1},
        ),
    }
    expected_hashes = {
        "goto-amsterdam-2020": "965929817d06c36a42ec11c115517c9cfc38fcd80d2819defdaebf47529a8562",
        "goto-copenhagen-2020": "57359303a3cbb7a4dff071777c2dab18670266f43b2ded01aa70d223e4970f24",
        "goto-community-day-chicago-2023": (
            "57ae8e2d4866124fd3fdbd50af2f25d82276bac7b0c6f6789747beda620ed3b5"
        ),
        "goto-copenhagen-2026": "d4aea002edb0b016a6139abce020618529cc68d5e1a5555e78852414a1010825",
        "accelerate-chicago-2026": (
            "6028273124bd15c0463957117f5c9abc0db2a73c7768a7284a607ebca5a7fb39"
        ),
    }

    for edition_key, (rows, talks, credits, masterclasses, exclusions) in expected.items():
        edition = editions[edition_key]
        recovered = [talk for talk in edition["talks"] if talk["session_format"] != "Masterclass"]
        retained = [talk for talk in edition["talks"] if talk["session_format"] == "Masterclass"]
        assert (
            edition["published_schedule_row_count"],
            len(recovered),
            sum(len(talk["speakers"]) for talk in recovered),
            len(retained),
            edition["excluded_schedule_rows"],
        ) == (rows, talks, credits, masterclasses, exclusions)
        assert edition["source_snapshot"] == {
            "retrieved_at": "2026-08-10T07:21:01Z",
            "url": GOTO_SCHEDULE_SOURCES[edition_key]["schedule_url"],
            "sha256": expected_hashes[edition_key],
            "sha256_scope": "canonical data-schedule-data JSON",
        }
        assert edition["source_version"] == f"sha256:{expected_hashes[edition_key]}"
        assert all(talk["speakers"] for talk in recovered)
        assert not any(talk["title"].casefold() == "tba" for talk in recovered)

    assert sum(expected[key][1] for key in expected) == 177
    assert sum(expected[key][2] for key in expected) == 196
