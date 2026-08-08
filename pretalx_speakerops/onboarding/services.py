from datetime import timedelta

from django.utils import timezone
from django_scopes import scope

from ..models import OnboardingTask, OnboardingTemplate, TaskDefinition, TaskEvidence

DEFAULT_DEFINITIONS = (
    ("profile", "Profile biography", "profile_field", {"field": "biography"}, 14),
    ("acknowledgement", "Acknowledge participation", "acknowledgement", {}, 14),
    (
        "headshot",
        "Upload a headshot",
        "upload",
        {"extensions": [".jpg", ".jpeg", ".png"], "max_size": 5_000_000},
        10,
    ),
    (
        "slides",
        "Upload slides",
        "upload",
        {"extensions": [".pdf", ".pptx"], "max_size": 20_000_000},
        7,
    ),
    (
        "supporting-document",
        "Upload supporting document",
        "upload",
        {"extensions": [".pdf"], "max_size": 10_000_000},
        7,
    ),
)


def get_or_create_default_template(event):
    template, _ = OnboardingTemplate.objects.get_or_create(
        event=event, slug="standard-speaker", defaults={"name": "Standard speaker onboarding"}
    )
    for position, (slug, name, evaluator, config, due_days) in enumerate(DEFAULT_DEFINITIONS):
        TaskDefinition.objects.get_or_create(
            event=event,
            template=template,
            slug=slug,
            defaults={
                "position": position,
                "name": name,
                "instructions": f"Complete: {name}.",
                "completion_criteria": "Provide the requested evidence.",
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
    if upload:
        suffix = upload.name.lower().rsplit(".", 1)[-1]
        allowed = [item.lstrip(".").lower() for item in config.get("extensions", [])]
        if allowed and suffix not in allowed:
            raise ValueError("Unsupported upload type")
        if upload.size > config.get("max_size", 20_000_000):
            raise ValueError("Upload exceeds the size limit")
    evidence = TaskEvidence.objects.create(
        event=task.event,
        task=task,
        speaker=speaker,
        kind=kind,
        value=value or {},
        upload=upload,
        content_type=getattr(upload, "content_type", "") if upload else "",
        size=getattr(upload, "size", None),
    )
    if kind == "acknowledgement":
        task.evidence = {**task.evidence, "acknowledged_at": timezone.now().isoformat()}
        task.save(update_fields=["evidence", "updated"])
    return evidence, evaluate_task(task)
