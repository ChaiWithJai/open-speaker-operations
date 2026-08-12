"""Durable, logical-record claims shared by every synchronization entry point."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import SyncWriteClaim


class SyncClaimBlocked(RuntimeError):
    def __init__(self, claim):
        self.claim = claim
        super().__init__(f"Sync write already claimed for {claim.local_type}:{claim.local_id}")


def acquire_sync_claim(item, actor, receipt=None):
    try:
        with transaction.atomic():
            return SyncWriteClaim.objects.create(
                event=item.event,
                local_type=item.local_type,
                local_id=item.local_id,
                actor=actor,
                receipt=receipt,
                item=item,
            )
    except IntegrityError:
        claim = SyncWriteClaim.objects.filter(
            event=item.event,
            local_type=item.local_type,
            local_id=item.local_id,
            active=True,
        ).first()
        if claim is None:
            raise
        raise SyncClaimBlocked(claim) from None


def release_sync_claim(claim, resolution="known_outcome"):
    SyncWriteClaim.objects.filter(pk=claim.pk, active=True).update(
        active=False,
        resolved_at=timezone.now(),
        resolution=resolution,
    )


def mark_sync_claim_ambiguous(claim):
    SyncWriteClaim.objects.filter(pk=claim.pk, active=True).update(
        status=SyncWriteClaim.AMBIGUOUS,
        resolution="connector_outcome_unknown",
    )
