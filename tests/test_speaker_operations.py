import io
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from django_scopes import scope
from pretalx.person.models import SpeakerProfile, User

from pretalx_speakerops.models import (
    OnboardingTask,
    ReminderReceipt,
    SpeakerOperationsProfile,
)
from pretalx_speakerops.tasks import send_due_speaker_reminders


@pytest.mark.django_db(transaction=True)
def test_speaker_operations_routes_are_manager_only(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    for user in (users["speaker"], users["reviewer"]):
        client.force_login(user)
        assert client.get(f"/orga/{event.slug}/speaker-operations/speakers/").status_code == 404
        assert (
            client.get(f"/orga/{event.slug}/speaker-operations/speakers/import/").status_code == 404
        )


@pytest.mark.django_db(transaction=True)
def test_csv_speaker_import_previews_maps_validates_and_persists(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/import/"
    csv_file = SimpleUploadedFile(
        "speakers.csv",
        (
            b"Full Name,Email Address,Status,Travel,Dietary,Accessibility\n"
            b"Ada Lovelace,ada@example.org,confirmed,Train,Vegetarian,Step-free stage\n"
            b"Grace Hopper,grace@example.org,ready,Air,None,None\n"
        ),
        content_type="text/csv",
    )
    preview = client.post(url, {"action": "preview", "csv_file": csv_file})
    assert preview.status_code == 200
    assert preview.context["row_count"] == 2
    assert preview.context["guesses"]["email"] == "Email Address"

    response = client.post(
        url,
        {
            "action": "import",
            "token": preview.context["token"],
            "map_name": "Full Name",
            "map_email": "Email Address",
            "map_workflow_status": "Status",
            "map_travel_preferences": "Travel",
            "map_dietary_requirements": "Dietary",
            "map_accessibility_requirements": "Accessibility",
        },
    )
    assert response.status_code == 302
    with scope(event=event):
        ada = User.objects.get(email="ada@example.org")
        assert SpeakerProfile.objects.filter(event=event, user=ada).exists()
        operations = SpeakerOperationsProfile.objects.get(event=event, speaker=ada)
        assert operations.workflow_status == SpeakerOperationsProfile.CONFIRMED
        assert operations.travel_preferences == "Train"
        assert operations.accessibility_requirements == "Step-free stage"


@pytest.mark.django_db(transaction=True)
def test_csv_speaker_import_rejects_all_rows_when_any_row_is_invalid(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/import/"
    preview = client.post(
        url,
        {
            "action": "preview",
            "csv_file": SimpleUploadedFile(
                "bad.csv",
                b"name,email\nValid Person,valid@example.org\nBroken,not-an-email\n",
                content_type="text/csv",
            ),
        },
    )
    response = client.post(
        url,
        {
            "action": "import",
            "token": preview.context["token"],
            "map_name": "name",
            "map_email": "email",
        },
    )
    assert response.status_code == 200
    assert not User.objects.filter(email="valid@example.org").exists()


@pytest.mark.django_db(transaction=True)
def test_workflow_logistics_filters_and_multi_speaker_action_roundtrip(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        second = User.objects.create_user(email="second-speaker@example.org", name="Second Speaker")
        SpeakerProfile.objects.create(event=event, user=second)
        outsider = User.objects.create_user(email="outsider@example.org", name="Outsider")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/"
    update = client.post(
        url,
        {
            "action": "update_speaker",
            "speaker_id": users["speaker"].pk,
            "workflow_status": "ready",
            "travel_preferences": "Rail after 10:00",
            "dietary_requirements": "Vegan",
            "accessibility_requirements": "Captioning",
            "logistics_notes": "Hotel held",
        },
    )
    assert update.status_code == 302
    filtered = client.get(url, {"status": "ready"})
    assert [row["speaker"].pk for row in filtered.context["rows"]] == [users["speaker"].pk]

    due = timezone.localdate() + timedelta(days=5)
    assigned = client.post(
        url,
        {
            "action": "create_task",
            "name": "Confirm travel itinerary",
            "instructions": "Check the itinerary and acknowledge it.",
            "completion_criteria": "The itinerary is confirmed.",
            "due_date": due.isoformat(),
            "speakers": [users["speaker"].pk, second.pk],
        },
    )
    assert assigned.status_code == 302
    with scope(event=event):
        tasks = OnboardingTask.objects.filter(
            event=event, definition__name="Confirm travel itinerary"
        )
        assert tasks.count() == 2
        assert set(tasks.values_list("speaker_id", flat=True)) == {
            users["speaker"].pk,
            second.pk,
        }
        assert tasks.filter(due_date=due, submission__isnull=True).count() == 2

    client.force_login(users["speaker"])
    checklist = client.get(f"/{event.slug}/speaker-operations/checklist/")
    assert b"Confirm travel itinerary" in checklist.content

    client.force_login(users["chair"])
    rejected = client.post(
        url,
        {
            "action": "create_task",
            "name": "Wrong event",
            "instructions": "Must not be assigned.",
            "completion_criteria": "Never.",
            "due_date": due.isoformat(),
            "speakers": [outsider.pk],
        },
    )
    assert rejected.status_code == 302
    with scope(event=event):
        assert not OnboardingTask.objects.filter(definition__name="Wrong event").exists()


@pytest.mark.django_db(transaction=True)
def test_scheduled_reminder_worker_handles_general_tasks_and_is_daily_idempotent(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.submission = None
        task.due_date = timezone.localdate() - timedelta(days=1)
        task.save(update_fields=["submission", "due_date", "updated"])

    output = io.StringIO()
    call_command("speakerops_send_reminders", event=event.slug, stdout=output)
    first = json.loads(output.getvalue())
    second = send_due_speaker_reminders(event.slug)
    assert first[event.slug] == 1
    assert second[event.slug] == 0
    with scope(event=event):
        receipt = ReminderReceipt.objects.get(task=task)
        assert receipt.reminder_key == f"onboarding-overdue:{timezone.localdate().isoformat()}"
