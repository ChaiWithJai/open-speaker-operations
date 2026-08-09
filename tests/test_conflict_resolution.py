from datetime import timedelta

import pytest
from django.contrib.messages import get_messages
from django.utils import timezone
from django_scopes import scope
from pretalx.schedule.models import Room, Schedule

from pretalx_speakerops.program.auto_schedule import build_schedule_proposal
from pretalx_speakerops.program.policy import classify_warnings


def _arrange_conflict(event, users, kind):
    talks = list(
        event.wip_schedule.talks.filter(submission__isnull=False)
        .select_related("submission", "room")
        .order_by("pk")
    )
    first, second = talks[:2]
    first_room = event.rooms.first()
    second_room = Room.objects.create(event=event, name="Studio B")
    start = timezone.now().replace(microsecond=0)

    for offset, talk in enumerate(talks[2:], start=1):
        talk.start = start + timedelta(days=offset)
        talk.end = talk.start + timedelta(minutes=30)
        talk.save(update_fields=["start", "end", "updated"])

    first.submission.speakers.clear()
    second.submission.speakers.clear()
    if kind == "room":
        first.submission.speakers.add(users["chair"])
        second.submission.speakers.add(users["reviewer"])
    else:
        first.submission.speakers.add(users["speaker"])
        second.submission.speakers.add(users["speaker"])

    first.room = first_room
    second.room = first_room if kind in {"room", "combined"} else second_room
    for talk in (first, second):
        talk.start = start
        talk.end = start + timedelta(minutes=30)
        talk.save(update_fields=["room", "start", "end", "updated"])
    return first, second, second_room


def _agenda_url(event):
    return f"/orga/{event.slug}/speaker-operations/agenda/"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("kind", "expected_categories"),
    [("room", ["room"]), ("speaker", ["speaker"]), ("combined", ["room", "speaker"])],
)
def test_conflict_rows_name_context_and_link_native_editors(
    event, users, client, kind, expected_categories
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        first, second, second_room = _arrange_conflict(event, users, kind)
        expected = classify_warnings(event.wip_schedule)

    client.force_login(users["chair"])
    response = client.get(_agenda_url(event))

    assert response.status_code == 200
    blocking = response.context["blocking"]
    assert [item["category"] for item in blocking] == expected_categories
    assert [item["conflict_key"] for item in blocking] == [
        item["conflict_key"] for item in expected
    ]
    body = response.content.decode()
    for item in blocking:
        assert first.submission.title in item["message"]
        assert second.submission.title in item["message"]
        assert str(first.room.name) in item["message"]
        assert str(item["competitor"].room.name) in item["message"]
        assert first.start.strftime("%Y-%m-%d %H:%M") in item["message"]
        assert str(item["resolve_url"]) == str(first.submission.orga_urls.quick_schedule)
        assert str(item["competitor_resolve_url"]) == str(
            second.submission.orga_urls.quick_schedule
        )
        assert str(item["resolve_url"]) in body
    if kind == "speaker":
        assert str(second_room.name) in body
        assert users["speaker"].get_display_name() in body
    assert "Recheck conflicts" in body
    native_editor = client.get(str(blocking[0]["resolve_url"]))
    assert native_editor.status_code == 200
    assert first.submission.title in native_editor.content.decode()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["room", "speaker"])
def test_return_to_gate_reports_cleared_conflict(event, users, client, kind):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        first, second, _ = _arrange_conflict(event, users, kind)

    client.force_login(users["chair"])
    assert client.get(_agenda_url(event)).context["blocking"]

    with scope(event=event):
        if kind == "room":
            second.start = first.end + timedelta(minutes=5)
            second.end = second.start + timedelta(minutes=30)
            second.save(update_fields=["start", "end", "updated"])
        else:
            second.submission.speakers.remove(users["speaker"])

    response = client.get(f"{_agenda_url(event)}?recheck=1")
    assert response.context["blocking"] == []
    assert response.context["gate_feedback"]["cleared"] is True
    assert "release gate clear" in response.content.decode()
    assert "1 conflict cleared" in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_combined_conflict_stays_blocked_until_every_resource_is_resolved(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        _, second, second_room = _arrange_conflict(event, users, "combined")

    client.force_login(users["chair"])
    initial = client.get(_agenda_url(event))
    assert [item["category"] for item in initial.context["blocking"]] == ["room", "speaker"]

    with scope(event=event):
        second.room = second_room
        second.save(update_fields=["room", "updated"])

    rechecked = client.get(f"{_agenda_url(event)}?recheck=1")
    assert [item["category"] for item in rechecked.context["blocking"]] == ["speaker"]
    feedback = rechecked.context["gate_feedback"]
    assert feedback["cleared"] is False
    assert feedback["title"] == "Conflict check complete · still blocked"
    assert "1 conflict cleared; 1 still blocks release" in feedback["message"]

    with scope(event=event):
        released_before = Schedule.objects.filter(event=event, version__isnull=False).count()
    blocked_release = client.post(
        _agenda_url(event), {"confirm_release": "yes", "name": "must-not-release"}
    )
    assert blocked_release.status_code == 302
    with scope(event=event):
        assert (
            Schedule.objects.filter(event=event, version__isnull=False).count() == released_before
        )
    assert any(
        "blocked by unresolved conflicts" in str(message)
        for message in get_messages(blocked_release.wsgi_request)
    )


@pytest.mark.django_db(transaction=True)
def test_assisted_agenda_previews_then_applies_conflict_free_plan(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        _arrange_conflict(event, users, "combined")
        proposal = build_schedule_proposal(event.wip_schedule)
        assert proposal
        assert any(item.changed for item in proposal)

    client.force_login(users["chair"])
    preview = client.post(_agenda_url(event), {"action": "preview_assisted_schedule"})
    assert preview.status_code == 200
    assert len(preview.context["proposed_placements"]) == len(proposal)
    assert "Generate conflict-free proposal" in preview.content.decode()
    assert "Apply proposed agenda" in preview.content.decode()

    unconfirmed = client.post(_agenda_url(event), {"action": "apply_assisted_schedule"})
    assert unconfirmed.status_code == 302
    with scope(event=event):
        assert classify_warnings(event.wip_schedule)

    applied = client.post(
        _agenda_url(event),
        {"action": "apply_assisted_schedule", "confirm_assisted_schedule": "yes"},
    )
    assert applied.status_code == 302
    with scope(event=event):
        assert classify_warnings(event.wip_schedule) == []
