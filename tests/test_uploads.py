from io import BytesIO
from zipfile import ZipFile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django_scopes import scope

from pretalx_speakerops.models import OnboardingTask, TaskEvidence

SCANNED_UPLOADS = []


def capture_upload_scan(*, upload, filename, content_type):
    SCANNED_UPLOADS.append((filename, content_type, upload.read(5)))


def _accepted_task(event, users, slug):
    submission = event.submissions.first()
    submission.speakers.add(users["speaker"])
    submission.accept(person=users["chair"], force=True)
    return OnboardingTask.objects.get(
        event=event,
        submission=submission,
        speaker=users["speaker"],
        definition__slug=slug,
    )


def _pptx_bytes():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("ppt/presentation.xml", "<p:presentation></p:presentation>")
    return payload.getvalue()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("slug", "filename", "content_type", "content"),
    [
        ("slides", "deck.pdf", "application/pdf", b"%PDF-1.7\n%%EOF"),
        (
            "slides",
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            _pptx_bytes(),
        ),
        ("headshot", "speaker.jpg", "image/jpeg", b"\xff\xd8\xff\xe0photo"),
        ("headshot", "speaker.png", "image/png", b"\x89PNG\r\n\x1a\nphoto"),
    ],
)
def test_validated_uploads_complete_through_http(
    event, users, client, slug, filename, content_type, content
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, slug)
    client.force_login(users["speaker"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {"upload": SimpleUploadedFile(filename, content, content_type=content_type)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200
    assert response.json()["saved"] is True
    task.refresh_from_db()
    assert task.status == OnboardingTask.COMPLETE
    with scope(event=event):
        assert TaskEvidence.objects.get(task=task).content_type == content_type


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("filename", "content_type", "content", "message"),
    [
        ("deck.pdf", "text/plain", b"%PDF-1.7", "does not match"),
        ("deck.pdf", "application/pdf", b"plain text", "contents do not match"),
        (
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"PK\x03\x04not-a-zip",
            "not a valid PPTX",
        ),
        ("deck.exe", "application/octet-stream", b"MZ", "Unsupported file extension"),
    ],
)
def test_upload_endpoint_rejects_extension_mime_and_signature_mismatches(
    event, users, client, filename, content_type, content, message
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {"upload": SimpleUploadedFile(filename, content, content_type=content_type)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 400
    assert message in response.json()["error"]
    task.refresh_from_db()
    assert task.status == OnboardingTask.PENDING
    with scope(event=event):
        assert not TaskEvidence.objects.filter(task=task).exists()


@pytest.mark.django_db(transaction=True)
def test_upload_ui_explains_recovery_and_completed_file_identity(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    checklist_url = f"/{event.slug}/speaker-operations/checklist/"
    pending = client.get(checklist_url)
    assert pending.status_code == 200
    assert b"Upload progress" in pending.content
    assert b"Cancel selection" in pending.content
    assert b"Retry upload" in pending.content
    assert b"Privacy:" in pending.content

    client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {
            "upload": SimpleUploadedFile(
                "final-deck.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            )
        },
    )
    completed = client.get(checklist_url)
    assert b"final-deck.pdf" in completed.content


@pytest.mark.django_db(transaction=True)
def test_upload_endpoint_preserves_size_limit(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "headshot")
    client.force_login(users["speaker"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {
            "upload": SimpleUploadedFile(
                "large.png",
                b"\x89PNG\r\n\x1a\n" + b"x" * 5_000_001,
                content_type="image/png",
            )
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 400
    assert "5 MB size limit" in response.json()["error"]


@pytest.mark.django_db(transaction=True)
@override_settings(SPEAKEROPS_UPLOAD_SCANNER="tests.test_uploads.capture_upload_scan")
def test_upload_endpoint_calls_configured_scanner_hook(event, users, client):
    SCANNED_UPLOADS.clear()
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {
            "upload": SimpleUploadedFile(
                "scanned.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            )
        },
    )
    assert response.status_code == 302
    assert SCANNED_UPLOADS == [("scanned.pdf", "application/pdf", b"%PDF-")]


@pytest.mark.django_db(transaction=True)
def test_lost_response_retry_returns_existing_file_identity_without_duplicate(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    url = f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/"
    first = client.post(
        url,
        {
            "upload": SimpleUploadedFile(
                "retry-safe.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            )
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert first.status_code == 200
    retry = client.post(url, {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert retry.status_code == 200
    assert retry.json()["filename"].endswith(".pdf")
    with scope(event=event):
        assert TaskEvidence.objects.filter(task=task).count() == 1


@pytest.mark.django_db(transaction=True)
def test_replacement_upload_keeps_version_history_and_is_retry_safe(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    url = f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/"
    for request_id, filename in (("first-upload", "v1.pdf"), ("replacement", "v2.pdf")):
        response = client.post(
            url,
            {
                "upload_request_id": request_id,
                "upload": SimpleUploadedFile(
                    filename, b"%PDF-1.7\n%%EOF", content_type="application/pdf"
                ),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200

    retry = client.post(
        url,
        {
            "upload_request_id": "replacement",
            "upload": SimpleUploadedFile(
                "v2.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            ),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert retry.status_code == 200
    with scope(event=event):
        evidence = list(TaskEvidence.objects.filter(task=task).order_by("version"))
    assert [item.version for item in evidence] == [1, 2]
    assert [item.review_status for item in evidence] == [
        TaskEvidence.PENDING,
        TaskEvidence.PENDING,
    ]
    checklist = client.get(f"/{event.slug}/speaker-operations/checklist/")
    assert checklist.content.count(b"Download v") == 2
    assert checklist.content.count(b"Current/latest") == 1
    for item in evidence:
        download = client.get(f"/{event.slug}/speaker-operations/evidence/{item.pk}/download/")
        assert download.status_code == 200
        assert b"%PDF-1.7" in b"".join(download.streaming_content)

    client.force_login(users["reviewer"])
    assert (
        client.get(
            f"/{event.slug}/speaker-operations/evidence/{evidence[0].pk}/download/"
        ).status_code
        == 404
    )


@pytest.mark.django_db(transaction=True)
def test_operator_approval_and_change_request_are_audited(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        task = _accepted_task(event, users, "slides")
    client.force_login(users["speaker"])
    upload_url = f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/"
    client.post(
        upload_url,
        {
            "upload_request_id": "review-me",
            "upload": SimpleUploadedFile(
                "review.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            ),
        },
    )
    with scope(event=event):
        evidence = TaskEvidence.objects.get(task=task)

    client.force_login(users["chair"])
    content = client.get(f"/orga/{event.slug}/speaker-operations/content/")
    assert content.status_code == 200
    assert b"Approve version 1" in content.content
    assert b"Request changes" in content.content

    missing_note = client.post(
        f"/orga/{event.slug}/speaker-operations/evidence/{evidence.pk}/request-changes/"
    )
    assert missing_note.status_code == 302
    task.refresh_from_db()
    assert task.status == OnboardingTask.COMPLETE

    changed = client.post(
        f"/orga/{event.slug}/speaker-operations/evidence/{evidence.pk}/request-changes/",
        {"review_note": "Replace the unreadable code samples."},
    )
    assert changed.status_code == 302
    task.refresh_from_db()
    evidence.refresh_from_db()
    assert task.status == OnboardingTask.REOPENED
    assert evidence.review_status == TaskEvidence.CHANGES_REQUESTED
    assert evidence.review_note == "Replace the unreadable code samples."
    assert evidence.reviewed_by == users["chair"]

    client.force_login(users["speaker"])
    client.post(
        upload_url,
        {
            "upload_request_id": "review-fixed",
            "upload": SimpleUploadedFile(
                "fixed.pdf", b"%PDF-1.7\n%%EOF", content_type="application/pdf"
            ),
        },
    )
    with scope(event=event):
        fixed = TaskEvidence.objects.get(task=task, version=2)
    client.force_login(users["chair"])
    approved = client.post(
        f"/orga/{event.slug}/speaker-operations/evidence/{fixed.pk}/approve/",
        {"review_note": "Approved for the speaker resource pack."},
    )
    assert approved.status_code == 302
    fixed.refresh_from_db()
    assert fixed.review_status == TaskEvidence.APPROVED
    assert fixed.reviewed_at is not None
