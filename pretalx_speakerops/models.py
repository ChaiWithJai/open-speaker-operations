from django.conf import settings
from django.db import models
from django.utils import timezone
from pretalx.common.models.mixins import PretalxModel


class EventOwnedModel(PretalxModel):
    event = models.ForeignKey("event.Event", on_delete=models.CASCADE)

    class Meta:
        abstract = True


class CommandReceipt(EventOwnedModel):
    key = models.CharField(max_length=200)
    command = models.CharField(max_length=200)
    aggregate_type = models.CharField(max_length=200)
    aggregate_id = models.PositiveBigIntegerField()
    result = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("event", "key"), name="speakerops_receipt_event_key")
        ]


class TransitionLog(EventOwnedModel):
    aggregate_type = models.CharField(max_length=200)
    aggregate_id = models.PositiveBigIntegerField()
    from_state = models.CharField(max_length=100, blank=True)
    to_state = models.CharField(max_length=100)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict)


class OutboxEvent(EventOwnedModel):
    kind = models.CharField(max_length=200)
    aggregate_type = models.CharField(max_length=200)
    aggregate_id = models.PositiveBigIntegerField()
    payload = models.JSONField(default=dict)
    created = models.DateTimeField(default=timezone.now)
    processed = models.DateTimeField(null=True, blank=True)


class TaskDefinition(EventOwnedModel):
    template = models.ForeignKey(
        "onboardingtemplate",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="definitions",
    )
    position = models.PositiveIntegerField(default=0)
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    instructions = models.TextField()
    completion_criteria = models.TextField()
    task_type = models.CharField(max_length=40, default="acknowledgement")
    completion_evaluator = models.CharField(max_length=60, default="acknowledgement")
    evaluator_config = models.JSONField(default=dict)
    due_days_after_acceptance = models.PositiveIntegerField(default=14)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "slug"), name="speakerops_definition_event_slug"
            )
        ]


class OnboardingTask(EventOwnedModel):
    PENDING = "pending"
    COMPLETE = "complete"
    REOPENED = "reopened"
    WAIVED = "waived"
    STATUS_CHOICES = (
        (PENDING, "Pending"),
        (COMPLETE, "Complete"),
        (REOPENED, "Reopened"),
        (WAIVED, "Waived"),
    )

    submission = models.ForeignKey(
        "submission.Submission", null=True, blank=True, on_delete=models.CASCADE
    )
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    definition = models.ForeignKey(TaskDefinition, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(default=timezone.now)
    evidence = models.JSONField(default=dict)
    waiver_reason = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "speaker", "definition"),
                name="speakerops_task_submission_speaker_definition",
            )
        ]


class PreviewRun(EventOwnedModel):
    status = models.CharField(max_length=30, default="created")
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)


class OnboardingTemplate(EventOwnedModel):
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("event", "slug"), name="speakerops_template_event_slug")
        ]


class TaskEvidence(EventOwnedModel):
    task = models.ForeignKey(
        OnboardingTask, on_delete=models.CASCADE, related_name="evidence_items"
    )
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kind = models.CharField(max_length=50)
    value = models.JSONField(default=dict)
    upload = models.FileField(upload_to="speakerops/evidence/", null=True, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)


class ReminderReceipt(EventOwnedModel):
    task = models.ForeignKey(OnboardingTask, on_delete=models.CASCADE)
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reminder_key = models.CharField(max_length=160)
    queued_mail_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "task", "speaker", "reminder_key"),
                name="speakerops_reminder_dedupe",
            )
        ]


class Resource(EventOwnedModel):
    slug = models.SlugField(max_length=100)
    title = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("event", "slug"), name="speakerops_resource_event_slug")
        ]


class ResourceVersion(EventOwnedModel):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    body_html = models.TextField()
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("resource", "version"), name="speakerops_resource_version"
            )
        ]


class ScheduleIcsIdentity(EventOwnedModel):
    submission = models.ForeignKey(
        "submission.Submission", on_delete=models.CASCADE, related_name="speakerops_ics"
    )
    uid = models.CharField(max_length=300)
    sequence = models.PositiveIntegerField(default=0)
    fingerprint = models.CharField(max_length=64)
    canceled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "submission"), name="speakerops_ics_event_submission"
            )
        ]
