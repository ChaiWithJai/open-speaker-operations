from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_scopes import scope
from PIL import Image
from pretalx.person.models import SpeakerProfile
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.models import (
    ContentRevision,
    EvidenceComment,
    OnboardingTask,
    SessionPublicationApproval,
    TaskDefinition,
)
from pretalx_speakerops.onboarding.services import record_evidence


def _upload_task(event, users):
    submission = event.submissions.first()
    submission.speakers.add(users["speaker"])
    submission.accept(person=users["chair"], force=True)
    task = OnboardingTask.objects.get(
        event=event,
        submission=submission,
        speaker=users["speaker"],
        definition__slug="slides",
    )
    evidence, _ = record_evidence(
        task,
        users["speaker"],
        "upload",
        upload=SimpleUploadedFile(
            "operator-deck.pdf",
            b"%PDF-1.7\ncontent-operations\n%%EOF",
            content_type="application/pdf",
        ),
    )
    return task, evidence


@pytest.mark.django_db(transaction=True)
def test_organiser_creates_file_request_and_assigns_multiple_speakers(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submissions = list(event.submissions.all()[:2])
        submissions[0].speakers.add(users["speaker"])
        submissions[1].speakers.add(users["reviewer"])
        submissions[0].accept(person=users["chair"], force=True)
        submissions[1].accept(person=users["chair"], force=True)

    client.force_login(users["chair"])
    due = date.today() + timedelta(days=9)
    form = client.get(f"/orga/{event.slug}/speaker-operations/content/")
    assert form.status_code == 200
    for submission, speaker in (
        (submissions[0], users["speaker"]),
        (submissions[1], users["reviewer"]),
    ):
        assert any(
            row["submission"].pk == submission.pk and row["speaker"].pk == speaker.pk
            for row in form.context["assignment_rows"]
        )
        assert submission.title.encode() in form.content
    response = client.post(
        f"/orga/{event.slug}/speaker-operations/content/file-requests/",
        {
            "name": "Caption file",
            "instructions": "Upload the final WebVTT captions.",
            "completion_criteria": "One PDF or PPTX caption reference file",
            "extensions": ".pdf,.pptx",
            "due_date": due.isoformat(),
            "assignments": [
                f"{submissions[0].pk}:{users['speaker'].pk}",
                f"{submissions[1].pk}:{users['reviewer'].pk}",
            ],
        },
    )
    assert response.status_code == 302
    with scope(event=event):
        definition = TaskDefinition.objects.get(event=event, name="Caption file")
        assert definition.completion_evaluator == "upload"
        assert definition.evaluator_config["extensions"] == [".pdf", ".pptx"]
        tasks = list(OnboardingTask.objects.filter(definition=definition).order_by("speaker_id"))
    assert len(tasks) == 2
    assert {task.speaker_id for task in tasks} == {
        users["speaker"].pk,
        users["reviewer"].pk,
    }
    assert {task.due_date for task in tasks} == {due}
    assert {task.submission_id for task in tasks} == {
        submissions[0].pk,
        submissions[1].pk,
    }
    filtered = client.get(
        f"/orga/{event.slug}/speaker-operations/content/",
        {"request": definition.pk, "status": "missing"},
    )
    assert filtered.status_code == 200
    assert len(filtered.context["rows"]) == 2
    one_speaker = client.get(
        f"/orga/{event.slug}/speaker-operations/content/",
        {"request": definition.pk, "speaker": users["speaker"].pk},
    )
    assert len(one_speaker.context["rows"]) == 1


@pytest.mark.django_db(transaction=True)
def test_organiser_download_comments_and_latest_version_zip_are_scoped(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task, evidence = _upload_task(event, users)
        latest, _ = record_evidence(
            task,
            users["speaker"],
            "upload",
            upload=SimpleUploadedFile(
                "slides.pdf",
                b"%PDF-1.7\nlatest-version-only\n%%EOF",
                content_type="application/pdf",
            ),
        )
        headshot_task = OnboardingTask.objects.get(
            event=event,
            submission=task.submission,
            speaker=users["speaker"],
            definition__slug="headshot",
        )
        headshot, _ = record_evidence(
            headshot_task,
            users["speaker"],
            "upload",
            upload=SimpleUploadedFile(
                "headshot.png",
                b"\x89PNG\r\n\x1a\nheadshot",
                content_type="image/png",
            ),
        )

    client.force_login(users["chair"])
    download = client.get(
        f"/orga/{event.slug}/speaker-operations/content/evidence/{evidence.pk}/download/"
    )
    assert download.status_code == 200
    assert b"content-operations" in b"".join(download.streaming_content)

    response = client.post(
        f"/orga/{event.slug}/speaker-operations/content/evidence/{evidence.pk}/comments/",
        {"body": "Please add the licensing slide."},
    )
    assert response.status_code == 302

    client.force_login(users["speaker"])
    checklist = client.get(f"/{event.slug}/speaker-operations/checklist/")
    assert b"Please add the licensing slide." in checklist.content
    reply = client.post(
        f"/{event.slug}/speaker-operations/checklist/evidence/{evidence.pk}/comments/",
        {"body": "Added in the next version."},
    )
    assert reply.status_code == 302

    client.force_login(users["chair"])
    content = client.get(f"/orga/{event.slug}/speaker-operations/content/")
    assert content.status_code == 200
    assert b"Central files library" in content.content
    assert b"Generate ZIP of latest selected files" in content.content
    assert b"Please add the licensing slide." in content.content
    assert b"Added in the next version." in content.content
    assert users["chair"].name.encode() in content.content
    assert users["speaker"].name.encode() in content.content
    assert b"Complete/uploaded" in content.content
    assert b"2 versions" in content.content
    assert b"Session, then speaker" in content.content
    assert b"Only the current/latest version" in content.content
    assert b"Ready to generate a ZIP" in content.content
    with scope(event=event):
        assert EvidenceComment.objects.filter(evidence=evidence).count() == 2

    exported_all = client.post(
        f"/orga/{event.slug}/speaker-operations/content/latest.zip",
        {
            "tasks": [str(task.pk), str(headshot_task.pk)],
            "grouping": "session",
        },
    )
    assert exported_all.status_code == 200
    with ZipFile(BytesIO(exported_all.content)) as archive:
        assert len(archive.namelist()) == 2
        assert any(
            f"v{latest.version}-{latest.pk}-slides.pdf" in name for name in archive.namelist()
        )
        assert any(
            f"v{headshot.version}-{headshot.pk}-headshot.png" in name for name in archive.namelist()
        )

    # Exact deselection proof: the headshot is uploaded but excluded when only
    # the slides task remains selected.
    exported = client.post(
        f"/orga/{event.slug}/speaker-operations/content/latest.zip",
        {"tasks": [str(task.pk)], "grouping": "session"},
    )
    assert exported.status_code == 200
    assert exported["Content-Type"] == "application/zip"
    assert exported["X-SpeakerOps-File-Count"] == "1"
    with ZipFile(BytesIO(exported.content)) as archive:
        assert len(archive.namelist()) == 1
        archive_name = archive.namelist()[0]
        assert f"v{latest.version}-{latest.pk}-" in archive_name
        assert "headshot" not in archive_name
        assert archive.read(archive_name) == b"%PDF-1.7\nlatest-version-only\n%%EOF"


@pytest.mark.django_db(transaction=True)
def test_legacy_speaker_assignment_chooses_accepted_session_not_first_proposal(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        proposals = list(event.submissions.all()[:2])
        proposals[0].speakers.add(users["speaker"])
        proposals[0].state = SubmissionStates.DRAFT
        proposals[0].save(update_fields=["state", "updated"])
        proposals[1].speakers.add(users["speaker"])
        proposals[1].accept(person=users["chair"], force=True)

    client.force_login(users["chair"])
    response = client.post(
        f"/orga/{event.slug}/speaker-operations/content/file-requests/",
        {
            "name": "Accepted-session deck",
            "instructions": "Upload the accepted session deck.",
            "completion_criteria": "PDF up to 20 MB",
            "extensions": ".pdf",
            "due_date": (date.today() + timedelta(days=10)).isoformat(),
            "speakers": [str(users["speaker"].pk)],
        },
    )
    assert response.status_code == 302
    with scope(event=event):
        task = OnboardingTask.objects.get(definition__name="Accepted-session deck")
    assert task.submission_id == proposals[1].pk
    assert task.submission_id != proposals[0].pk


@pytest.mark.django_db(transaction=True)
def test_task_drilldowns_name_status_and_route_upload_work_to_content(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)

    client.force_login(users["chair"])
    tasks = client.get(f"/orga/{event.slug}/speaker-operations/tasks/")
    missing = client.get(f"/orga/{event.slug}/speaker-operations/missing-assets/")
    assert tasks.status_code == missing.status_code == 200
    assert b"Pending" in tasks.content
    assert b"open Content" in tasks.content
    assert b"Pending" in missing.content
    assert b"No file uploaded" in missing.content
    assert b"Open the canonical Content files dashboard" in missing.content


@pytest.mark.django_db(transaction=True)
def test_content_journey_upload_updates_filterable_dashboard_and_library(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.get(
            event=event,
            submission=submission,
            speaker=users["speaker"],
            definition__slug="slides",
        )

    client.force_login(users["speaker"])
    checklist_url = f"/{event.slug}/speaker-operations/checklist/"
    before = client.get(checklist_url)
    assert before.status_code == 200
    assert task.definition.name.encode() in before.content
    assert b"Due " in before.content
    portal_task = next(item for item in before.context["tasks"] if item.pk == task.pk)
    assert portal_task.due_date == task.due_date
    upload_url = f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/"
    for request_id, body in (("content-v1", b"first"), ("content-v2", b"latest")):
        response = client.post(
            upload_url,
            {
                "upload_request_id": request_id,
                "upload": SimpleUploadedFile(
                    "slides.pdf",
                    b"%PDF-1.7\n" + body + b"\n%%EOF",
                    content_type="application/pdf",
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200
        assert response.json()["saved"] is True

    task.refresh_from_db()
    assert task.status == OnboardingTask.COMPLETE
    client.force_login(users["chair"])
    dashboard_url = f"/orga/{event.slug}/speaker-operations/content/"
    dashboard = client.get(dashboard_url)
    assert dashboard.status_code == 200
    row = next(row for row in dashboard.context["rows"] if row.pk == task.pk)
    assert row.speakerops_latest_evidence.version == 2
    assert len(row.speakerops_evidence_items) == 2
    body = dashboard.content
    for expected in (
        b"Central files library",
        b"Complete/uploaded",
        b"2 versions",
        users["speaker"].name.encode(),
        users["speaker"].email.encode(),
        submission.title.encode(),
        b"slides.pdf",
        b"Current/latest",
        b"Apply filters",
    ):
        assert expected in body

    filtered = client.get(dashboard_url, {"speaker": users["speaker"].pk})
    assert filtered.status_code == 200
    assert filtered.context["selected_speaker"] == str(users["speaker"].pk)
    assert all(row.speaker_id == users["speaker"].pk for row in filtered.context["rows"])


@pytest.mark.django_db(transaction=True)
def test_content_portal_and_organiser_routes_are_speaker_scoped(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submissions = list(event.submissions.all()[:2])
        submissions[0].speakers.add(users["speaker"])
        submissions[0].accept(person=users["chair"], force=True)
        submissions[1].speakers.add(users["reviewer"])
        submissions[1].accept(person=users["chair"], force=True)
        other_task = OnboardingTask.objects.get(
            event=event,
            submission=submissions[1],
            speaker=users["reviewer"],
            definition__slug="slides",
        )
        other_evidence, _ = record_evidence(
            other_task,
            users["reviewer"],
            "upload",
            upload=SimpleUploadedFile(
                "marcus-private.pdf",
                b"%PDF-1.7\nprivate\n%%EOF",
                content_type="application/pdf",
            ),
        )

    client.force_login(users["speaker"])
    portal = client.get(f"/{event.slug}/speaker-operations/checklist/")
    assert portal.status_code == 200
    assert submissions[0].title.encode() in portal.content
    assert submissions[1].title.encode() not in portal.content
    assert users["reviewer"].email.encode() not in portal.content
    assert b"marcus-private.pdf" not in portal.content
    assert (
        client.get(
            f"/{event.slug}/speaker-operations/evidence/{other_evidence.pk}/download/"
        ).status_code
        == 404
    )
    for path in (
        f"/orga/{event.slug}/speaker-operations/",
        f"/orga/{event.slug}/speaker-operations/content/",
        f"/orga/{event.slug}/speaker-operations/speakers/",
    ):
        assert client.get(path).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_explicit_session_approval_controls_public_widgets(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        schedule = event.current_schedule
        if not schedule:
            pytest.skip("fixture has no released schedule")
        slot = (
            schedule.talks.filter(is_visible=True, submission__isnull=False)
            .select_related("submission")
            .first()
        )
        if not slot:
            pytest.skip("fixture has no released visible session")
        title = slot.submission.title.encode()

    baseline = client.get(f"/{event.slug}/speaker-operations/embed/")
    assert title in baseline.content

    client.force_login(users["chair"])
    pending = client.post(
        f"/orga/{event.slug}/speaker-operations/content/submissions/{slot.submission_id}/approval/",
        {"status": "pending", "note": "Awaiting final content review."},
    )
    assert pending.status_code == 302

    client.logout()
    gated = client.get(f"/{event.slug}/speaker-operations/embed/")
    assert title not in gated.content
    gated_ics = client.get(f"/{event.slug}/speaker-operations/schedule.ics")
    assert title not in gated_ics.content

    client.force_login(users["chair"])
    approved = client.post(
        f"/orga/{event.slug}/speaker-operations/content/submissions/{slot.submission_id}/approval/",
        {"status": "approved", "note": "Content approved."},
    )
    assert approved.status_code == 302
    with scope(event=event):
        approval = SessionPublicationApproval.objects.get(submission=slot.submission)
        assert approval.reviewed_by == users["chair"]
        assert approval.reviewed_at is not None

    client.logout()
    public = client.get(f"/{event.slug}/speaker-operations/embed/")
    assert title in public.content
    public_ics = client.get(f"/{event.slug}/speaker-operations/schedule.ics")
    assert title in public_ics.content


@pytest.mark.django_db(transaction=True)
def test_speaker_cannot_comment_on_another_speakers_file(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        _, evidence = _upload_task(event, users)
    client.force_login(users["reviewer"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/evidence/{evidence.pk}/comments/",
        {"body": "I should not be allowed here."},
    )
    assert response.status_code == 404
    with scope(event=event):
        assert not EvidenceComment.objects.filter(evidence=evidence).exists()


@pytest.mark.django_db(transaction=True)
def test_session_and_speaker_edits_are_attributed_and_restorable(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        original_title = submission.title
        original_abstract = submission.abstract
        profile, _ = SpeakerProfile.objects.get_or_create(event=event, user=users["speaker"])
        profile.biography = "Original biography"
        profile.save(update_fields=["biography", "updated"])

    client.force_login(users["chair"])
    session_edit = client.post(
        f"/orga/{event.slug}/speaker-operations/content/submissions/{submission.pk}/edit/",
        {"title": "Revised session title", "abstract": "Revised abstract"},
    )
    assert session_edit.status_code == 302
    headshot_bytes = BytesIO()
    Image.new("RGB", (8, 8), color=(23, 92, 211)).save(headshot_bytes, format="PNG")
    speaker_edit = client.post(
        f"/orga/{event.slug}/speaker-operations/content/speakers/{users['speaker'].pk}/edit/",
        {
            "biography": "Revised biography",
            "headshot": SimpleUploadedFile(
                "headshot.png",
                headshot_bytes.getvalue(),
                content_type="image/png",
            ),
        },
    )
    assert speaker_edit.status_code == 302

    with scope(event=event):
        session_revision = ContentRevision.objects.get(
            event=event,
            content_type=ContentRevision.SESSION,
            object_id=submission.pk,
        )
        speaker_revision = ContentRevision.objects.get(
            event=event,
            content_type=ContentRevision.SPEAKER,
            object_id=users["speaker"].pk,
        )
    assert session_revision.snapshot == {
        "title": original_title,
        "abstract": original_abstract,
    }
    assert session_revision.actor == users["chair"]
    assert speaker_revision.snapshot == {"biography": "Original biography", "avatar": ""}
    users["speaker"].refresh_from_db()
    assert users["speaker"].avatar.name.endswith(".png")
    assert users["speaker"].avatar.storage.exists(users["speaker"].avatar.name)
    avatar_url = reverse(
        "plugins:speakerops:speakerops_organiser_speaker_headshot",
        kwargs={"event": event.slug, "pk": users["speaker"].pk},
    )

    history = client.get(f"/orga/{event.slug}/speaker-operations/content/")
    assert original_title.encode() in history.content
    assert b"Original biography" in history.content
    assert users["chair"].name.encode() in history.content
    assert b"Restore this session version" in history.content
    assert b"Current headshot for" in history.content
    assert b"headshot.png" in history.content
    assert b"Uploaded" in history.content
    assert avatar_url.encode() in history.content
    assert (
        avatar_url.encode() in client.get(f"/orga/{event.slug}/speaker-operations/content/").content
    )
    rendered_headshot = client.get(avatar_url)
    assert rendered_headshot.status_code == 200
    assert rendered_headshot["Content-Type"] == "image/png"
    assert b"".join(rendered_headshot.streaming_content).startswith(b"\x89PNG\r\n\x1a\n")

    restored_session = client.post(
        f"/orga/{event.slug}/speaker-operations/content/revisions/{session_revision.pk}/restore/"
    )
    restored_speaker = client.post(
        f"/orga/{event.slug}/speaker-operations/content/revisions/{speaker_revision.pk}/restore/"
    )
    assert restored_session.status_code == 302
    assert restored_speaker.status_code == 302
    submission.refresh_from_db()
    profile.refresh_from_db()
    users["speaker"].refresh_from_db()
    assert submission.title == original_title
    assert submission.abstract == original_abstract
    assert profile.biography == "Original biography"
    assert users["speaker"].avatar.name == ""
    with scope(event=event):
        assert ContentRevision.objects.filter(event=event, restored_from__isnull=False).count() == 2


@pytest.mark.django_db(transaction=True)
def test_session_restore_removes_second_edit_but_keeps_first(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()

    client.force_login(users["chair"])
    edit_url = f"/orga/{event.slug}/speaker-operations/content/submissions/{submission.pk}/edit/"
    assert (
        client.post(
            edit_url,
            {"title": "First approved edit", "abstract": "First sentence retained."},
        ).status_code
        == 302
    )
    assert (
        client.post(
            edit_url,
            {
                "title": "Second temporary edit",
                "abstract": "First sentence retained. Second sentence removed.",
            },
        ).status_code
        == 302
    )

    with scope(event=event):
        restore_point = ContentRevision.objects.get(
            event=event,
            content_type=ContentRevision.SESSION,
            object_id=submission.pk,
            snapshot__title="First approved edit",
        )
    response = client.post(
        f"/orga/{event.slug}/speaker-operations/content/revisions/{restore_point.pk}/restore/"
    )

    assert response.status_code == 302
    submission.refresh_from_db()
    assert submission.title == "First approved edit"
    assert submission.abstract == "First sentence retained."
    assert "Second" not in submission.abstract
