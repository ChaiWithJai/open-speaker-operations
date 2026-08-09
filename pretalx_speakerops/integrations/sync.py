import hashlib
import json
import logging
from datetime import datetime, timezone

from django.db import transaction
from pretalx.person.models import User
from pretalx.submission.models import Submission

from ..domain.commands import Command, execute
from ..domain.state import StateMachine, Transition
from ..models import (
    AcceleventsConnection,
    ExternalIdentity,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
)
from .accelevents import AcceleventsClient, AcceleventsError

log = logging.getLogger(__name__)

SYNC_ITEM_MACHINE = StateMachine(
    states=frozenset(
        {
            SyncItem.PENDING,
            SyncItem.RUNNING,
            SyncItem.SUCCEEDED,
            SyncItem.FAILED,
            SyncItem.NOOP,
            SyncItem.RECONCILED,
        }
    ),
    transitions=(
        Transition(SyncItem.PENDING, SyncItem.RUNNING),
        Transition(SyncItem.PENDING, SyncItem.NOOP),
        Transition(SyncItem.RUNNING, SyncItem.SUCCEEDED),
        Transition(SyncItem.RUNNING, SyncItem.FAILED),
        Transition(SyncItem.RUNNING, SyncItem.RECONCILED),
        Transition(SyncItem.FAILED, SyncItem.RUNNING),
    ),
)
SYNC_RUN_MACHINE = StateMachine(
    states=frozenset(
        {
            SyncRun.PREVIEWED,
            SyncRun.RUNNING,
            SyncRun.PARTIAL,
            SyncRun.SUCCEEDED,
            SyncRun.FAILED,
        }
    ),
    transitions=(
        Transition(SyncRun.PREVIEWED, SyncRun.RUNNING),
        Transition(SyncRun.RUNNING, SyncRun.PARTIAL),
        Transition(SyncRun.RUNNING, SyncRun.SUCCEEDED),
        Transition(SyncRun.RUNNING, SyncRun.FAILED),
        Transition(SyncRun.PARTIAL, SyncRun.RUNNING),
        Transition(SyncRun.PARTIAL, SyncRun.SUCCEEDED),
    ),
)


def fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def client_for(event):
    connection = AcceleventsConnection.objects.get(event=event)
    if not connection.credential_ref:
        raise AcceleventsError("Accelevents credential is unavailable")
    return AcceleventsClient(
        connection.base_url,
        connection.event_url,
        connection.credential_ref,
        auth_header=connection.auth_header,
    )


def preview(event, payloads):
    items = []
    for local_type, local_id, payload in payloads:
        digest = fingerprint(payload)
        identity = ExternalIdentity.objects.filter(
            event=event, local_type=local_type, local_id=local_id
        ).first()
        if not identity:
            action = "create"
        elif identity.request_fingerprint == digest:
            action = "noop"
        else:
            action = "update"
        items.append(
            {
                "local_type": local_type,
                "local_id": local_id,
                "payload": payload,
                "fingerprint": digest,
                "action": action,
                "external_id": identity.external_id if identity else "",
            }
        )
    body = {"items": items}
    run = SyncPreview.objects.create(
        event=event, status=SyncPreview.CREATED, fingerprint=fingerprint(body), payload=body
    )
    return run


def execute_preview(event, preview_id, actor, payloads=None, execute_now=True):
    with transaction.atomic():
        preview_run = SyncPreview.objects.select_for_update().get(pk=preview_id, event=event)
        current_payload = [
            {
                **item,
                "payload": _live_payload(event, item) or item["payload"],
                "fingerprint": fingerprint(_live_payload(event, item) or item["payload"]),
            }
            for item in preview_run.payload["items"]
        ]
        current = fingerprint({"items": current_payload})
        if current != preview_run.fingerprint:
            preview_run.status = SyncPreview.INVALID
            preview_run.save(update_fields=["status"])
            raise ValueError("Preview is stale; compute a new preview.")
        run = SyncRun.objects.create(event=event, preview=preview_run, status=SyncRun.PREVIEWED)
        for item in preview_run.payload["items"]:
            SyncItem.objects.create(
                event=event,
                run=run,
                action=item["action"],
                local_type=item["local_type"],
                local_id=item["local_id"],
                payload=item["payload"],
                request_fingerprint=item["fingerprint"],
                external_id=item.get("external_id", ""),
            )
        preview_run.status = SyncPreview.EXECUTED
        preview_run.save(update_fields=["status"])
        execute(
            Command(
                event=event,
                aggregate_model=SyncRun,
                aggregate_id=run.pk,
                action="sync.run",
                target_state=SyncRun.RUNNING,
                state_machine=SYNC_RUN_MACHINE,
            ),
            actor,
            key=f"sync-run:{run.pk}:start",
            expected_version=run.version,
        )
    if execute_now:
        items = list(run.items.order_by("pk"))
        if not items:
            _refresh_run_status(run, actor)
        else:
            for item in items:
                execute_item(item, actor)
        run.refresh_from_db()
    return run


def _refresh_run_status(run, actor):
    statuses = set(run.items.values_list("status", flat=True))
    if statuses & {SyncItem.PENDING, SyncItem.RUNNING}:
        target = SyncRun.RUNNING
    elif SyncItem.FAILED in statuses:
        target = SyncRun.PARTIAL
    else:
        target = SyncRun.SUCCEEDED
    run.refresh_from_db()
    if run.status == target:
        return run
    execute(
        Command(
            event=run.event,
            aggregate_model=SyncRun,
            aggregate_id=run.pk,
            action="sync.run.status",
            target_state=target,
            state_machine=SYNC_RUN_MACHINE,
        ),
        actor,
        key=f"sync-run:{run.pk}:status:{target}:{run.version + 1}",
        expected_version=run.version,
    )
    return run


def _reconcile_speaker(client, payload):
    matches = [
        item
        for item in client.speakers_with_sessions()
        if item.get("email") == payload.get("email")
    ]
    if len(matches) == 1:
        return str(matches[0]["id"])
    raise AcceleventsError("Unable to reconcile duplicate speaker", code=4068906)


def _live_payload(event, item):
    if item["local_type"] == "speaker":
        speaker = User.objects.filter(pk=item["local_id"]).first()
        if speaker:
            first_name, _, last_name = (speaker.name or "Demo Speaker").partition(" ")
            return {
                "firstName": first_name,
                "lastName": last_name or first_name,
                "email": speaker.email,
            }
    if item["local_type"] == "session":
        submission = Submission.objects.filter(pk=item["local_id"], event=event).first()
        if submission:
            return {"title": submission.title}
    return None


def execute_item(item, actor):
    client = client_for(item.event)
    if item.action == "noop":
        execute(
            Command(
                event=item.event,
                aggregate_model=SyncItem,
                aggregate_id=item.pk,
                action="sync.noop",
                target_state=SyncItem.NOOP,
                state_machine=SYNC_ITEM_MACHINE,
            ),
            actor,
            key=f"sync-item:{item.pk}:noop",
            expected_version=item.version,
        )
        _refresh_run_status(item.run, actor)
        return item
    attempt = SyncAttempt.objects.create(
        event=item.event, item=item, number=item.attempts + 1, status="running"
    )
    attempt_number = item.attempts + 1
    execute(
        Command(
            event=item.event,
            aggregate_model=SyncItem,
            aggregate_id=item.pk,
            action="sync.start",
            target_state=SyncItem.RUNNING,
            state_machine=SYNC_ITEM_MACHINE,
        ),
        actor,
        key=f"sync-item:{item.pk}:attempt:{attempt.pk}",
        expected_version=item.version,
    )
    item.refresh_from_db()
    item.attempts = attempt_number
    item.error = ""
    try:
        if item.local_type == "speaker":
            if item.action == "update":
                external_id = item.external_id
                client.update_speaker(external_id, item.payload)
            else:
                external_id = client.create_speaker(item.payload)
        else:
            if item.action == "update":
                external_id = item.external_id
                client.update_session(external_id, item.payload)
            else:
                external_id = client.create_session(item.payload)
        attempt.request_id = client.last_request_id
        next_status = SyncItem.SUCCEEDED
        item.external_id = str(external_id)
    except AcceleventsError as error:
        if error.code == 4068906 and item.local_type == "speaker":
            next_status = SyncItem.RECONCILED
            item.external_id = _reconcile_speaker(client, item.payload)
        else:
            next_status = SyncItem.FAILED
            item.error = str(error)
        log.warning(
            "accelevents sync item failed/reconciled",
            extra={"run_id": item.run_id, "item_id": item.id},
        )
        attempt.request_id = client.last_request_id
        attempt.error = str(error)
    execute(
        Command(
            event=item.event,
            aggregate_model=SyncItem,
            aggregate_id=item.pk,
            action=f"sync.{next_status}",
            target_state=next_status,
            state_machine=SYNC_ITEM_MACHINE,
        ),
        actor,
        key=f"sync-item:{item.pk}:finish:{attempt.pk}",
        expected_version=item.version,
    )
    item.refresh_from_db()
    item.attempts = attempt_number
    attempt.status = (
        "succeeded" if item.status in {SyncItem.SUCCEEDED, SyncItem.RECONCILED} else "failed"
    )
    attempt.response = {"external_id": item.external_id}
    attempt.finished_at = datetime.now(timezone.utc)
    attempt.save(
        update_fields=[
            "status",
            "request_id",
            "response",
            "error",
            "finished_at",
            "updated",
        ]
    )
    item.save(update_fields=["attempts", "external_id", "status", "error", "updated"])
    if item.status in {SyncItem.SUCCEEDED, SyncItem.RECONCILED}:
        ExternalIdentity.objects.update_or_create(
            event=item.event,
            local_type=item.local_type,
            local_id=item.local_id,
            defaults={
                "external_id": item.external_id,
                "request_fingerprint": item.request_fingerprint,
                "reconciled": item.status == SyncItem.RECONCILED,
            },
        )
    _refresh_run_status(item.run, actor)
    return item
