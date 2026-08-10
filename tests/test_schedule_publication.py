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
def test_organiser_creates_rooms_and_tracks_from_agenda_view(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/agenda/"

    response = client.post(
        url, {"action": "create_room", "room_name": "Workshop Loft", "room_capacity": "45"}
    )
    assert response.status_code == 302
    response = client.post(url, {"action": "create_track", "track_name": "AI Engineering"})
    assert response.status_code == 302
    with scope(event=event):
        room = event.rooms.get(name="Workshop Loft")
        assert room.capacity == 45
        track = event.tracks.get(name="AI Engineering")
        assert track.color

    response = client.get(url)
    assert response.status_code == 200
    assert b"Workshop Loft" in response.content
    assert b"AI Engineering" in response.content

    # Duplicates and invalid input are rejected without creating records.
    client.post(url, {"action": "create_room", "room_name": "workshop loft"})
    client.post(url, {"action": "create_track", "track_name": "AI Engineering"})
    client.post(
        url, {"action": "create_track", "track_name": "Colourless", "track_color": "not-a-color"}
    )
    with scope(event=event):
        assert event.rooms.filter(name__iexact="workshop loft").count() == 1
        assert event.tracks.filter(name="AI Engineering").count() == 1
        assert not event.tracks.filter(name="Colourless").exists()


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
