import base64
import io
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django_scopes import scope
from pretalx.celery_app import app
from pretalx.mail.models import QueuedMail
from pretalx.person.models import SpeakerProfile, User

from pretalx_speakerops.models import (
    OnboardingTask,
    ReminderReceipt,
    SpeakerCommunicationLog,
    SpeakerOperationsProfile,
)
from pretalx_speakerops.onboarding.reminders import ReminderOutcomeAmbiguous
from pretalx_speakerops.tasks import (
    REMINDER_BEAT_HEADER,
    REMINDER_SCHEDULE_NAME,
    send_due_speaker_reminders,
    send_due_speaker_reminders_task,
)


def test_daily_reminder_schedule_is_registered_with_celery():
    schedule = app.conf.beat_schedule[REMINDER_SCHEDULE_NAME]
    assert schedule["task"] == "speakerops.send_due_speaker_reminders"
    assert str(schedule["schedule"]) == "<crontab: 0 9 * * * (m/h/dM/MY/d)>"
    assert schedule["options"]["headers"] == {
        "speakerops_dispatch_origin": REMINDER_BEAT_HEADER,
        "speakerops_schedule_name": REMINDER_SCHEDULE_NAME,
    }


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
def test_spk02_single_speaker_profile_crud_is_event_scoped(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        outsider = User.objects.create_user(email="not-in-roster@example.org", name="Outsider")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/"

    created = client.post(
        url,
        {
            "action": "create_speaker",
            "name": "Individual Speaker",
            "email": "individual@example.org",
            "biography": "Original individual biography.",
        },
    )
    assert created.status_code == 302
    with scope(event=event):
        speaker = User.objects.get(email="individual@example.org")
        assert speaker.pw_reset_token, "A newly invited speaker needs a working account setup link"
        assert SpeakerProfile.objects.get(event=event, user=speaker).biography == (
            "Original individual biography."
        )
        assert SpeakerOperationsProfile.objects.filter(event=event, speaker=speaker).exists()

    updated = client.post(
        url,
        {
            "action": "update_speaker",
            "speaker_id": speaker.pk,
            "name": "Individual Speaker Updated",
            "email": "individual-updated@example.org",
            "biography": "Updated individual biography.",
            "social_url": "https://example.org/individual",
            "workflow_status": "confirmed",
            "travel_preferences": "Train",
            "dietary_requirements": "Vegetarian",
            "accessibility_requirements": "Step-free route",
            "logistics_notes": "Hotel confirmed",
        },
    )
    assert updated.status_code == 302
    with scope(event=event):
        speaker.refresh_from_db()
        profile = SpeakerProfile.objects.get(event=event, user=speaker)
        operations = SpeakerOperationsProfile.objects.get(event=event, speaker=speaker)
        assert speaker.name == "Individual Speaker Updated"
        assert speaker.email == "individual-updated@example.org"
        assert str(profile.biography) == "Updated individual biography."
        assert operations.social_url == "https://example.org/individual"
        assert operations.workflow_status == SpeakerOperationsProfile.CONFIRMED

    rejected_cross_event = client.post(url, {"action": "remove_speaker", "speaker_id": outsider.pk})
    assert rejected_cross_event.status_code == 302
    with scope(event=event):
        submission = event.submissions.first()
        submission.speakers.add(speaker)
    protected = client.post(url, {"action": "remove_speaker", "speaker_id": speaker.pk})
    assert protected.status_code == 302
    with scope(event=event):
        assert SpeakerProfile.objects.filter(event=event, user=speaker).exists()
        submission.speakers.remove(speaker)
    removed = client.post(url, {"action": "remove_speaker", "speaker_id": speaker.pk})
    assert removed.status_code == 302
    with scope(event=event):
        assert User.objects.filter(pk=speaker.pk).exists(), "Event removal must retain the account"
        assert not SpeakerProfile.objects.filter(event=event, user=speaker).exists()
        assert not SpeakerOperationsProfile.objects.filter(event=event, speaker=speaker).exists()


@pytest.mark.django_db(transaction=True)
def test_spk06_spk11_invitation_is_sent_logged_and_assignments_show_in_both_views(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.title = "Literal Session Assignment"
        submission.save(update_fields=["title"])
        submission.speakers.add(users["speaker"])
        users["speaker"].pw_reset_token = "literal-account-setup-token"
        users["speaker"].pw_reset_time = timezone.now()
        users["speaker"].save(update_fields=["pw_reset_token", "pw_reset_time"])
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/"
    with patch("pretalx.common.mail.mail_send_task.apply_async") as dispatch:
        response = client.post(
            url,
            {
                "action": "send_invitation",
                "speaker_id": users["speaker"].pk,
                "subject": "Welcome {{ first_name }} to {{ event_name }}",
                "body": (
                    "Sessions: {{ session_titles }}\n"
                    "Account: {{ account_setup_url }}\n"
                    "Onboarding: {{ speaker_portal_url }}"
                ),
            },
        )
    assert response.status_code == 302
    dispatch.assert_called_once()
    with scope(event=event):
        log = SpeakerCommunicationLog.objects.get(
            event=event,
            speaker=users["speaker"],
            kind=SpeakerCommunicationLog.INVITATION,
        )
        assert log.outcome == SpeakerCommunicationLog.SENT
        assert "Literal Session Assignment" in log.rendered_body
        assert "literal-account-setup-token" in log.rendered_body
        assert f"/{event.slug}/speaker-operations/profile/" in log.rendered_body
        queued = QueuedMail.objects.get(pk=log.queued_mail_id)
        assert queued.sent is not None
        assert list(queued.to_users.all()) == [users["speaker"]]
        assert list(queued.submissions.all()) == [submission]

    organizer = client.get(url)
    assert b"Literal Session Assignment" in organizer.content
    client.force_login(users["speaker"])
    portal = client.get(f"/{event.slug}/speaker-operations/profile/")
    assert portal.status_code == 200
    assert b"Your session assignments" in portal.content
    assert b"Literal Session Assignment" in portal.content


@pytest.mark.django_db(transaction=True)
def test_spk13_spk14_selected_bulk_email_previews_personalizes_and_logs_each_outcome(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        second = User.objects.create_user(email="bulk-second@example.org", name="Grace Hopper")
        SpeakerProfile.objects.create(event=event, user=second)
        outsider = User.objects.create_user(email="bulk-outsider@example.org", name="Outsider")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/speakers/"
    payload = {
        "speakers": [users["speaker"].pk, second.pk],
        "subject": "A note for {{ full_name }}",
        "body": (
            "Hi {{ first_name }} ({{ email }}), {{ event_name }} sessions: "
            "{{ session_titles }}. Portal: {{ speaker_portal_url }}"
        ),
    }
    preview = client.post(url, {"action": "preview_email", **payload})
    assert preview.status_code == 200
    assert b"Personalized preview" in preview.content
    assert users["speaker"].get_display_name().encode() in preview.content
    assert b"Hi Grace (bulk-second@example.org)" in preview.content
    assert all(
        "{{" not in item["subject"] + item["body"] for item in preview.context["email_preview"]
    )
    assert outsider.email.encode() not in preview.content

    with patch("pretalx.common.mail.mail_send_task.apply_async") as dispatch:
        sent = client.post(url, {"action": "send_bulk_email", **payload})
    assert sent.status_code == 302
    assert dispatch.call_count == 2
    with scope(event=event):
        logs = SpeakerCommunicationLog.objects.filter(
            event=event, kind=SpeakerCommunicationLog.BULK_EMAIL
        )
        assert logs.count() == 2
        assert logs.filter(outcome=SpeakerCommunicationLog.SENT).count() == 2
        assert set(logs.values_list("speaker_id", flat=True)) == {
            users["speaker"].pk,
            second.pk,
        }
        assert not logs.filter(speaker=outsider).exists()

    with patch(
        "pretalx.common.mail.mail_send_task.apply_async", side_effect=RuntimeError("mail down")
    ):
        failed = client.post(
            url,
            {
                "action": "send_invitation",
                "speaker_id": second.pk,
                "subject": "Retry for {{ full_name }}",
                "body": "Open {{ speaker_portal_url }}",
            },
        )
    assert failed.status_code == 302
    with scope(event=event):
        failure = SpeakerCommunicationLog.objects.filter(
            event=event,
            speaker=second,
            kind=SpeakerCommunicationLog.INVITATION,
        ).latest("pk")
        assert failure.outcome == SpeakerCommunicationLog.FAILED
        assert "RuntimeError: mail down" in failure.outcome_detail


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
def test_speaker_portal_profile_roundtrips_to_organizer(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        second = User.objects.create_user(
            email="profile-scope@example.org",
            name="Other Event Speaker",
            password="test-password",
        )
        SpeakerProfile.objects.create(
            event=event,
            user=second,
            biography="Other speaker biography must remain unchanged.",
        )
        submission.speakers.add(second)

    profile_url = f"/{event.slug}/speaker-operations/profile/"
    client.force_login(users["reviewer"])
    assert client.get(profile_url).status_code == 404

    client.force_login(users["speaker"])
    rejected = client.post(
        profile_url,
        {
            "biography": "The invalid upload must not update this biography.",
            "social_url": "http://example.org/not-secure",
            "speaker_id": second.pk,
            "headshot": SimpleUploadedFile(
                "headshot.png",
                b"not an image",
                content_type="image/png",
            ),
        },
    )
    assert rejected.status_code == 400
    assert b"Upload a valid image" in rejected.content
    assert b"Use an HTTPS" in rejected.content

    headshot = SimpleUploadedFile(
        "speaker-headshot.png",
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ),
        content_type="image/png",
    )
    biography = "SBEK-PORTAL-BIO-01 — I build reliable conference systems."
    social_url = "https://example.org/speaker-profile"
    saved = client.post(
        profile_url,
        {
            "biography": biography,
            "social_url": social_url,
            "speaker_id": second.pk,
            "headshot": headshot,
        },
    )
    assert saved.status_code == 302
    assert saved.url == profile_url

    with scope(event=event):
        own_profile = SpeakerProfile.objects.get(event=event, user=users["speaker"])
        other_profile = SpeakerProfile.objects.get(event=event, user=second)
        operations = SpeakerOperationsProfile.objects.get(
            event=event,
            speaker=users["speaker"],
        )
        assert str(own_profile.biography) == biography
        assert operations.social_url == social_url
        assert operations.headshot_original_filename == "speaker-headshot.png"
        assert operations.headshot_uploaded_at is not None
        assert str(other_profile.biography) == "Other speaker biography must remain unchanged."
        assert not SpeakerOperationsProfile.objects.filter(event=event, speaker=second).exists()
        users["speaker"].refresh_from_db()
        assert users["speaker"].avatar.name.endswith(".png")

    reloaded = client.get(profile_url)
    assert reloaded.status_code == 200
    assert biography.encode() in reloaded.content
    assert social_url.encode() in reloaded.content
    assert b"Current headshot" in reloaded.content
    self_headshot_url = reverse(
        "plugins:speakerops:speakerops_speaker_headshot", kwargs={"event": event.slug}
    )
    assert self_headshot_url.encode() in reloaded.content
    rendered_self_headshot = client.get(self_headshot_url)
    assert rendered_self_headshot.status_code == 200
    assert rendered_self_headshot["Content-Type"] == "image/png"
    assert b"".join(rendered_self_headshot.streaming_content).startswith(b"\x89PNG\r\n\x1a\n")

    client.force_login(second)
    scoped = client.get(profile_url)
    assert scoped.status_code == 200
    assert biography.encode() not in scoped.content

    client.force_login(users["chair"])
    organiser = client.get(f"/orga/{event.slug}/speaker-operations/speakers/")
    assert organiser.status_code == 200
    assert biography.encode() in organiser.content
    assert social_url.encode() in organiser.content
    assert b"data-speakerops-headshot" in organiser.content
    assert b"speaker-headshot.png" in organiser.content
    assert b"Uploaded" in organiser.content
    organiser_headshot_url = reverse(
        "plugins:speakerops:speakerops_organiser_speaker_headshot",
        kwargs={"event": event.slug, "pk": users["speaker"].pk},
    )
    assert organiser_headshot_url.encode() in organiser.content
    rendered_organiser_headshot = client.get(organiser_headshot_url)
    assert rendered_organiser_headshot.status_code == 200


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
    with patch("pretalx.common.mail.mail_send_task.apply_async") as dispatch:
        call_command("speakerops_send_reminders", event=event.slug, stdout=output)
        first = json.loads(output.getvalue())
        second = send_due_speaker_reminders(event.slug)
    assert first[event.slug] == 1
    assert second[event.slug] == 0
    assert dispatch.call_count == 1
    with scope(event=event):
        receipt = ReminderReceipt.objects.get(task=task)
        assert receipt.reminder_key == f"onboarding-overdue:{timezone.localdate().isoformat()}"
        mail = QueuedMail.objects.get(pk=receipt.queued_mail_id)
        assert mail.sent is not None
        assert list(mail.to_users.all()) == [users["speaker"]]
        assert task.definition.name in mail.subject
        assert task.definition.name in mail.text
        assert task.due_date.isoformat() in mail.text
        communication = SpeakerCommunicationLog.objects.get(
            event=event,
            speaker=users["speaker"],
            kind=SpeakerCommunicationLog.AUTOMATED_REMINDER,
        )
        assert communication.outcome == SpeakerCommunicationLog.SENT
        assert communication.actor is None
        assert communication.queued_mail_id == mail.pk
        assert communication.subject == mail.subject
        assert communication.rendered_body == mail.text
        assert communication.outcome_detail == (
            "Pretalx accepted the automated reminder for delivery."
        )


@pytest.mark.django_db(transaction=True)
def test_scheduled_reminder_broker_failure_is_durably_ambiguous(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        task.due_date = timezone.localdate() - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])

    with (
        patch(
            "pretalx.common.mail.mail_send_task.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ),
        pytest.raises(ReminderOutcomeAmbiguous),
    ):
        send_due_speaker_reminders(event.slug)

    with scope(event=event):
        receipt = ReminderReceipt.objects.get(task=task)
        assert receipt.delivery_status == ReminderReceipt.AMBIGUOUS
        assert receipt.queued_mail_id
        communication = SpeakerCommunicationLog.objects.get(
            event=event,
            speaker=users["speaker"],
            kind=SpeakerCommunicationLog.AUTOMATED_REMINDER,
        )
        assert communication.outcome == SpeakerCommunicationLog.FAILED
        assert communication.actor is None
        assert communication.queued_mail_id == receipt.queued_mail_id
        assert communication.outcome_detail == (
            "Broker outcome is ambiguous; automatic retry suppressed."
        )

    with patch("pretalx.common.mail.mail_send_task.apply_async") as dispatch:
        with pytest.raises(ReminderOutcomeAmbiguous):
            send_due_speaker_reminders(event.slug)
    dispatch.assert_not_called()
    with scope(event=event):
        assert (
            SpeakerCommunicationLog.objects.filter(
                event=event,
                speaker=users["speaker"],
                kind=SpeakerCommunicationLog.AUTOMATED_REMINDER,
            ).count()
            == 1
        )

    with patch(
        "pretalx_speakerops.tasks.send_due_speaker_reminders",
        side_effect=ReminderOutcomeAmbiguous(receipt),
    ):
        result = send_due_speaker_reminders_task.apply(task_id="scheduled-test-task").get()
    assert result == {
        "status": "ambiguous",
        "task_id": task.pk,
        "reminder_receipt_id": receipt.pk,
        "retry_suppressed": True,
    }

    client.force_login(users["chair"])
    with patch(
        "pretalx_speakerops.views.queue_reminders",
        side_effect=ReminderOutcomeAmbiguous(receipt),
    ):
        response = client.post(
            reverse("plugins:speakerops:speakerops_reminders", args=[event.slug]),
            {"confirm_reminders": "yes", "tasks": [task.pk]},
        )
    assert response.status_code == 302
