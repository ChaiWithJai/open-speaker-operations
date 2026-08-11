from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import RequestFactory
from django.utils import timezone
from django.utils.html import strip_tags
from django_scopes import scope
from pretalx.person.models import SpeakerProfile

from pretalx_speakerops.receivers import speakerops_cfp_assets

ROOT = Path(__file__).resolve().parents[1]


def _slot_ids(response):
    return {slot.pk for slot in response.context["slots"]}


class _AttributeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def _elements(response, *, tag=None, **attributes):
    parser = _AttributeParser()
    parser.feed(response.content.decode())
    return [
        attrs
        for element_tag, attrs in parser.elements
        if (tag is None or element_tag == tag)
        and all(attrs.get(name) == value for name, value in attributes.items())
    ]


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
        "speakers": (b"Speakers", b"speaker-grid", b"widget-search"),
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
def test_agenda_exposes_keyboard_operable_day_tabs(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")

    response = client.get(f"/{event.slug}/speaker-operations/widgets/agenda/")

    assert response.status_code == 200
    assert _elements(response, tag="div", role="tablist")
    assert not _elements(response, tag="form", role="tablist")
    assert b"data-agenda-day=" in response.content
    assert b"data-agenda-panel=" in response.content
    assert _elements(response, role="tabpanel")
    assert _elements(response, role="tab", **{"aria-selected": "true"})


@pytest.mark.django_db(transaction=True)
def test_itinerary_uses_valid_tablist_host(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")

    response = client.get(f"/{event.slug}/speaker-operations/widgets/itinerary/")

    assert response.status_code == 200
    assert _elements(response, tag="div", role="tablist")
    assert not _elements(response, tag="form", role="tablist")


def test_public_widget_mobile_navigation_wraps_without_clipping():
    stylesheet = (
        ROOT / "pretalx_speakerops" / "static" / "pretalx_speakerops" / "public_widgets.css"
    ).read_text()

    mobile_rules = stylesheet.split("@media(max-width:42rem)", maxsplit=1)[1]
    assert ".widget-nav{overflow-x:visible;flex-wrap:wrap}" in mobile_rules
    assert ".widget-nav a{white-space:normal}" in mobile_rules
    assert "flex-wrap:nowrap" not in mobile_rules


def test_native_schedule_live_badge_has_contrast_override():
    assets = speakerops_cfp_assets(
        sender=object(), request=RequestFactory().get("/event/schedule/")
    )
    script = (
        ROOT / "pretalx_speakerops" / "static" / "pretalx_speakerops" / "cfp-a11y.js"
    ).read_text()

    assert "pretalx_speakerops/cfp-a11y" in str(assets)
    assert (
        ".time-box .is-live { background-color: #b71c1c !important; color: #ffffff !important; }"
    ) in script


@pytest.mark.django_db(transaction=True)
def test_sessions_widget_server_filters_title_speaker_track_format_and_room(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slots = list(
            event.current_schedule.talks.filter(
                is_visible=True,
                submission__isnull=False,
                submission__track__isnull=False,
                submission__submission_type__isnull=False,
                room__isnull=False,
            )
            .select_related(
                "submission", "submission__track", "submission__submission_type", "room"
            )
            .prefetch_related("submission__speakers")
            .order_by("pk")
        )
        assert slots
        target = slots[0]
        speaker = target.submission.speakers.first()
        assert speaker
        all_slots = list(
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related(
                "submission", "submission__track", "submission__submission_type", "room"
            )
            .prefetch_related("submission__speakers")
        )

    url = f"/{event.slug}/speaker-operations/widgets/sessions/"

    def expected(*, query="", track="", session_format="", room=""):
        needle = query.casefold()
        return {
            slot.pk
            for slot in all_slots
            if (
                not needle
                or needle
                in (
                    slot.submission.title
                    + " "
                    + " ".join(item.get_display_name() for item in slot.submission.speakers.all())
                ).casefold()
            )
            and (not track or str(slot.submission.track_id or "") == track)
            and (
                not session_format
                or str(slot.submission.submission_type_id or "") == session_format
            )
            and (not room or str(slot.room_id or "") == room)
        }

    title_query = target.submission.title
    title_response = client.get(url, {"q": title_query})
    assert _slot_ids(title_response) == expected(query=title_query)
    assert title_response.context["selected_query"] == title_query

    speaker_query = speaker.get_display_name()
    speaker_response = client.get(url, {"q": speaker_query})
    assert _slot_ids(speaker_response) == expected(query=speaker_query)

    filters = {
        "track": str(target.submission.track_id),
        "format": str(target.submission.submission_type_id),
        "room": str(target.room_id),
    }
    filtered = client.get(url, filters)
    assert _slot_ids(filtered) == expected(
        track=filters["track"],
        session_format=filters["format"],
        room=filters["room"],
    )
    assert filtered.context["selected_track"] == filters["track"]
    assert filtered.context["selected_format"] == filters["format"]
    assert filtered.context["selected_room"] == filters["room"]
    assert _elements(filtered, tag="select", id="widget-format", name="format")


@pytest.mark.django_db(transaction=True)
def test_speaker_surname_search_returns_every_released_session_for_that_speaker(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        speaker = users["speaker"]
        speaker.name = "Priya Raman"
        speaker.save(update_fields=["name"])
        slots = list(
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .order_by("pk")[:3]
        )
        assert len(slots) == 3
        for slot in slots:
            slot.submission.speakers.add(speaker)
        expected_ids = set(
            event.current_schedule.talks.filter(
                is_visible=True, submission__speakers=speaker
            ).values_list("pk", flat=True)
        )

    response = client.get(f"/{event.slug}/speaker-operations/widgets/sessions/", {"q": "Raman"})

    assert response.status_code == 200
    assert _slot_ids(response) == expected_ids
    for slot in slots:
        assert slot.submission.title.encode() in response.content


@pytest.mark.django_db(transaction=True)
def test_agenda_day_query_selects_exact_initial_tab_and_panel(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slots = list(
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .order_by("pk")[:2]
        )
        assert len(slots) == 2
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        slots[0].start = start
        slots[0].end = start + timedelta(minutes=30)
        slots[1].start = start + timedelta(days=1)
        slots[1].end = slots[1].start + timedelta(minutes=30)
        for slot in slots:
            slot.save(update_fields=["start", "end", "updated"])
        selected_day = timezone.localtime(slots[1].start, event.tz).date().isoformat()
        other_day = timezone.localtime(slots[0].start, event.tz).date().isoformat()

    response = client.get(
        f"/{event.slug}/speaker-operations/widgets/agenda/", {"day": selected_day}
    )

    assert response.status_code == 200
    assert response.context["selected_day"] == selected_day
    assert _elements(
        response,
        tag="button",
        id=f"agenda-tab-{selected_day}",
        **{
            "aria-controls": f"agenda-panel-{selected_day}",
            "aria-selected": "true",
            "tabindex": "0",
        },
    )
    assert _elements(
        response,
        tag="button",
        id=f"agenda-tab-{other_day}",
        **{
            "aria-controls": f"agenda-panel-{other_day}",
            "aria-selected": "false",
            "tabindex": "-1",
        },
    )
    # Raw HTML retains every day for form navigation and no-JS use. The deferred
    # script applies the requested day as progressive enhancement.
    selected_panel = _elements(response, tag="section", id=f"agenda-panel-{selected_day}")[0]
    other_panel = _elements(response, tag="section", id=f"agenda-panel-{other_day}")[0]
    assert "hidden" not in selected_panel
    assert "hidden" not in other_panel
    assert _elements(response, tag="main", **{"data-selected-day": selected_day})
    assert b"Showing " in response.content


@pytest.mark.django_db(transaction=True)
def test_agenda_session_detail_exposes_full_metadata_and_restores_day(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slot = (
            event.current_schedule.talks.filter(
                is_visible=True,
                submission__isnull=False,
                submission__track__isnull=False,
                submission__submission_type__isnull=False,
                room__isnull=False,
            )
            .select_related(
                "submission", "submission__track", "submission__submission_type", "room"
            )
            .first()
        )
        assert slot
        selected_day = timezone.localtime(slot.start, event.tz).date().isoformat()

    agenda = client.get(f"/{event.slug}/speaker-operations/widgets/agenda/", {"day": selected_day})
    agenda_links = _elements(agenda, tag="a")
    for day in agenda.context["days"]:
        for day_slot in day["slots"]:
            day_detail_path = (
                f"/{event.slug}/speaker-operations/widgets/sessions/{day_slot.submission.code}/"
            )
            day_link = next(
                attrs for attrs in agenda_links if attrs.get("href", "").startswith(day_detail_path)
            )
            day_target = urlsplit(day_link["href"])
            assert parse_qs(day_target.query) == {
                "from": ["agenda"],
                "day": [day["key"]],
            }
    detail_path = f"/{event.slug}/speaker-operations/widgets/sessions/{slot.submission.code}/"
    detail_link = next(
        attrs
        for attrs in _elements(agenda, tag="a")
        if attrs.get("href", "").startswith(detail_path)
    )
    detail_target = urlsplit(detail_link["href"])
    assert parse_qs(detail_target.query) == {"from": ["agenda"], "day": [selected_day]}

    detail = client.get(detail_path, {"from": "agenda", "day": selected_day})
    assert detail.status_code == 200
    for value in (
        slot.submission.title,
        slot.room.name,
        slot.submission.submission_type.name,
        slot.submission.track.name,
    ):
        assert str(value).encode() in detail.content
    rendered_text = " ".join(strip_tags(detail.content.decode()).split())
    description_text = " ".join(
        strip_tags(str(slot.submission.description or slot.submission.abstract)).split()
    )
    assert description_text in rendered_text
    back = _elements(detail, tag="a", **{"data-return-to": "agenda"})[0]
    return_target = urlsplit(back["href"])
    assert return_target.path == f"/{event.slug}/speaker-operations/widgets/agenda/"
    assert parse_qs(return_target.query) == {"day": [selected_day]}
    assert return_target.fragment == f"session-{slot.submission.code}"


@pytest.mark.django_db(transaction=True)
def test_itinerary_is_grouped_and_server_navigable_by_day(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slots = list(
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .order_by("pk")[:2]
        )
        assert len(slots) == 2
        start = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        slots[0].start = start
        slots[0].end = start + timedelta(minutes=30)
        slots[1].start = start + timedelta(days=1)
        slots[1].end = slots[1].start + timedelta(minutes=30)
        for slot in slots:
            slot.save(update_fields=["start", "end", "updated"])
        selected_day = timezone.localtime(slots[1].start, event.tz).date().isoformat()

    response = client.get(
        f"/{event.slug}/speaker-operations/widgets/itinerary/", {"day": selected_day}
    )

    assert response.status_code == 200
    assert response.context["selected_day"] == selected_day
    assert len(response.context["days"]) >= 2
    assert _elements(response, tag="div", role="tablist", **{"aria-label": "Itinerary days"})
    assert b"data-itinerary-day=" in response.content
    assert b"data-itinerary-panel=" in response.content
    assert _elements(
        response,
        tag="button",
        id=f"itinerary-tab-{selected_day}",
        **{
            "aria-controls": f"itinerary-panel-{selected_day}",
            "aria-selected": "true",
            "tabindex": "0",
        },
    )
    for day in response.context["days"]:
        panel = _elements(response, tag="section", id=f"itinerary-panel-{day['key']}")[0]
        assert "hidden" not in panel
        for slot in day["slots"]:
            assert slot.submission.title.encode() in response.content


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
def test_speaker_detail_expands_biography_and_restores_originating_grid_state(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slot = (
            event.current_schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .prefetch_related("submission__speakers")
            .first()
        )
        assert slot
        speaker = slot.submission.speakers.first()
        assert speaker
        SpeakerProfile.objects.update_or_create(
            event=event,
            user=speaker,
            defaults={
                "biography": " ".join(
                    f"Accessible biography sentence {number}." for number in range(1, 9)
                )
            },
        )

    search = f"{speaker.get_display_name()} & reliability"
    detail_path = f"/{event.slug}/speaker-operations/widgets/speakers/{speaker.code}/"
    for origin in ("gallery", "speakers"):
        listing = client.get(f"/{event.slug}/speaker-operations/widgets/{origin}/", {"q": search})
        assert listing.status_code == 200
        assert _elements(listing, tag="article", id=f"speaker-{speaker.code}")
        detail_links = [
            attrs
            for attrs in _elements(listing, tag="a")
            if "data-speaker-detail" in attrs and attrs.get("href", "").startswith(detail_path)
        ]
        assert len(detail_links) == 1
        detail_target = urlsplit(detail_links[0]["href"])
        assert detail_target.path == detail_path
        assert parse_qs(detail_target.query) == {"from": [origin], "q": [search]}

        detail = client.get(detail_path, {"from": origin, "q": search})
        assert detail.status_code == 200
        assert detail.context["origin"] == origin
        expected_return_path = f"/{event.slug}/speaker-operations/widgets/{origin}/"
        back = _elements(detail, tag="a", **{"data-return-to": origin})
        assert len(back) == 1
        return_target = urlsplit(back[0]["href"])
        assert return_target.path == expected_return_path
        assert parse_qs(return_target.query) == {"q": [search]}
        assert return_target.fragment == f"speaker-{speaker.code}"

        biography = _elements(
            detail,
            tag="div",
            id="speaker-biography",
        )[0]
        assert "data-biography" in biography
        toggle = _elements(
            detail,
            tag="button",
            type="button",
            **{
                "data-biography-toggle": None,
                "aria-controls": "speaker-biography",
                "aria-expanded": "false",
            },
        )[0]
        assert "data-biography-toggle" in toggle
        assert "hidden" in toggle
        assert b"Show more biography" in detail.content
        assert _elements(
            detail,
            tag="script",
            src="/static/pretalx_speakerops/public_speaker_detail.js",
        )

    untrusted_origin = client.get(
        detail_path,
        {"from": "https://attacker.example/redirect", "q": search},
    )
    assert untrusted_origin.context["origin"] == "speakers"
    safe_back = _elements(untrusted_origin, tag="a", **{"data-return-to": "speakers"})[0]
    assert urlsplit(safe_back["href"]).path == (
        f"/{event.slug}/speaker-operations/widgets/speakers/"
    )


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
        b"Search filter",
        b"Session format filter",
        b"Room filter",
        b"Format",
        b"Generated snippet",
        b"embed-preview",
        b"Responsive styled HTML iframe",
        b"Basic HTML share link",
        b"JSON data feed",
        b"XML data feed",
        b"iCal calendar feed",
        b"Five shareable public surfaces",
    ):
        assert marker in response.content
    for widget in (b"sessions", b"speakers", b"agenda", b"itinerary", b"gallery"):
        assert b"/widgets/" + widget + b"/" in response.content


@pytest.mark.django_db(transaction=True)
def test_public_day_views_default_to_all_days_and_keep_broken_image_fallback(event, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    agenda = client.get(f"/{event.slug}/speaker-operations/widgets/agenda/")
    gallery = client.get(f"/{event.slug}/speaker-operations/widgets/gallery/")

    assert agenda.context["selected_day"] == "all"
    assert b">All days</button>" in agenda.content
    assert b"Showing all event days" in agenda.content
    assert all("hidden" not in panel for panel in _elements(agenda, tag="section", role="tabpanel"))
    if b"data-avatar" in gallery.content:
        assert b"data-avatar-fallback" in gallery.content
        widget_script = Path(
            "pretalx_speakerops/static/pretalx_speakerops/public_widgets.js"
        ).read_text()
        assert "avatar.complete && avatar.naturalWidth === 0" in widget_script
