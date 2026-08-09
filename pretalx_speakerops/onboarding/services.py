from datetime import timedelta
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string
from django_scopes import scope

from ..models import OnboardingTask, OnboardingTemplate, TaskDefinition, TaskEvidence

DEFAULT_DEFINITIONS = (
    (
        "profile",
        "Add your speaker biography",
        "profile_field",
        {"field": "biography"},
        14,
        "Write a short biography for the public speaker page.",
        "A biography has been saved to your event profile.",
    ),
    (
        "acknowledgement",
        "Confirm your participation",
        "acknowledgement",
        {},
        14,
        "Confirm that you plan to participate in this event.",
        "The participation acknowledgement is checked.",
    ),
    (
        "headshot",
        "Upload a headshot",
        "upload",
        {"extensions": [".jpg", ".jpeg", ".png"], "max_size": 5_000_000},
        10,
        "Upload a clear JPG or PNG portrait for the public program.",
        "A JPG or PNG image no larger than 5 MB has been uploaded.",
    ),
    (
        "slides",
        "Upload slides",
        "upload",
        {"extensions": [".pdf", ".pptx"], "max_size": 20_000_000},
        7,
        "Upload the final deck as a PDF or PowerPoint file.",
        "A PDF or PPTX file no larger than 20 MB has been uploaded.",
    ),
    (
        "supporting-document",
        "Upload supporting document",
        "upload",
        {"extensions": [".pdf"], "max_size": 10_000_000},
        7,
        "Upload any handout or supporting material as a PDF.",
        "A PDF no larger than 10 MB has been uploaded.",
    ),
)

UPLOAD_TYPES = {
    "pdf": {
        "mime_types": {"application/pdf"},
        "signature": lambda header: header.startswith(b"%PDF-"),
    },
    "pptx": {
        "mime_types": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        "signature": lambda header: header.startswith(b"PK\x03\x04"),
    },
    "jpg": {
        "mime_types": {"image/jpeg", "image/pjpeg"},
        "signature": lambda header: header.startswith(b"\xff\xd8\xff"),
    },
    "jpeg": {
        "mime_types": {"image/jpeg", "image/pjpeg"},
        "signature": lambda header: header.startswith(b"\xff\xd8\xff"),
    },
    "png": {
        "mime_types": {"image/png"},
        "signature": lambda header: header.startswith(b"\x89PNG\r\n\x1a\n"),
    },
}


def _validate_upload(upload, config):
    suffix = upload.name.lower().rsplit(".", 1)[-1] if "." in upload.name else ""
    allowed = [item.lstrip(".").lower() for item in config.get("extensions", [])]
    if allowed and suffix not in allowed:
        raise ValueError(f"Unsupported file extension. Choose: {', '.join(allowed).upper()}.")
    if upload.size > config.get("max_size", 20_000_000):
        limit_mb = config.get("max_size", 20_000_000) / 1_000_000
        raise ValueError(f"Upload exceeds the {limit_mb:g} MB size limit.")
    expected = UPLOAD_TYPES.get(suffix)
    if not expected:
        raise ValueError("This upload format has no content validator configured.")
    content_type = (getattr(upload, "content_type", "") or "").lower().split(";", 1)[0]
    if content_type not in expected["mime_types"]:
        raise ValueError(
            f"The browser reported {content_type or 'no MIME type'}, which does not match "
            f"the .{suffix} file extension."
        )
    position = upload.tell()
    try:
        upload.seek(0)
        header = upload.read(16)
        if not expected["signature"](header):
            raise ValueError(
                f"The file contents do not match the .{suffix} file extension and MIME type."
            )
        if suffix == "pptx":
            upload.seek(0)
            try:
                with ZipFile(upload) as archive:
                    names = set(archive.namelist())
            except (BadZipFile, OSError):
                raise ValueError("The PowerPoint file is not a valid PPTX archive.") from None
            required_members = {"[Content_Types].xml", "ppt/presentation.xml"}
            if not required_members.issubset(names):
                raise ValueError("The PowerPoint archive is missing required PPTX content.")
    finally:
        upload.seek(position)

    scanner_path = getattr(settings, "SPEAKEROPS_UPLOAD_SCANNER", "")
    if scanner_path:
        upload.seek(0)
        try:
            import_string(scanner_path)(
                upload=upload,
                filename=upload.name,
                content_type=content_type,
            )
        finally:
            upload.seek(position)


def get_or_create_default_template(event):
    template, _ = OnboardingTemplate.objects.get_or_create(
        event=event, slug="standard-speaker", defaults={"name": "Standard speaker onboarding"}
    )
    for position, (
        slug,
        name,
        evaluator,
        config,
        due_days,
        instructions,
        completion_criteria,
    ) in enumerate(DEFAULT_DEFINITIONS):
        TaskDefinition.objects.update_or_create(
            event=event,
            slug=slug,
            defaults={
                "template": template,
                "position": position,
                "name": name,
                "instructions": instructions,
                "completion_criteria": completion_criteria,
                "task_type": evaluator,
                "completion_evaluator": evaluator,
                "evaluator_config": config,
                "due_days_after_acceptance": due_days,
            },
        )
    return template


def ensure_acceptance_plan(submission):
    event = submission.event
    with scope(event=event):
        template = OnboardingTemplate.objects.filter(event=event, active=True).first()
        template = template or get_or_create_default_template(event)
        accepted_at = timezone.now()
        for speaker in submission.speakers.all():
            for definition in template.definitions.filter(active=True).order_by("position", "id"):
                task, _ = OnboardingTask.objects.get_or_create(
                    event=event,
                    submission=submission,
                    speaker=speaker,
                    definition=definition,
                    defaults={
                        "accepted_at": accepted_at,
                        "due_date": (
                            accepted_at + timedelta(days=definition.due_days_after_acceptance)
                        ).date(),
                    },
                )
                if task.status in (OnboardingTask.PENDING, OnboardingTask.REOPENED):
                    evaluate_task(task)


def evaluate_task(task):
    definition = task.definition
    evaluator = definition.completion_evaluator
    complete = False
    if evaluator == "acknowledgement":
        complete = bool(task.evidence.get("acknowledged_at"))
    elif evaluator == "profile_field":
        from pretalx.person.models import SpeakerProfile

        profile = SpeakerProfile.objects.filter(event=task.event, user=task.speaker).first()
        complete = bool(
            profile and getattr(profile, definition.evaluator_config.get("field", ""), None)
        )
    elif evaluator == "question":
        from pretalx.submission.models import Answer

        complete = (
            Answer.objects.filter(
                person=task.speaker, question_id=definition.evaluator_config.get("question_id")
            )
            .exclude(answer="")
            .exists()
        )
    elif evaluator == "upload":
        complete = task.evidence_items.filter(upload__isnull=False).exists()
    return complete


def record_evidence(task, speaker, kind, value=None, upload=None):
    config = task.definition.evaluator_config
    value = value or {}
    if kind == "profile_field":
        from pretalx.person.models import SpeakerProfile

        field = config.get("field")
        response = str(value.get("response", "")).strip()
        if field not in {"biography"} or not response:
            raise ValueError("Add your biography before completing this task.")
        profile, _ = SpeakerProfile.objects.get_or_create(event=task.event, user=speaker)
        setattr(profile, field, response)
        profile.save(update_fields=[field, "updated"])
    if kind == "upload" and not upload:
        raise ValueError("Choose a file before submitting this task.")
    if upload:
        _validate_upload(upload, config)
    latest_version = (
        TaskEvidence.objects.filter(task=task)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
        or 0
    )
    evidence = TaskEvidence.objects.create(
        event=task.event,
        task=task,
        speaker=speaker,
        kind=kind,
        value=value,
        upload=upload,
        content_type=getattr(upload, "content_type", "") if upload else "",
        size=getattr(upload, "size", None),
        version=latest_version + 1,
        review_status=TaskEvidence.PENDING if upload else TaskEvidence.APPROVED,
    )
    if kind == "acknowledgement":
        task.evidence = {**task.evidence, "acknowledged_at": timezone.now().isoformat()}
        task.save(update_fields=["evidence", "updated"])
    return evidence, evaluate_task(task)
