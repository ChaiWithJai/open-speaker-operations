import pytest
from django.core.management import call_command
from django_scopes import scope
from pretalx.event.models import Event

from pretalx_speakerops.management.commands.speakerops_seed import (
    CFP_DEADLINE,
    CFP_OPENING,
    CONFLICT_FIXTURE_TITLES,
    CURATED_PROGRAM,
    DEMO_END,
    DEMO_START,
    DEMO_WALKTHROUGH_AT,
)
from pretalx_speakerops.models import (
    ExternalIdentity,
    OnboardingTask,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
)
from pretalx_speakerops.program.policy import classify_warnings


def _released_program(event):
    schedule = event.schedules.get(version="m3-demo")
    return tuple(
        (
            slot.submission.title,
            slot.start.isoformat(),
            slot.end.isoformat(),
            str(slot.room.name),
            tuple(
                sorted(
                    (speaker.email, speaker.get_display_name())
                    for speaker in slot.submission.speakers.all()
                )
            ),
        )
        for slot in schedule.talks.filter(
            submission__isnull=False,
            is_visible=True,
        )
        .select_related("submission", "room")
        .prefetch_related("submission__speakers")
        .order_by("start", "room__position", "pk")
    )


def _baseline(event):
    return {
        "event": (
            event.date_from,
            event.date_to,
            event.timezone,
            event.cfp.opening,
            event.cfp.deadline,
        ),
        "released_program": _released_program(event),
        "tasks": tuple(
            OnboardingTask.objects.filter(event=event)
            .values_list(
                "definition__slug",
                "status",
                "due_date",
                "waiver_reason",
                "speaker__email",
                "submission__title",
            )
            .order_by("definition__position", "pk")
        ),
        "sync": {
            "previews": tuple(
                SyncPreview.objects.filter(event=event)
                .values_list("fingerprint", "status", "payload")
                .order_by("fingerprint")
            ),
            "runs": tuple(
                SyncRun.objects.filter(event=event)
                .values_list("status", "preview__fingerprint")
                .order_by("preview__fingerprint")
            ),
            "items": tuple(
                SyncItem.objects.filter(event=event)
                .values_list(
                    "local_type",
                    "local_id",
                    "action",
                    "status",
                    "attempts",
                    "external_id",
                    "request_fingerprint",
                    "error",
                    "payload",
                )
                .order_by("local_type", "local_id")
            ),
            "attempts": tuple(
                SyncAttempt.objects.filter(event=event)
                .values_list("item__local_type", "item__local_id", "number", "status", "error")
                .order_by("item__local_type", "item__local_id", "number")
            ),
            "identities": tuple(
                ExternalIdentity.objects.filter(event=event)
                .values_list(
                    "local_type",
                    "local_id",
                    "external_id",
                    "request_fingerprint",
                )
                .order_by("local_type", "local_id")
            ),
        },
    }


@pytest.mark.django_db(transaction=True)
def test_seed_is_deterministic_and_keeps_conflicts_out_of_released_program(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "seed-admin@example.org")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "test-password")
    monkeypatch.setenv("PRETALX_INIT_ORGANISER_NAME", "Seed Test Organiser")
    monkeypatch.setenv("PRETALX_INIT_ORGANISER_SLUG", "seed-test-organiser")
    call_command("init", interactive=False, verbosity=0)

    call_command("speakerops_seed", verbosity=0)
    event = Event.objects.get(slug="speakerops-demo")
    with scope(event=event):
        first = _baseline(event)

        assert first["event"] == (
            DEMO_START,
            DEMO_END,
            "America/New_York",
            CFP_OPENING,
            CFP_DEADLINE,
        )
        assert CFP_DEADLINE < DEMO_WALKTHROUGH_AT
        assert DEMO_WALKTHROUGH_AT.date() < DEMO_START
        assert event.get_feature_flag("use_tracks") is True
        assert "Browse the released schedule" in str(event.landing_page_text)
        assert "/speakerops-demo/speaker-operations/embed/" in str(event.landing_page_text)
        released = first["released_program"]
        assert len(released) == len(CURATED_PROGRAM) == 12
        assert {row[3] for row in released} == {"Main Stage", "Studio"}
        assert {row[0] for row in released} == {program[1] for program in CURATED_PROGRAM}
        assert all(row[1].startswith(DEMO_START.isoformat()) for row in released[:4])
        assert all(row[1].startswith(DEMO_END.isoformat()) for row in released[-4:])

        released_by_title = {row[0]: row for row in released}
        for speaker_name, title, _abstract in CURATED_PROGRAM:
            speakers = released_by_title[title][4]
            assert len(speakers) == 1
            assert speakers[0][1] == speaker_name
        demo_speaker_sessions = [
            row[0]
            for row in released
            if "speaker@example.org" in {email for email, _name in row[4]}
        ]
        assert demo_speaker_sessions == [CURATED_PROGRAM[0][1]]

        wip_warnings = classify_warnings(event.wip_schedule)
        assert {warning["category"] for warning in wip_warnings} == {"room", "speaker"}
        wip_slots = list(
            event.wip_schedule.talks.filter(submission__isnull=False).values_list(
                "submission__title", flat=True
            )
        )
        assert len(wip_slots) == len(CURATED_PROGRAM) + len(CONFLICT_FIXTURE_TITLES)
        assert set(wip_slots) == {
            *(program[1] for program in CURATED_PROGRAM),
            *CONFLICT_FIXTURE_TITLES,
        }
        warning_titles = {
            warning["category"]: {
                warning["talk"].submission.title,
                warning["competitor"].submission.title,
            }
            for warning in wip_warnings
        }
        assert warning_titles["room"] == set(CONFLICT_FIXTURE_TITLES)
        assert warning_titles["speaker"] == {
            CURATED_PROGRAM[0][1],
            CONFLICT_FIXTURE_TITLES[1],
        }

    call_command("speakerops_seed", verbosity=0)
    event.refresh_from_db()
    with scope(event=event):
        assert _baseline(event) == first
