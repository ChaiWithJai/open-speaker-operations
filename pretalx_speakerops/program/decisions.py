from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..cfp import validate_aie_submission_policy
from ..models import ProgramDecision


@transaction.atomic
def stage_program_decision(submission, status, actor, wave=None, rationale=""):
    """Stage a chair decision without sending mail or changing native state."""
    if status not in dict(ProgramDecision.STATUS_CHOICES):
        raise ValidationError("Choose accept, waitlist, or reject.")
    if status == ProgramDecision.ACCEPT:
        if wave is None:
            raise ValidationError("Choose an acceptance wave before staging acceptance.")
        if wave.event_id != submission.event_id:
            raise ValidationError("The acceptance wave belongs to another event.")
        validate_aie_submission_policy(submission)
    elif wave is not None:
        raise ValidationError("Only accepted proposals are assigned to an acceptance wave.")
    applied = ProgramDecision.objects.filter(event=submission.event, submission=submission).first()
    if applied and applied.applied_at:
        raise ValidationError(
            "This program decision has already been applied. Use the native proposal audit "
            "workflow for a deliberate reversal."
        )
    decision, _ = ProgramDecision.objects.update_or_create(
        event=submission.event,
        submission=submission,
        defaults={
            "status": status,
            "wave": wave,
            "decided_by": actor,
            "rationale": rationale.strip(),
            "decided_at": timezone.now(),
        },
    )
    return decision


@transaction.atomic
def release_acceptance_wave(wave, actor):
    """Apply a staged wave to pretalx only after an explicit operator action."""
    decisions = list(
        wave.decisions.select_for_update()
        .filter(status=ProgramDecision.ACCEPT, applied_at__isnull=True)
        .select_related("submission")
    )
    released = 0
    for decision in decisions:
        submission = decision.submission
        validate_aie_submission_policy(submission)
        if submission.state != "accepted":
            submission.accept(person=actor, force=True)
            released += 1
        decision.applied_at = timezone.now()
        decision.applied_by = actor
        decision.save(update_fields=["applied_at", "applied_by", "updated"])
    return released


@transaction.atomic
def finalize_rejections(event, actor):
    """Apply staged rejections only after a separate explicit confirmation."""
    decisions = list(
        ProgramDecision.objects.select_for_update()
        .filter(event=event, status=ProgramDecision.REJECT, applied_at__isnull=True)
        .select_related("submission")
    )
    finalized = 0
    for decision in decisions:
        if decision.submission.state != "rejected":
            decision.submission.reject(person=actor, force=True)
            finalized += 1
        decision.applied_at = timezone.now()
        decision.applied_by = actor
        decision.save(update_fields=["applied_at", "applied_by", "updated"])
    return finalized
