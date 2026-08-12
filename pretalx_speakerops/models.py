from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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


class WorkflowActionReceipt(EventOwnedModel):
    """Durable, sanitized proof of a human-confirmed Buzz-assisted action.

    This is deliberately higher-level than ``CommandReceipt`` and
    ``ReminderReceipt``: one row represents the operator's confirmed workflow
    action, while the lower-level records retain per-aggregate delivery and
    transition evidence. ``result`` must contain counts, identifiers, and
    outcome classes only; connector payloads, responses, request IDs, and
    contact data do not belong here.
    """

    SPEAKER_NUDGES = "speaker_nudges"
    SYNC_RECOVERY = "sync_recovery"
    WORKFLOW_CHOICES = (
        (SPEAKER_NUDGES, "Speaker nudges"),
        (SYNC_RECOVERY, "Synchronization recovery"),
    )

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    NOOP = "noop"
    STATUS_CHOICES = (
        (PENDING, "Pending"),
        (SUCCEEDED, "Succeeded"),
        (PARTIAL, "Partial"),
        (FAILED, "Failed"),
        (AMBIGUOUS, "Ambiguous; inspect before retrying"),
        (NOOP, "No action needed"),
    )

    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES)
    action = models.CharField(max_length=80)
    correlation_id = models.UUIDField()
    requesting_principal = models.CharField(max_length=160)
    claimed_channel_id = models.CharField(max_length=200, blank=True, default="")
    claimed_trigger_event_id = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_workflow_action_receipts",
    )
    confirmed_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    target_count = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict)

    class Meta:
        ordering = ("-confirmed_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "correlation_id"),
                name="speakerops_workflow_receipt_event_correlation",
            )
        ]


class SyncWriteClaim(EventOwnedModel):
    """Central logical-record guard for every external synchronization write."""

    IN_PROGRESS = "in_progress"
    AMBIGUOUS = "ambiguous"
    STATUS_CHOICES = ((IN_PROGRESS, "In progress"), (AMBIGUOUS, "Ambiguous"))

    local_type = models.CharField(max_length=40)
    local_id = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=IN_PROGRESS)
    active = models.BooleanField(default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    receipt = models.ForeignKey(
        WorkflowActionReceipt,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_write_claims",
    )
    item = models.ForeignKey(
        "SyncItem",
        on_delete=models.PROTECT,
        related_name="write_claims",
    )
    claimed_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=80, blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_speakerops_sync_claims",
    )
    resolution_note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "local_type", "local_id"),
                condition=Q(active=True),
                name="speakerops_active_sync_logical_claim",
            )
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
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REVIEW_STATUS_CHOICES = (
        (PENDING, "Awaiting review"),
        (APPROVED, "Approved"),
        (CHANGES_REQUESTED, "Changes requested"),
    )

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
    version = models.PositiveIntegerField(default=1)
    review_status = models.CharField(max_length=24, choices=REVIEW_STATUS_CHOICES, default=PENDING)
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_reviewed_evidence",
    )

    class Meta:
        ordering = ("-version", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("task", "version"), name="speakerops_task_evidence_version"
            )
        ]


class EvidenceComment(EventOwnedModel):
    """A durable, cross-role discussion attached to one uploaded version."""

    evidence = models.ForeignKey(TaskEvidence, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_evidence_comments",
    )
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("created_at", "pk")


class SessionPublicationApproval(EventOwnedModel):
    """An explicit content-approval gate layered over a released schedule."""

    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    STATUS_CHOICES = (
        (PENDING, "Pending approval"),
        (APPROVED, "Approved for publication"),
        (CHANGES_REQUESTED, "Changes requested"),
    )

    submission = models.OneToOneField(
        "submission.Submission",
        on_delete=models.CASCADE,
        related_name="speakerops_publication_approval",
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=PENDING)
    note = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_publication_reviews",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "submission"),
                name="speakerops_publication_approval_event_submission",
            )
        ]


class ContentRevision(EventOwnedModel):
    """A restorable snapshot of organizer-edited session or speaker content."""

    SESSION = "session"
    SPEAKER = "speaker"
    CONTENT_TYPE_CHOICES = ((SESSION, "Session"), (SPEAKER, "Speaker"))

    content_type = models.CharField(max_length=16, choices=CONTENT_TYPE_CHOICES)
    object_id = models.PositiveBigIntegerField()
    label = models.CharField(max_length=240)
    snapshot = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_content_revisions",
    )
    created_at = models.DateTimeField(default=timezone.now)
    restored_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="restore_events",
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("event", "content_type", "object_id"))]


class ReminderReceipt(EventOwnedModel):
    PENDING = "pending"
    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"
    DELIVERY_CHOICES = (
        (PENDING, "Pending broker handoff"),
        (ACCEPTED, "Broker accepted"),
        (AMBIGUOUS, "Broker outcome ambiguous"),
    )
    task = models.ForeignKey(OnboardingTask, on_delete=models.CASCADE)
    speaker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reminder_key = models.CharField(max_length=160)
    queued_mail_id = models.PositiveBigIntegerField(null=True, blank=True)
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_CHOICES, default=PENDING)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "task", "speaker", "reminder_key"),
                name="speakerops_reminder_dedupe",
            )
        ]


class SpeakerOperationsProfile(EventOwnedModel):
    """Event-owned workflow and logistics data for an event speaker.

    Sourced identity remains on pretalx's User/SpeakerProfile models. These are
    deliberately operator-owned fields and never leak into public widgets.
    """

    INVITED = "invited"
    CONFIRMED = "confirmed"
    ONBOARDING = "onboarding"
    READY = "ready"
    WITHDRAWN = "withdrawn"
    STATUS_CHOICES = (
        (INVITED, "Invited"),
        (CONFIRMED, "Confirmed"),
        (ONBOARDING, "Onboarding"),
        (READY, "Ready"),
        (WITHDRAWN, "Withdrawn"),
    )

    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speakerops_event_profiles",
    )
    social_url = models.URLField(blank=True, default="")
    headshot_original_filename = models.CharField(max_length=255, blank=True, default="")
    headshot_uploaded_at = models.DateTimeField(null=True, blank=True)
    workflow_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=INVITED)
    travel_preferences = models.TextField(blank=True, default="")
    dietary_requirements = models.TextField(blank=True, default="")
    accessibility_requirements = models.TextField(blank=True, default="")
    logistics_notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("speaker__name", "speaker__email")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "speaker"),
                name="speakerops_event_speaker_operations_profile",
            )
        ]


class SpeakerCommunicationLog(EventOwnedModel):
    """Immutable, per-recipient evidence for operator-triggered speaker mail."""

    INVITATION = "invitation"
    BULK_EMAIL = "bulk_email"
    KIND_CHOICES = (
        (INVITATION, "Invitation / onboarding"),
        (BULK_EMAIL, "Selected-speaker email"),
    )
    SENT = "sent"
    FAILED = "failed"
    OUTCOME_CHOICES = ((SENT, "Sent"), (FAILED, "Failed"))

    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="speakerops_communications",
    )
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    subject = models.CharField(max_length=200)
    rendered_body = models.TextField()
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    outcome_detail = models.TextField(blank=True, default="")
    queued_mail_id = models.PositiveBigIntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_communications_sent",
    )
    attempted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-attempted_at", "-pk")
        indexes = [
            models.Index(fields=("event", "speaker", "kind"), name="speakerops_comm_event_speaker")
        ]


class AcceptanceWave(EventOwnedModel):
    """A named program-decision wave, distinct from a reviewer access phase."""

    name = models.CharField(max_length=120)
    decision_at = models.DateTimeField()
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "decision_at")
        constraints = [
            models.UniqueConstraint(fields=("event", "name"), name="speakerops_wave_event_name")
        ]


class ProgramDecision(EventOwnedModel):
    ACCEPT = "accept"
    WAITLIST = "waitlist"
    REJECT = "reject"
    STATUS_CHOICES = (
        (ACCEPT, "Accept"),
        (WAITLIST, "Waitlist"),
        (REJECT, "Reject"),
    )

    submission = models.OneToOneField(
        "submission.Submission",
        on_delete=models.CASCADE,
        related_name="speakerops_program_decision",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    wave = models.ForeignKey(
        AcceptanceWave,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    rationale = models.TextField(blank=True)
    decided_at = models.DateTimeField(default=timezone.now)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_applied_program_decisions",
    )

    class Meta:
        ordering = ("-decided_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("event", "submission"), name="speakerops_decision_event_submission"
            )
        ]


class ConditionalQuestionRule(EventOwnedModel):
    """A persisted CFP visibility rule enforced by both browser and server."""

    name = models.CharField(max_length=160)
    controller_question = models.ForeignKey(
        "submission.Question",
        on_delete=models.PROTECT,
        related_name="speakerops_controlled_rules",
    )
    trigger_option = models.ForeignKey(
        "submission.AnswerOption",
        on_delete=models.PROTECT,
        related_name="speakerops_triggered_rules",
    )
    target_question = models.ForeignKey(
        "submission.Question",
        on_delete=models.PROTECT,
        related_name="speakerops_visibility_rules",
    )
    target_required_on_match = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("event", "name"), name="speakerops_conditional_rule_event_name"
            )
        ]


class ReviewerPool(EventOwnedModel):
    """A named set of reviewers used for deterministic category routing."""

    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    reviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="speakerops_reviewer_pools",
    )

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("event", "slug"), name="speakerops_reviewer_pool_event_slug"
            )
        ]


class ReviewerPoolTrack(EventOwnedModel):
    """An unambiguous event-track to reviewer-pool mapping."""

    pool = models.ForeignKey(
        ReviewerPool,
        on_delete=models.CASCADE,
        related_name="track_mappings",
    )
    track = models.ForeignKey(
        "submission.Track",
        on_delete=models.CASCADE,
        related_name="speakerops_pool_mappings",
    )

    class Meta:
        ordering = ("track__position", "track__name")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "track"), name="speakerops_reviewer_pool_event_track"
            ),
            models.UniqueConstraint(
                fields=("pool", "track"), name="speakerops_reviewer_pool_track"
            ),
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


class ConferenceSeries(PretalxModel):
    """A conference family whose public program history can be imported."""

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=200)
    website = models.URLField()
    source_policy = models.JSONField(default=dict)
    objects = models.Manager()

    class Meta:
        ordering = ("name",)


class ConferenceEdition(PretalxModel):
    series = models.ForeignKey(ConferenceSeries, on_delete=models.CASCADE, related_name="editions")
    external_key = models.CharField(max_length=160)
    name = models.CharField(max_length=240)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=240, blank=True)
    source_url = models.URLField()
    source_updated_at = models.DateTimeField()
    objects = models.Manager()

    class Meta:
        ordering = ("series__name", "date_from", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("series", "external_key"),
                name="speakerops_edition_series_external_key",
            )
        ]


class HistoricalSpeaker(PretalxModel):
    canonical_key = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    biography = models.TextField(blank=True)
    source_url = models.URLField()
    source_updated_at = models.DateTimeField()
    objects = models.Manager()

    class Meta:
        ordering = ("name",)


class HistoricalSourceIdentity(PretalxModel):
    """A source-scoped speaker identity mapped to a canonical speaker."""

    ISOLATED = "isolated"
    VERIFIED = "verified"
    LEGACY_UNVERIFIED = "legacy_unverified"
    NEEDS_REVIEW = "needs_review"
    RESOLUTION_STATUS_CHOICES = (
        (ISOLATED, "Isolated"),
        (VERIFIED, "Verified"),
        (LEGACY_UNVERIFIED, "Legacy unverified"),
        (NEEDS_REVIEW, "Needs review"),
    )

    edition = models.ForeignKey(
        ConferenceEdition, on_delete=models.CASCADE, related_name="source_identities"
    )
    source_key = models.CharField(max_length=240)
    speaker = models.ForeignKey(
        HistoricalSpeaker, on_delete=models.PROTECT, related_name="source_identities"
    )
    display_name = models.CharField(max_length=200)
    source_url = models.URLField()
    source_updated_at = models.DateTimeField()
    resolution_status = models.CharField(
        max_length=24,
        choices=RESOLUTION_STATUS_CHOICES,
        default=ISOLATED,
    )
    active = models.BooleanField(default=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    objects = models.Manager()

    class Meta:
        ordering = ("edition", "display_name", "source_key")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "source_key"),
                name="speakerops_source_identity_edition_key",
            )
        ]
        indexes = [
            models.Index(fields=("edition", "source_key")),
            models.Index(fields=("display_name",)),
        ]


class HistoricalIdentityDecision(PretalxModel):
    """An auditable operator decision about a source identity mapping."""

    LINK = "link"
    SPLIT = "split"
    RELINK = "relink"
    ACTION_CHOICES = (
        (LINK, "Link"),
        (SPLIT, "Split"),
        (RELINK, "Relink"),
    )

    source_identity = models.ForeignKey(
        HistoricalSourceIdentity,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    prior_speaker = models.ForeignKey(
        HistoricalSpeaker,
        on_delete=models.PROTECT,
        related_name="prior_identity_decisions",
    )
    resolved_speaker = models.ForeignKey(
        HistoricalSpeaker,
        on_delete=models.PROTECT,
        related_name="resolved_identity_decisions",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    reason = models.TextField()
    evidence_url = models.URLField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_historical_identity_decisions",
    )
    decided_at = models.DateTimeField(default=timezone.now)
    decision_version = models.PositiveIntegerField(default=1)
    objects = models.Manager()

    class Meta:
        ordering = ("-decided_at", "-decision_version", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("source_identity", "decision_version"),
                name="speakerops_identity_decision_version",
            )
        ]


class SpeakerMemoryProfile(EventOwnedModel):
    """AIE-owned operating context layered over immutable sourced speaker history."""

    speaker = models.ForeignKey(
        HistoricalSpeaker, on_delete=models.CASCADE, related_name="operator_profiles"
    )
    tags = models.JSONField(default=list)
    internal_notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_memory_profiles_updated",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "speaker"), name="speakerops_memory_profile_event_speaker"
            )
        ]


class HistoricalTalk(PretalxModel):
    edition = models.ForeignKey(ConferenceEdition, on_delete=models.CASCADE, related_name="talks")
    external_key = models.CharField(max_length=200)
    title = models.CharField(max_length=300)
    abstract = models.TextField(blank=True)
    session_format = models.CharField(max_length=100, blank=True)
    track = models.CharField(max_length=160, blank=True)
    level = models.CharField(max_length=80, blank=True)
    topics = models.JSONField(default=list)
    recording_url = models.URLField(blank=True)
    source_url = models.URLField()
    source_updated_at = models.DateTimeField()
    field_provenance = models.JSONField(default=dict)
    speakers = models.ManyToManyField(HistoricalSpeaker, related_name="historical_talks")
    objects = models.Manager()

    class Meta:
        ordering = ("edition__date_from", "title")
        constraints = [
            models.UniqueConstraint(
                fields=("edition", "external_key"),
                name="speakerops_talk_edition_external_key",
            )
        ]


class HistoricalSpeakerCredit(PretalxModel):
    """Source-specific evidence that a person appeared on one historical talk."""

    talk = models.ForeignKey(HistoricalTalk, on_delete=models.CASCADE, related_name="credits")
    speaker = models.ForeignKey(HistoricalSpeaker, on_delete=models.CASCADE, related_name="credits")
    source_identity = models.ForeignKey(
        HistoricalSourceIdentity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    name_at_source = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    source_url = models.URLField()
    source_updated_at = models.DateTimeField()
    objects = models.Manager()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("talk", "speaker"), name="speakerops_credit_talk_speaker"
            )
        ]


class CRMContact(PretalxModel):
    """An organiser-owned, mutable contact layered beside sourced history."""

    organiser = models.ForeignKey(
        "event.Organiser", on_delete=models.CASCADE, related_name="speakerops_crm_contacts"
    )
    source_speaker = models.ForeignKey(
        HistoricalSpeaker,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="crm_contacts",
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, default="")
    company = models.CharField(max_length=200, blank=True, default="")
    job_title = models.CharField(max_length=200, blank=True, default="")
    headshot_url = models.URLField(blank=True, default="")
    biography = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    internal_notes = models.TextField(blank=True, default="")
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="merged_contacts",
    )
    objects = models.Manager()

    class Meta:
        ordering = ("name", "email", "pk")
        indexes = [
            models.Index(fields=("organiser", "name")),
            models.Index(fields=("organiser", "email")),
        ]

    @property
    def active(self):
        return self.merged_into_id is None


class CRMSegment(PretalxModel):
    organiser = models.ForeignKey(
        "event.Organiser", on_delete=models.CASCADE, related_name="speakerops_crm_segments"
    )
    name = models.CharField(max_length=160)
    filter_definition = models.JSONField(default=dict, blank=True)
    contacts = models.ManyToManyField(CRMContact, related_name="segments", blank=True)
    objects = models.Manager()

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("organiser", "name"), name="speakerops_crm_segment_organiser_name"
            )
        ]


class CRMPipelineCard(PretalxModel):
    PROSPECT = "prospect"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    INVITED = "invited"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    STAGE_CHOICES = (
        (PROSPECT, "Prospect"),
        (CONTACTED, "Contacted"),
        (INTERESTED, "Interested"),
        (INVITED, "Invited"),
        (CONFIRMED, "Confirmed"),
        (DECLINED, "Declined"),
    )

    organiser = models.ForeignKey(
        "event.Organiser", on_delete=models.CASCADE, related_name="speakerops_crm_cards"
    )
    contact = models.OneToOneField(
        CRMContact, on_delete=models.CASCADE, related_name="pipeline_card"
    )
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=PROSPECT)
    notes = models.TextField(blank=True, default="")
    objects = models.Manager()

    class Meta:
        ordering = ("stage", "contact__name")


class CRMPipelineHistory(PretalxModel):
    card = models.ForeignKey(CRMPipelineCard, on_delete=models.CASCADE, related_name="history")
    from_stage = models.CharField(max_length=20, blank=True, default="")
    to_stage = models.CharField(max_length=20, choices=CRMPipelineCard.STAGE_CHOICES)
    note = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    changed_at = models.DateTimeField(default=timezone.now)
    objects = models.Manager()

    class Meta:
        ordering = ("-changed_at", "-pk")


class CRMEventLink(PretalxModel):
    organiser = models.ForeignKey(
        "event.Organiser", on_delete=models.CASCADE, related_name="speakerops_crm_event_links"
    )
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="event_links")
    event = models.ForeignKey("event.Event", on_delete=models.CASCADE, related_name="crm_contacts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_crm_event_links",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="speakerops_crm_links_added",
    )
    added_at = models.DateTimeField(default=timezone.now)
    objects = models.Manager()

    class Meta:
        ordering = ("-added_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("contact", "event"), name="speakerops_crm_contact_event"
            )
        ]


class CRMOutreachLog(PretalxModel):
    organiser = models.ForeignKey(
        "event.Organiser", on_delete=models.CASCADE, related_name="speakerops_crm_outreach"
    )
    contact = models.ForeignKey(CRMContact, on_delete=models.CASCADE, related_name="outreach")
    event = models.ForeignKey(
        "event.Event", null=True, blank=True, on_delete=models.SET_NULL, related_name="crm_outreach"
    )
    subject = models.CharField(max_length=240)
    rendered_body = models.TextField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    logged_at = models.DateTimeField(default=timezone.now)
    objects = models.Manager()

    class Meta:
        ordering = ("-logged_at", "-pk")


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


class AcceleventsConnection(EventOwnedModel):
    STATUS_CONNECTED = "connected"
    STATUS_CREDENTIAL_BLOCKED = "credential_blocked"
    STATUS_ERROR = "error"
    STATUS_CHOICES = (
        (STATUS_CONNECTED, "Connected"),
        (STATUS_CREDENTIAL_BLOCKED, "Credential blocked"),
        (STATUS_ERROR, "Error"),
    )

    base_url = models.URLField(default="http://mock-accelevents:9000")
    event_url = models.SlugField(max_length=200)
    credential_ref = models.CharField(max_length=200, blank=True)
    auth_header = models.CharField(max_length=40, default="Key")
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default=STATUS_CREDENTIAL_BLOCKED
    )
    last_error = models.TextField(blank=True)
    last_verified = models.DateTimeField(null=True, blank=True)


class FieldMapping(EventOwnedModel):
    local_type = models.CharField(max_length=40)
    mapping = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "local_type"), name="speakerops_mapping_event_type"
            )
        ]


class ExternalIdentity(EventOwnedModel):
    local_type = models.CharField(max_length=40)
    local_id = models.PositiveBigIntegerField()
    external_id = models.CharField(max_length=120)
    request_fingerprint = models.CharField(max_length=64)
    reconciled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "local_type", "local_id"), name="speakerops_external_identity"
            )
        ]


class SyncPreview(EventOwnedModel):
    CREATED = "created"
    EXECUTED = "executed"
    INVALID = "invalid"
    status = models.CharField(max_length=20, default=CREATED)
    fingerprint = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)


class SyncRun(EventOwnedModel):
    PREVIEWED = "previewed"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    status = models.CharField(max_length=20, default=PREVIEWED)
    preview = models.ForeignKey(SyncPreview, on_delete=models.PROTECT, related_name="runs")
    version = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)


class SyncItem(EventOwnedModel):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOOP = "noop"
    RECONCILED = "reconciled"
    action = models.CharField(max_length=20)
    local_type = models.CharField(max_length=40)
    local_id = models.PositiveBigIntegerField()
    payload = models.JSONField(default=dict)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default=PENDING)
    external_id = models.CharField(max_length=120, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    request_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=0)
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="items")


class SyncAttempt(EventOwnedModel):
    item = models.ForeignKey(SyncItem, on_delete=models.CASCADE, related_name="attempt_history")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=20)
    request_id = models.CharField(max_length=120, blank=True)
    response = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)


class ReviewRecommendation(EventOwnedModel):
    """A reviewer's explicit recommendation, separate from chair authority."""

    STRONG_ACCEPT = "strong_accept"
    ACCEPT = "accept"
    HOLD = "hold"
    REJECT = "reject"
    CHOICES = (
        (STRONG_ACCEPT, "Strong accept"),
        (ACCEPT, "Accept"),
        (HOLD, "Discuss"),
        (REJECT, "Reject"),
    )

    submission = models.ForeignKey(
        "submission.Submission",
        on_delete=models.CASCADE,
        related_name="speakerops_recommendations",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speakerops_recommendations",
    )
    recommendation = models.CharField(max_length=24, choices=CHOICES, default=HOLD)
    save_session = models.CharField(max_length=64, blank=True, default="")
    client_revision = models.PositiveIntegerField(default=0)
    save_version = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("event", "submission", "reviewer"),
                name="speakerops_recommendation_event_submission_reviewer",
            )
        ]


class SubmissionPresenterRole(EventOwnedModel):
    """A role label for a user already attached to a native pretalx submission."""

    PRIMARY_AUTHOR = "primary_author"
    CO_AUTHOR = "co_author"
    CO_PRESENTER = "co_presenter"
    ROLE_CHOICES = (
        (PRIMARY_AUTHOR, "Primary author"),
        (CO_AUTHOR, "Co-author"),
        (CO_PRESENTER, "Co-presenter"),
    )

    submission = models.ForeignKey(
        "submission.Submission",
        on_delete=models.CASCADE,
        related_name="speakerops_presenter_roles",
    )
    speaker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speakerops_submission_roles",
    )
    role = models.CharField(max_length=24, choices=ROLE_CHOICES)

    class Meta:
        ordering = ("role", "speaker__name", "speaker__email")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "submission", "speaker"),
                name="speakerops_presenter_role_event_submission_speaker",
            ),
            models.UniqueConstraint(
                fields=("submission",),
                condition=models.Q(role="primary_author"),
                name="speakerops_presenter_role_one_primary",
            ),
        ]

    def clean(self):
        errors = {}
        if self.submission_id and self.event_id != self.submission.event_id:
            errors["submission"] = "Choose a submission from this event."
        if (
            self.submission_id
            and self.speaker_id
            and not self.submission.speakers.filter(pk=self.speaker_id).exists()
        ):
            errors["speaker"] = "Role labels require an attached submission presenter."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class EvaluationRound(EventOwnedModel):
    """An independent, event-scoped review round and its visibility policy."""

    name = models.CharField(max_length=160)
    position = models.PositiveIntegerField(default=0)
    opens_at = models.DateField()
    closes_at = models.DateField()
    blinded = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("position", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("event", "name"), name="speakerops_evaluation_round_event_name"
            )
        ]


class EvaluationCriterion(EventOwnedModel):
    NUMERIC = "numeric"
    DROPDOWN = "dropdown"
    TEXT = "text"
    TYPE_CHOICES = (
        (NUMERIC, "Numeric rating"),
        (DROPDOWN, "Dropdown"),
        (TEXT, "Free text"),
    )

    round = models.ForeignKey(EvaluationRound, on_delete=models.CASCADE, related_name="criteria")
    name = models.CharField(max_length=160)
    field_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    position = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)
    weight = models.DecimalField(max_digits=7, decimal_places=2, default=1)
    minimum = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    maximum = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    options = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("position", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("round", "name"), name="speakerops_evaluation_criterion_round_name"
            )
        ]


class RoundReviewer(EventOwnedModel):
    """Reviewer membership and capacity are scoped to exactly one round."""

    round = models.ForeignKey(
        EvaluationRound, on_delete=models.CASCADE, related_name="reviewer_memberships"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speakerops_round_memberships",
    )
    assignment_limit = models.PositiveIntegerField(default=5)
    last_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("reviewer__name", "reviewer__email")
        constraints = [
            models.UniqueConstraint(
                fields=("round", "reviewer"), name="speakerops_round_reviewer_unique"
            )
        ]


class RoundReviewAssignment(EventOwnedModel):
    ASSIGNED = "assigned"
    COMPLETE = "complete"
    RECUSED = "recused"
    STATUS_CHOICES = (
        (ASSIGNED, "Assigned"),
        (COMPLETE, "Complete"),
        (RECUSED, "Conflict declared"),
    )

    round = models.ForeignKey(EvaluationRound, on_delete=models.CASCADE, related_name="assignments")
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speakerops_round_assignments",
    )
    submission = models.ForeignKey(
        "submission.Submission",
        on_delete=models.CASCADE,
        related_name="speakerops_round_assignments",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=ASSIGNED)
    submitted_at = models.DateTimeField(null=True, blank=True)
    recusal_reason = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("submission__title", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("round", "reviewer", "submission"),
                name="speakerops_round_assignment_unique",
            )
        ]


class EvaluationAnswer(EventOwnedModel):
    assignment = models.ForeignKey(
        RoundReviewAssignment, on_delete=models.CASCADE, related_name="answers"
    )
    criterion = models.ForeignKey(
        EvaluationCriterion, on_delete=models.CASCADE, related_name="answers"
    )
    numeric_value = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    choice_value = models.CharField(max_length=160, blank=True, default="")
    text_value = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("criterion__position", "criterion_id")
        constraints = [
            models.UniqueConstraint(
                fields=("assignment", "criterion"),
                name="speakerops_evaluation_answer_assignment_criterion",
            )
        ]
