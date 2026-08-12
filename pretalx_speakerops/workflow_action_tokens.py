"""Opaque, short-lived action snapshots stored in the shared Redis cache."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

ACTION_SNAPSHOT_TTL_SECONDS = 15 * 60
ACTION_BATCH_LIMIT = 25
_KEY_PREFIX = "speakerops:workflow-action:v1:"


@dataclass(frozen=True)
class ActionSnapshot:
    nonce: uuid.UUID
    event_slug: str
    workflow: str
    correlation_id: uuid.UUID
    target_ids: list[int]
    requesting_principal: str
    claimed_channel_id: str
    claimed_trigger_event_id: str
    expires_at: object


def _require_shared_cache():
    configured_backend = settings.CACHES.get("default", {}).get("BACKEND", "").casefold()
    test_runtime = "locmem" in configured_backend
    if "redis" not in configured_backend and not test_runtime:
        raise RuntimeError("workflow action previews require the configured shared Redis cache")


def _key(nonce):
    return f"{_KEY_PREFIX}{nonce}"


def create_action_snapshot(
    *,
    event,
    workflow,
    correlation_id,
    target_ids,
    principal,
    claimed_channel_id="",
    claimed_trigger_event_id="",
):
    _require_shared_cache()
    normalized_ids = sorted({int(value) for value in target_ids})
    if len(normalized_ids) > ACTION_BATCH_LIMIT:
        raise ValueError(f"action snapshot exceeds the {ACTION_BATCH_LIMIT}-target safety cap")
    nonce = uuid.uuid4()
    expires_at = timezone.now() + timedelta(seconds=ACTION_SNAPSHOT_TTL_SECONDS)
    payload = {
        "event_slug": event.slug,
        "workflow": workflow,
        "correlation_id": str(correlation_id),
        "target_ids": normalized_ids,
        "requesting_principal": str(principal)[:160],
        "claimed_channel_id": str(claimed_channel_id)[:200],
        "claimed_trigger_event_id": str(claimed_trigger_event_id)[:200],
        "expires_at": expires_at.isoformat(),
    }
    if not cache.add(_key(nonce), payload, timeout=ACTION_SNAPSHOT_TTL_SECONDS):
        raise RuntimeError("could not allocate an opaque action preview")
    return ActionSnapshot(
        nonce=nonce,
        expires_at=expires_at,
        **{key: value for key, value in payload.items() if key != "expires_at"},
    )


def load_action_snapshot(*, nonce, event_slug, workflow, correlation_id):
    _require_shared_cache()
    payload = cache.get(_key(nonce))
    if not payload or (
        payload.get("event_slug") != event_slug
        or payload.get("workflow") != workflow
        or payload.get("correlation_id") != str(correlation_id)
    ):
        return None
    expires_at = timezone.datetime.fromisoformat(payload["expires_at"])
    if expires_at <= timezone.now():
        cache.delete(_key(nonce))
        return None
    return ActionSnapshot(
        nonce=uuid.UUID(str(nonce)),
        expires_at=expires_at,
        **{key: value for key, value in payload.items() if key != "expires_at"},
    )


def consume_action_snapshot(nonce):
    try:
        cache.delete(_key(nonce))
    except Exception:
        # Consumption is replay hygiene, not the write's source of idempotency.
        # Durable receipts and claims remain authoritative if Redis is degraded.
        return False
    return True
