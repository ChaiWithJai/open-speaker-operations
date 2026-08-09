import pytest
from django_scopes import scope
from pretalx.person.models import SpeakerProfile


@pytest.mark.django_db(transaction=True)
def test_five_public_widget_modes_are_released_only_and_cross_origin(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        schedule = event.current_schedule
        assert schedule
        slots = list(
            schedule.talks.filter(is_visible=True, submission__isnull=False).select_related(
                "submission"
            )
        )
        assert slots
        released_titles = {slot.submission.title for slot in slots}
        unreleased = (
            event.wip_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .exclude(submission_id__in={slot.submission_id for slot in slots})
            .first()
        )

    markers = {
        "sessions": (b"Show more", b"Add to my schedule", b"widget-search"),
        "speakers": (b"Title not provided", b"Company not provided", b"widget-search"),
        "agenda": (b"<table", b"Published program views", b"Time"),
        "itinerary": (b"Export selected sessions", b"data-calendar-export", b"data-star"),
        "gallery": (b"speaker-grid", b"widget-search", b"Published program views"),
    }
    for widget, expected in markers.items():
        response = client.get(f"/{event.slug}/speaker-operations/widgets/{widget}/")
        assert response.status_code == 200
        assert "X-Frame-Options" not in response
        assert "frame-ancestors *" in response["Content-Security-Policy"]
        for marker in expected:
            assert marker in response.content
        assert any(title.encode() in response.content for title in released_titles)
        if unreleased:
            assert unreleased.submission.title.encode() not in response.content


@pytest.mark.django_db(transaction=True)
def test_rich_session_search_and_speaker_detail_use_public_released_data(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slot = (
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission", "submission__submission_type")
            .prefetch_related("submission__speakers")
            .first()
        )
        assert slot
        speaker = slot.submission.speakers.first()
        assert speaker
        SpeakerProfile.objects.update_or_create(
            event=event,
            user=speaker,
            defaults={"biography": "A public biography for widget verification."},
        )

    sessions = client.get(f"/{event.slug}/speaker-operations/widgets/sessions/")
    assert slot.submission.title.encode() in sessions.content
    assert speaker.get_display_name().encode() in sessions.content
    assert str(slot.submission.submission_type.name).encode() in sessions.content
    assert b"result" in sessions.content

    speakers = client.get(f"/{event.slug}/speaker-operations/widgets/speakers/")
    detail_url = f"/{event.slug}/speaker-operations/widgets/speakers/{speaker.code}/"
    assert detail_url.encode() in speakers.content
    detail = client.get(detail_url)
    assert detail.status_code == 200
    assert b"A public biography for widget verification." in detail.content
    assert slot.submission.title.encode() in detail.content


@pytest.mark.django_db(transaction=True)
def test_selected_calendar_exports_only_released_requested_sessions(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slots = list(
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .order_by("pk")[:2]
        )
        assert slots
    selected = slots[0]
    response = client.get(
        f"/{event.slug}/speaker-operations/my-schedule.ics",
        {"sessions": selected.submission.code},
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/calendar")
    assert selected.submission.title.encode() in response.content
    if len(slots) > 1:
        assert slots[1].submission.title.encode() not in response.content
    assert client.get(f"/{event.slug}/speaker-operations/my-schedule.ics").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_embed_builder_is_organizer_only_and_exposes_required_controls(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    url = f"/orga/{event.slug}/speaker-operations/embed-builder/"
    assert client.get(url).status_code == 302
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404
    client.force_login(users["chair"])
    response = client.get(url)
    assert response.status_code == 200
    for marker in (
        b"Widget type",
        b"Branding",
        b"Fields",
        b"Track filter",
        b"Format",
        b"Generated snippet",
        b"embed-preview",
    ):
        assert marker in response.content
