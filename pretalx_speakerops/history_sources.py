"""Deterministic normalizers for first-party conference-history sources."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from html.parser import HTMLParser

AIE_WF26_SESSIONS_URL = "https://www.ai.engineer/worldsfair/2026/sessions.json"
AIE_WF26_SPEAKERS_URL = "https://www.ai.engineer/worldsfair/2026/speakers.json"
AIE_WF26_WEBSITE = "https://www.ai.engineer/worldsfair/2026"

GOTO_SCHEDULE_SOURCES = {
    "goto-amsterdam-2020": {
        "conference_id": 24,
        "name": "GOTO Amsterdam 2020",
        "location": "Amsterdam, Netherlands",
        "date_from": "2020-12-07",
        "date_to": "2020-12-10",
        "schedule_url": "https://web.archive.org/web/20201024180755id_/https://gotoams.nl/2020/schedule",
        "event_url": "https://web.archive.org/web/20201024180755id_/https://gotoams.nl/2020",
        "url_base": "https://web.archive.org/web/20201024180755id_/https://gotoams.nl",
        "expected": (54, 52, 60),
    },
    "goto-copenhagen-2020": {
        "conference_id": 33,
        "name": "GOTO Copenhagen 2020",
        "location": "Copenhagen, Denmark",
        "date_from": "2020-11-09",
        "date_to": "2020-11-13",
        "schedule_url": "https://web.archive.org/web/20200922205801id_/https://gotocph.com/november-2020/schedule",
        "event_url": "https://web.archive.org/web/20200922205801id_/https://gotocph.com/november-2020",
        "url_base": "https://web.archive.org/web/20200922205801id_/https://gotocph.com",
        "expected": (66, 27, 30),
    },
    "goto-community-day-chicago-2023": {
        "conference_id": 78,
        "name": "GOTO Community Day Chicago 2023",
        "location": "Chicago, IL",
        "date_from": "2023-10-24",
        "date_to": "2023-10-24",
        "schedule_url": "https://gotochgo.com/ai-days-2023/schedule",
        "event_url": "https://gotochgo.com/ai-days-2023",
        "url_base": "https://gotochgo.com",
        "excluded_titles": {"cto breakfast"},
        "expected": (30, 28, 31),
    },
    "goto-copenhagen-2026": {
        "conference_id": 135,
        "name": "GOTO Copenhagen 2026",
        "location": "Copenhagen, Denmark",
        "date_from": "2026-09-28",
        "date_to": "2026-10-02",
        "program_dates": {"2026-09-30", "2026-10-01", "2026-10-02"},
        "schedule_url": "https://gotocph.com/2026/schedule?date=2026-09-28&video=false",
        "event_url": "https://gotocph.com/2026",
        "url_base": "https://gotocph.com",
        "expected": (85, 42, 44),
    },
    "accelerate-chicago-2026": {
        "conference_id": 142,
        "name": "Accelerate Chicago 2026",
        "location": "Chicago, IL",
        "date_from": "2026-06-22",
        "date_to": "2026-06-24",
        "program_dates": {"2026-06-23", "2026-06-24"},
        "schedule_url": "https://gotochgo.com/accelerate-chicago-2026/schedule",
        "event_url": "https://gotochgo.com/accelerate-chicago-2026",
        "url_base": "https://gotochgo.com",
        "expected": (31, 28, 31),
    },
}


class _ScheduleDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.schedule_data = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id") == "schedule-container":
            self.schedule_data = attributes.get("data-schedule-data")


def extract_goto_schedule_data(document):
    """Extract the first-party schedule payload embedded in an event page."""
    parser = _ScheduleDataParser()
    parser.feed(document)
    if not parser.schedule_data:
        raise ValueError("GOTO schedule page has no data-schedule-data payload")
    return json.loads(parser.schedule_data)


def _goto_source_url(base, path):
    # urljoin collapses the second scheme inside Wayback's /https:// path.
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def normalize_goto_schedule(edition_key, payload, *, retrieved_at, source_sha256):
    """Normalize one first-party GOTO schedule without republishing source prose."""
    config = GOTO_SCHEDULE_SOURCES[edition_key]
    if payload.get("conference_id") != config["conference_id"]:
        raise ValueError(f"Unexpected GOTO conference id: {payload.get('conference_id')!r}")
    days = payload.get("schedule_data", {}).get("days", [])
    rows = [
        (day.get("date"), session)
        for day in days
        for slot in day.get("time_slots", [])
        for session in slot.get("sessions", [])
    ]
    expected_rows, expected_talks, expected_credits = config["expected"]
    if len(rows) != expected_rows:
        raise ValueError(
            f"{edition_key} source drift: expected {expected_rows} rows, got {len(rows)}"
        )

    talks_by_key = {}
    excluded_counts = Counter()
    for date, row in rows:
        title = _normalized_source_text(row.get("title"))
        if config.get("program_dates") and date not in config["program_dates"]:
            excluded_counts["outside_main_program"] += 1
            continue
        if not row.get("speakers"):
            excluded_counts["speakerless"] += 1
            continue
        if title.casefold() == "tba":
            excluded_counts["tba"] += 1
            continue
        if title.casefold() in config.get("excluded_titles", set()):
            excluded_counts["furniture"] += 1
            continue
        external_key = str(row["id"])
        speakers = [
            {
                "name": _normalized_source_text(speaker["name"]),
                "source_url": _goto_source_url(config["event_url"], f"speakers/{speaker['id']}"),
                "source_updated_at": retrieved_at,
                "biography": "",
            }
            for speaker in row["speakers"]
        ]
        talk = {
            "external_key": external_key,
            "title": title,
            "abstract": "",
            "session_format": _normalized_source_text(row.get("type")),
            "track": _normalized_source_text(row.get("track")),
            "level": "",
            "topics": [
                _normalized_source_text(tag.get("name") if isinstance(tag, dict) else tag)
                for tag in row.get("tags") or []
            ],
            "recording_url": "",
            "source_url": _goto_source_url(config["url_base"], row["details_url"]),
            "source_updated_at": retrieved_at,
            "speakers": speakers,
        }
        previous = talks_by_key.setdefault(external_key, talk)
        if previous != talk:
            raise ValueError(f"{edition_key} repeated session {external_key} changed identity")

    talks = sorted(talks_by_key.values(), key=lambda row: row["external_key"])
    credits = sum(len(talk["speakers"]) for talk in talks)
    if (len(talks), credits) != (expected_talks, expected_credits):
        raise ValueError(
            f"{edition_key} source drift: expected {expected_talks}/{expected_credits} "
            f"talks/credits, got {len(talks)}/{credits}"
        )
    return {
        "external_key": edition_key,
        "name": config["name"],
        "date_from": config["date_from"],
        "date_to": config["date_to"],
        "location": config["location"],
        "source_url": config["event_url"],
        "source_updated_at": retrieved_at,
        "source_version": f"sha256:{source_sha256}",
        "published_schedule_row_count": len(rows),
        "excluded_schedule_rows": dict(sorted(excluded_counts.items())),
        "source_snapshot": {
            "retrieved_at": retrieved_at,
            "url": config["schedule_url"],
            "sha256": source_sha256,
            "sha256_scope": "canonical data-schedule-data JSON",
        },
        "talks": talks,
    }


def _normalized_source_text(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def _session_key(session):
    identity = json.dumps(
        [
            _normalized_source_text(session["title"]),
            _normalized_source_text(session.get("day")),
            _normalized_source_text(session.get("time")),
            _normalized_source_text(session.get("room")),
            sorted(_normalized_source_text(name) for name in session.get("speakers") or []),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"wf26-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def normalize_aie_worldsfair_2026(session_feed, speaker_feed, *, retrieved_at):
    """Normalize the official WF26 feeds without republishing source prose.

    The source exposes no stable session identifiers or update timestamp. Keys
    therefore digest the published title, schedule coordinates, and sorted credits.
    """
    expected_conference = "AI Engineer World's Fair 2026"
    for label, payload, collection, total in (
        ("sessions", session_feed, "sessions", "totalSessions"),
        ("speakers", speaker_feed, "speakers", "totalSpeakers"),
    ):
        if payload.get("conference") != expected_conference:
            raise ValueError(f"Unexpected {label} conference: {payload.get('conference')!r}")
        if payload.get(total) != len(payload.get(collection, [])):
            raise ValueError(f"WF26 {label} total does not match its published collection")
    if session_feed.get("scheduleVersion") != speaker_feed.get("scheduleVersion"):
        raise ValueError("WF26 feeds publish different schedule versions")
    if session_feed.get("dates") != "June 29 - July 2, 2026":
        raise ValueError(f"Unexpected WF26 dates: {session_feed.get('dates')!r}")
    if session_feed.get("location") != "San Francisco, CA":
        raise ValueError(f"Unexpected WF26 location: {session_feed.get('location')!r}")

    speaker_rows = speaker_feed["speakers"]
    speaker_names = [row.get("name") for row in speaker_rows]
    if any(not name for name in speaker_names) or len(speaker_names) != len(set(speaker_names)):
        raise ValueError("WF26 speaker directory names must be present and unique")
    speakers_by_name = {row["name"]: row for row in speaker_rows}

    sessions = session_feed["sessions"]
    title_counts = Counter(row["title"] for row in sessions)
    if not any(count > 1 for count in title_counts.values()):
        raise ValueError("WF26 source unexpectedly has no duplicate session titles")
    talks = []
    unresolved_speaker_references = []
    for row in sessions:
        if not row.get("title"):
            raise ValueError("WF26 sessions require a title")
        speakers = []
        for name in row["speakers"]:
            directory_row = speakers_by_name.get(name)
            if not directory_row:
                unresolved_speaker_references.append(name)
                continue
            speakers.append(
                {
                    "name": name,
                    "source_url": AIE_WF26_SPEAKERS_URL,
                    "source_updated_at": retrieved_at,
                    # Prose is intentionally excluded by the catalog licensing policy.
                    "biography": "",
                }
            )
        talks.append(
            {
                "external_key": _session_key(row),
                "title": _normalized_source_text(row["title"]),
                # Prose is intentionally excluded by the catalog licensing policy.
                "abstract": "",
                "session_format": row.get("type") or "",
                "track": row.get("track") or "",
                "level": "",
                "topics": [],
                "recording_url": "",
                "source_url": AIE_WF26_SESSIONS_URL,
                "source_updated_at": retrieved_at,
                "speakers": speakers,
            }
        )
    keys = [talk["external_key"] for talk in talks]
    if len(keys) != len(set(keys)):
        raise ValueError("WF26 deterministic session keys are not unique")

    return {
        "external_key": "worldsfair-2026",
        "name": expected_conference,
        "date_from": "2026-06-29",
        "date_to": "2026-07-02",
        "location": "San Francisco, CA",
        "source_url": AIE_WF26_WEBSITE,
        "source_updated_at": retrieved_at,
        "source_version": f"scheduleVersion:{session_feed['scheduleVersion']}",
        "published_session_count": len(session_feed["sessions"]),
        "uncredited_session_count": sum(not row.get("speakers") for row in sessions),
        "unresolved_speaker_references": sorted(set(unresolved_speaker_references)),
        "expected_missing_speaker_credit_count": sum(not talk["speakers"] for talk in talks),
        "talks": talks,
    }
