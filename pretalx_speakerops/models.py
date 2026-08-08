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
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    instructions = models.TextField()
    completion_criteria = models.TextField()
    task_type = models.CharField(max_length=40, default="acknowledgement")
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
    STATUS_CHOICES = ((PENDING, "Pending"), (COMPLETE, "Complete"))

    submission = models.ForeignKey(
        "submission.Submission", null=True, blank=True, on_delete=models.CASCADE
    )
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    definition = models.ForeignKey(TaskDefinition, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
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
