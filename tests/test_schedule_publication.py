from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_scopes import scope

from pretalx_speakerops.models import ScheduleIcsIdentity
from pretalx_speakerops.program.calendar import released_ical
from pretalx_speakerops.program.policy import assert_release_allowed, classify_warnings
from pretalx_speakerops.program.reviews import configure_review_rounds, decision_history


@pytest.mark.django_db(transaction=True)
def test_review_configuration_has_two_rounds_and_auditable_history(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        phases, criteria = configure_review_rounds(event, second_round=True)
        assert [phase.name for phase in phases] == ["Round 1", "Round 2"]
        assert len(criteria) == 3
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        history = decision_history(submission)
        assert any(item["kind"] == "pretalx" for item in history)


@pytest.mark.django_db(transaction=True)
def test_organiser_creates_validated_rooms_and_tracks_from_agenda(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/agenda/"

    assert (
        client.post(
            url,
            {"action": "create_room", "room_name": "Workshop Loft", "room_capacity": "45"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            url,
            {
                "action": "create_track",
                "track_name": "Emerging Systems",
                "track_color": "#315efb",
            },
        ).status_code
        == 302
    )
    with scope(event=event):
        room = event.rooms.get(name="Workshop Loft")
        track = event.tracks.get(name="Emerging Systems")
        assert room.capacity == 45
        assert track.color == "#315efb"

        slot = event.wip_schedule.talks.filter(submission__isnull=False).first()
        assert slot
        slot.room = room
        slot.save(update_fields=["room", "updated"])
        slot.submission.track = track
        slot.submission.save(update_fields=["track"])
        placed_title = slot.submission.title

    response = client.get(url)
    assert response.status_code == 200
    placed = next(
        item for item in response.context["slots"] if item.submission.title == placed_title
    )
    assert placed.room_id == room.pk
    assert placed.submission.track_id == track.pk
    assert b"Workshop Loft" in response.content
    assert b"AI Engineering" in response.content

    client.post(url, {"action": "create_room", "room_name": "workshop loft"})
    client.post(
        url,
        {"action": "create_room", "room_name": "Overflow", "room_capacity": "99999999999"},
    )
    client.post(url, {"action": "create_track", "track_name": "AI Engineering"})
    client.post(
        url,
        {"action": "create_track", "track_name": "Colourless", "track_color": "not-a-color"},
    )
    with scope(event=event):
        assert event.rooms.filter(name__iexact="workshop loft").count() == 1
        assert not event.rooms.filter(name="Overflow").exists()
        assert event.tracks.filter(name__iexact="AI Engineering").count() == 1
        assert not event.tracks.filter(name="Colourless").exists()


@pytest.mark.django_db(transaction=True)
def test_room_and_track_creation_requires_event_settings_access(event, client):
    from pretalx.event.models import Team
    from pretalx.person.models import User

    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    coordinator = User.objects.create_user(
        email="coordinator@example.org", name="Coordinator", password="test-password"
    )
    team = Team.objects.create(
        organiser=event.organiser,
        name=f"Program {event.slug}",
        can_change_submissions=True,
    )
    team.limit_events.add(event)
    team.members.add(coordinator)

    client.force_login(coordinator)
    url = f"/orga/{event.slug}/speaker-operations/agenda/"
    response = client.get(url)
    assert response.status_code == 200
    assert b"requires event-settings access" in response.content
    assert b' name="room_name"' not in response.content
    assert b' name="track_name"' not in response.content

    assert client.post(url, {"action": "create_room", "room_name": "Side Room"}).status_code == 404
    assert (
        client.post(url, {"action": "create_track", "track_name": "Side Track"}).status_code == 404
    )
    with scope(event=event):
        assert not event.rooms.filter(name="Side Room").exists()
        assert not event.tracks.filter(name="Side Track").exists()


@pytest.mark.django_db(transaction=True)
def test_blocking_schedule_warning_prevents_release(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        talks = list(event.wip_schedule.talks.filter(submission__isnull=False)[:2])
        start = timezone.now()
        for talk in talks:
            talk.submission.speakers.add(users["speaker"])
            talk.room = event.rooms.first()
            talk.start = start
            talk.end = start + timedelta(minutes=30)
            talk.save(update_fields=["room", "start", "end", "updated"])
        classified = classify_warnings(event.wip_schedule)
        assert any(item["blocking"] for item in classified)
        with pytest.raises(ValidationError):
            assert_release_allowed(event.wip_schedule)


@pytest.mark.django_db(transaction=True)
def test_released_ics_has_stable_uid_and_incrementing_sequence(event):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        schedule = event.current_schedule
        slot = schedule.talks.filter(is_visible=True).select_related("submission", "room").first()
        if slot is None:
            pytest.skip("fixture has no released visible talk")
        first = released_ical(event)
        identity = ScheduleIcsIdentity.objects.get(event=event, submission=slot.submission)
        slot.submission.title = f"{slot.submission.title} updated"
        slot.submission.save(update_fields=["title", "updated"])
        second = released_ical(event)
        assert identity.uid in first and identity.uid in second
        assert "SEQUENCE:0" in first
        assert "SEQUENCE:1" in second


@pytest.mark.django_db(transaction=True)
def test_published_embed_is_cross_origin_readable_and_released_only(event, client):
    with scope(event=event):
        released = bool(event.current_schedule)
    response = client.get(f"/{event.slug}/speaker-operations/embed/")
    if released:
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
        assert "X-Frame-Options" not in response
        assert "frame-ancestors *" in response["Content-Security-Policy"]
        assert b"schedule" in response.content.lower()
        assert b"data-view-button=list" in response.content
        assert b"data-view-button=day" in response.content
        assert b"data-view-button=week" in response.content
        assert b"id=track-filter" in response.content
        assert b"id=room-filter" in response.content
        assert b"released_schedule.js" in response.content
        assert f"/{event.slug}/talk/".encode() in response.content
    else:
        assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_successful_release_hands_exact_schedule_to_public_agenda(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        slots = list(
            event.wip_schedule.talks.filter(submission__isnull=False).select_related("submission")
        )
        assert slots
        start = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        for index, slot in enumerate(slots):
            slot.room = event.rooms.first()
            slot.start = start + timedelta(hours=index)
            slot.end = slot.start + timedelta(minutes=30)
            slot.save(update_fields=["room", "start", "end", "updated"])
        expected_title = slots[0].submission.title
        assert classify_warnings(event.wip_schedule) == []

    client.force_login(users["chair"])
    response = client.post(
        f"/orga/{event.slug}/speaker-operations/agenda/",
        {"confirm_release": "yes", "name": "SBEK public handoff"},
    )

    assert response.status_code == 302
    public = client.get(f"/{event.slug}/speaker-operations/widgets/agenda/")
    assert public.status_code == 200
    assert expected_title.encode() in public.content
    with scope(event=event):
        assert str(event.current_schedule.version) == "SBEK public handoff"
