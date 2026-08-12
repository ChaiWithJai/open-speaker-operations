import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from django_scopes import scope

from pretalx_speakerops.integrations.buzz.operations_reads import (
    sync_recovery,
    workflow_action_receipts,
)
from pretalx_speakerops.integrations.buzz.speaker_reads import speaker_nudges
from pretalx_speakerops.models import (
    OnboardingTask,
    ReminderReceipt,
    SyncItem,
    SyncPreview,
    SyncRun,
    SyncWriteClaim,
    WorkflowActionReceipt,
)
from pretalx_speakerops.workflow_action_tokens import ACTION_BATCH_LIMIT, create_action_snapshot


@pytest.fixture(autouse=True)
def shared_action_cache():
    with override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    ):
        yield


def _snapshot(event, workflow, correlation, target_ids, trigger="event-456"):
    return create_action_snapshot(
        event=event,
        workflow=workflow,
        correlation_id=correlation,
        target_ids=target_ids,
        principal="buzz-operator",
        claimed_channel_id="channel-123",
        claimed_trigger_event_id=trigger,
    )


def _enable_and_make_overdue(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            event=event,
            submission=submission,
            speaker=users["speaker"],
            status=OnboardingTask.PENDING,
        ).first()
        task.due_date = timezone.localdate() - timedelta(days=1)
        task.save(update_fields=["due_date", "updated"])
        return task


@pytest.mark.django_db(transaction=True)
def test_speaker_nudge_preview_requires_chair_confirmation_and_receipts_once(event, users, client):
    task = _enable_and_make_overdue(event, users)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SPEAKER_NUDGES, correlation, [task.pk])
    preview_url = f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/{correlation}/"
    preview_url = f"{preview_url}{snapshot.nonce}/"
    confirm_url = f"{preview_url}confirm/"

    client.force_login(users["speaker"])
    assert client.get(preview_url).status_code == 404
    client.force_login(users["chair"])
    preview = client.get(preview_url)
    assert preview.status_code == 200
    assert list(preview.context["targets"]) == [task]
    with scope(event=event):
        assert not WorkflowActionReceipt.objects.exists()

    missing_confirmation = client.post(confirm_url, {"targets": [task.pk]})
    assert missing_confirmation.status_code == 302
    with scope(event=event):
        assert not WorkflowActionReceipt.objects.exists()

    confirmed = client.post(
        confirm_url,
        {"targets": [task.pk], "confirm_action": "yes"},
    )
    assert confirmed.status_code == 302
    with scope(event=event):
        receipt = WorkflowActionReceipt.objects.get(correlation_id=correlation)
        assert receipt.workflow == WorkflowActionReceipt.SPEAKER_NUDGES
        assert receipt.actor == users["chair"]
        assert receipt.requesting_principal == "buzz-operator"
        assert receipt.claimed_channel_id == "channel-123"
        assert receipt.claimed_trigger_event_id == "event-456"
        assert receipt.status == WorkflowActionReceipt.SUCCEEDED
        assert receipt.target_count == 1
        assert receipt.result == {
            "outcome": "queued",
            "eligible_count": 1,
            "queued_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "ambiguous_count": 0,
            "not_attempted_count": 0,
            "noop_count": 0,
            "task_ids": [task.pk],
            "attempted_task_ids": [task.pk],
            "reminder_receipt_ids": [ReminderReceipt.objects.get(task=task).pk],
        }
        assert "email" not in str(receipt.result).lower()

    replay = client.post(
        confirm_url,
        {"targets": [task.pk], "confirm_action": "yes"},
    )
    assert replay.status_code == 302
    with scope(event=event):
        assert WorkflowActionReceipt.objects.filter(correlation_id=correlation).count() == 1
        assert ReminderReceipt.objects.filter(task=task).count() == 1

    tampered_correlation = uuid.uuid4()
    tampered_url = (
        f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/"
        f"{tampered_correlation}/{snapshot.nonce}/"
    )
    assert client.get(tampered_url).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_speaker_nudge_confirmation_locks_only_task_row(event, users, client):
    """PostgreSQL must not try to lock nullable select_related joins."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific row-lock regression")
    task = _enable_and_make_overdue(event, users)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SPEAKER_NUDGES, correlation, [task.pk])
    confirm_url = (
        f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/"
        f"{correlation}/{snapshot.nonce}/confirm/"
    )
    client.force_login(users["chair"])

    response = client.post(
        confirm_url,
        {"targets": [task.pk], "confirm_action": "yes"},
    )

    assert response.status_code == 302
    with scope(event=event):
        assert WorkflowActionReceipt.objects.get(correlation_id=correlation).status == (
            WorkflowActionReceipt.SUCCEEDED
        )

def _sync_items(event):
    preview = SyncPreview.objects.create(
        event=event,
        status=SyncPreview.EXECUTED,
        fingerprint="a" * 64,
        payload={"items": []},
    )
    run = SyncRun.objects.create(event=event, preview=preview, status=SyncRun.PARTIAL)
    failed = SyncItem.objects.create(
        event=event,
        run=run,
        action="update",
        local_type="session",
        local_id=901,
        payload={"title": "Private payload"},
        request_fingerprint="b" * 64,
        status=SyncItem.FAILED,
        error="private upstream response",
    )
    succeeded = SyncItem.objects.create(
        event=event,
        run=run,
        action="update",
        local_type="session",
        local_id=902,
        payload={"title": "Already done"},
        request_fingerprint="c" * 64,
        status=SyncItem.SUCCEEDED,
    )
    return failed, succeeded


@pytest.mark.django_db(transaction=True)
def test_sync_preview_revalidates_failed_items_and_records_sanitized_receipt(
    event, users, client, monkeypatch
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        failed, succeeded = _sync_items(event)

    called = []

    def fake_execute(item, actor, workflow_receipt=None):
        assert workflow_receipt is not None
        called.append((item.pk, actor.pk))
        item.status = SyncItem.SUCCEEDED
        item.attempts += 1
        item.save(update_fields=["status", "attempts", "updated"])
        return item

    monkeypatch.setattr("pretalx_speakerops.workflow_actions.execute_item", fake_execute)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SYNC_RECOVERY, correlation, [failed.pk])
    preview_url = f"/orga/{event.slug}/speaker-operations/actions/sync-recovery/{correlation}/"
    preview_url = f"{preview_url}{snapshot.nonce}/"
    client.force_login(users["chair"])
    preview = client.get(preview_url)
    assert preview.status_code == 200
    assert [row.pk for row in preview.context["targets"]] == [failed.pk]

    tampered = client.post(
        f"{preview_url}confirm/",
        {
            "targets": [failed.pk, succeeded.pk],
            "confirm_action": "yes",
        },
    )
    assert tampered.status_code == 302
    assert called == []
    with scope(event=event):
        assert not WorkflowActionReceipt.objects.filter(correlation_id=correlation).exists()

        failed.status = SyncItem.SUCCEEDED
        failed.save(update_fields=["status", "updated"])
    stale = client.post(
        f"{preview_url}confirm/",
        {"targets": [failed.pk], "confirm_action": "yes"},
    )
    assert stale.status_code == 302
    assert called == []
    with scope(event=event):
        assert not WorkflowActionReceipt.objects.filter(correlation_id=correlation).exists()
        failed.status = SyncItem.FAILED
        failed.save(update_fields=["status", "updated"])

    response = client.post(
        f"{preview_url}confirm/",
        {"targets": [failed.pk], "confirm_action": "yes"},
    )
    assert response.status_code == 302
    assert called == [(failed.pk, users["chair"].pk)]
    with scope(event=event):
        receipt = WorkflowActionReceipt.objects.get(correlation_id=correlation)
        assert receipt.workflow == WorkflowActionReceipt.SYNC_RECOVERY
        assert receipt.status == WorkflowActionReceipt.SUCCEEDED
        assert receipt.result == {
            "outcome": "retry_completed",
            "eligible_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "ambiguous_count": 0,
            "not_attempted_count": 0,
            "sync_item_ids": [failed.pk],
            "attempted_item_ids": [failed.pk],
            "ambiguous_item_id": None,
        }
        succeeded.refresh_from_db()
        assert succeeded.attempts == 0

    second_correlation = uuid.uuid4()
    second_snapshot = _snapshot(
        event,
        WorkflowActionReceipt.SYNC_RECOVERY,
        second_correlation,
        [failed.pk],
        trigger="event-789",
    )
    second_url = (
        f"/orga/{event.slug}/speaker-operations/actions/sync-recovery/"
        f"{second_correlation}/{second_snapshot.nonce}/confirm/"
    )
    assert (
        client.post(second_url, {"targets": [failed.pk], "confirm_action": "yes"}).status_code
        == 302
    )
    assert called == [(failed.pk, users["chair"].pk)]
    with scope(event=event):
        assert not WorkflowActionReceipt.objects.filter(correlation_id=second_correlation).exists()


@pytest.mark.django_db(transaction=True)
def test_receipt_read_is_allowlisted_role_safe_and_links_exact_record(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        receipt = WorkflowActionReceipt.objects.create(
            event=event,
            workflow=WorkflowActionReceipt.SYNC_RECOVERY,
            action="retry_failed_sync_items",
            correlation_id=uuid.uuid4(),
            requesting_principal="buzz-operator",
            claimed_channel_id="channel-123",
            claimed_trigger_event_id="event-456",
            status=WorkflowActionReceipt.FAILED,
            actor=users["chair"],
            completed_at=timezone.now(),
            target_count=1,
            result={
                "outcome": "retry_failed",
                "eligible_count": 1,
                "completed_count": 0,
                "failed_count": 1,
                "sync_item_ids": [42],
                "final_status_counts": {"failed": 1},
                "credential_ref": "sk-do-not-leak",
                "response": {"email": "private@example.org"},
            },
        )
        WorkflowActionReceipt.objects.create(
            event=event,
            workflow=WorkflowActionReceipt.SPEAKER_NUDGES,
            action="queue_overdue_reminders",
            correlation_id=uuid.uuid4(),
            requesting_principal="another-agent",
            status=WorkflowActionReceipt.SUCCEEDED,
            actor=users["chair"],
            completed_at=timezone.now(),
            result={"outcome": "queued"},
        )

    result = workflow_action_receipts(
        event.slug,
        receipt.correlation_id,
        "https://speakerops.example",
        requesting_principal="buzz-operator",
    )
    serialized = str(result)
    assert result["read_only"] is True
    assert result["receipt"]["correlation_id"] == str(receipt.correlation_id)
    assert result["receipt"]["receipt_link"] == (
        f"https://speakerops.example/go/workflow-action-receipt/{event.slug}~{receipt.pk}/"
    )
    assert "sk-do-not-leak" not in serialized
    assert "private@example.org" not in serialized
    assert "credential_ref" not in serialized

    url = f"/orga/{event.slug}/speaker-operations/action-receipts/{receipt.pk}/"
    client.force_login(users["speaker"])
    assert client.get(url).status_code == 404
    client.force_login(users["chair"])
    assert client.get(url).status_code == 200


@pytest.mark.django_db(transaction=True)
def test_expired_action_snapshot_is_rejected(event, users, client):
    task = _enable_and_make_overdue(event, users)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SPEAKER_NUDGES, correlation, [task.pk])
    cache.delete(f"speakerops:workflow-action:v1:{snapshot.nonce}")
    client.force_login(users["chair"])
    url = (
        f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/"
        f"{correlation}/{snapshot.nonce}/"
    )
    assert client.get(url).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_unexpected_sync_exception_is_ambiguous_and_stops_batch(event, users, client, monkeypatch):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        first, second = _sync_items(event)
        second.status = SyncItem.FAILED
        second.save(update_fields=["status", "updated"])

    called = []

    def ambiguous_execute(item, actor, workflow_receipt=None):
        assert workflow_receipt is not None
        called.append(item.pk)
        raise RuntimeError("connection lost after write")

    monkeypatch.setattr("pretalx_speakerops.workflow_actions.execute_item", ambiguous_execute)
    correlation = uuid.uuid4()
    target_ids = sorted([first.pk, second.pk])
    snapshot = _snapshot(event, WorkflowActionReceipt.SYNC_RECOVERY, correlation, target_ids)
    url = (
        f"/orga/{event.slug}/speaker-operations/actions/sync-recovery/"
        f"{correlation}/{snapshot.nonce}/confirm/"
    )
    client.force_login(users["chair"])
    response = client.post(url, {"targets": target_ids, "confirm_action": "yes"})

    assert response.status_code == 302
    assert called == [target_ids[0]], "ambiguous failure must stop the remaining batch"
    with scope(event=event):
        receipt = WorkflowActionReceipt.objects.get(correlation_id=correlation)
        assert receipt.status == WorkflowActionReceipt.AMBIGUOUS
        assert receipt.result["outcome"] == "retry_outcome_ambiguous"
        assert receipt.result["ambiguous_count"] == 1
        assert receipt.result["completed_count"] == 0
        assert receipt.result["failed_count"] == 0
        assert receipt.result["not_attempted_count"] == 1


@pytest.mark.django_db(transaction=True)
def test_reads_create_only_ephemeral_cache_snapshots_and_short_opaque_urls(event, users):
    _enable_and_make_overdue(event, users)
    with scope(event=event):
        before = (
            WorkflowActionReceipt.objects.count(),
            SyncWriteClaim.objects.count(),
        )
        nudge = speaker_nudges(
            event.slug,
            requesting_principal="buzz-operator",
            claimed_channel_id="synthetic-channel",
            claimed_trigger_event_id="synthetic-trigger",
        )
        sync = sync_recovery(
            event.slug,
            requesting_principal="buzz-operator",
            claimed_channel_id="synthetic-channel",
            claimed_trigger_event_id="synthetic-trigger",
        )
        after = (
            WorkflowActionReceipt.objects.count(),
            SyncWriteClaim.objects.count(),
        )
    assert after == before
    for url in (
        nudge["action_preview"]["confirmation_url"],
        sync["retry_preview"]["confirmation_url"],
    ):
        assert len(url) < 220
        assert "target_ids" not in url and "principal" not in url


@pytest.mark.django_db(transaction=True)
def test_sync_read_ignores_old_failed_row_when_newer_logical_row_succeeded(event):
    with scope(event=event):
        old_failed, _ = _sync_items(event)
        SyncItem.objects.create(
            event=event,
            run=old_failed.run,
            action=old_failed.action,
            local_type=old_failed.local_type,
            local_id=old_failed.local_id,
            payload={},
            request_fingerprint="d" * 64,
            status=SyncItem.SUCCEEDED,
        )
    result = sync_recovery(event.slug)
    assert old_failed.pk not in result["retry_preview"]["eligible_item_ids"]


@pytest.mark.django_db(transaction=True)
def test_snapshot_batch_cap_and_exact_principal_scoped_receipt(event, users):
    with pytest.raises(ValueError, match="safety cap"):
        _snapshot(
            event,
            WorkflowActionReceipt.SYNC_RECOVERY,
            uuid.uuid4(),
            range(1, ACTION_BATCH_LIMIT + 2),
        )
    with scope(event=event):
        receipt = WorkflowActionReceipt.objects.create(
            event=event,
            workflow=WorkflowActionReceipt.SYNC_RECOVERY,
            action="retry_failed_sync_items",
            correlation_id=uuid.uuid4(),
            requesting_principal="buzz-operator",
            status=WorkflowActionReceipt.SUCCEEDED,
            actor=users["chair"],
            result={"outcome": "retry_completed"},
        )
    assert (
        workflow_action_receipts(
            event.slug, receipt.correlation_id, requesting_principal="buzz-operator"
        )["receipt"]["receipt_id"]
        == receipt.pk
    )
    with pytest.raises(KeyError):
        workflow_action_receipts(
            event.slug,
            receipt.correlation_id,
            requesting_principal="another-agent",
        )


@pytest.mark.django_db(transaction=True)
def test_reminder_broker_exception_leaves_committed_ambiguous_receipt(
    event, users, client, monkeypatch
):
    task = _enable_and_make_overdue(event, users)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SPEAKER_NUDGES, correlation, [task.pk])

    def unknown_acceptance(*args, **kwargs):
        assert WorkflowActionReceipt.objects.filter(
            event=event, correlation_id=correlation, status=WorkflowActionReceipt.PENDING
        ).exists(), "claim must be committed before broker I/O"
        raise RuntimeError("connection lost after broker acceptance")

    monkeypatch.setattr(
        "pretalx_speakerops.workflow_actions.queue_reminder_task", unknown_acceptance
    )
    client.force_login(users["chair"])
    url = (
        f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/"
        f"{correlation}/{snapshot.nonce}/confirm/"
    )
    assert client.post(url, {"targets": [task.pk], "confirm_action": "yes"}).status_code == 302
    with scope(event=event):
        receipt = WorkflowActionReceipt.objects.get(correlation_id=correlation)
        assert receipt.status == WorkflowActionReceipt.AMBIGUOUS
        assert receipt.result["outcome"] == "queue_outcome_ambiguous"
        assert receipt.result["ambiguous_count"] == 1
        assert receipt.result["failed_count"] == 0


@pytest.mark.django_db(transaction=True)
def test_typed_reads_survive_cache_failure_without_database_mutation(event, users, monkeypatch):
    _enable_and_make_overdue(event, users)
    with scope(event=event):
        before = (
            WorkflowActionReceipt.objects.count(),
            SyncWriteClaim.objects.count(),
            ReminderReceipt.objects.count(),
        )

    def cache_unavailable(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "pretalx_speakerops.integrations.buzz.speaker_reads.create_action_snapshot",
        cache_unavailable,
    )
    monkeypatch.setattr(
        "pretalx_speakerops.integrations.buzz.operations_reads.create_action_snapshot",
        cache_unavailable,
    )
    nudge = speaker_nudges(event.slug)
    sync = sync_recovery(event.slug)

    assert nudge["action_preview"]["available"] is False
    assert nudge["action_preview"]["confirmation_url"] is None
    assert sync["retry_preview"]["available"] is False
    assert sync["retry_preview"]["confirmation_url"] is None
    with scope(event=event):
        after = (
            WorkflowActionReceipt.objects.count(),
            SyncWriteClaim.objects.count(),
            ReminderReceipt.objects.count(),
        )
    assert after == before


@pytest.mark.django_db(transaction=True)
def test_cache_delete_failure_does_not_block_confirmed_idempotent_action(
    event, users, client, monkeypatch
):
    task = _enable_and_make_overdue(event, users)
    correlation = uuid.uuid4()
    snapshot = _snapshot(event, WorkflowActionReceipt.SPEAKER_NUDGES, correlation, [task.pk])

    def delete_failed(*args, **kwargs):
        raise RuntimeError("redis delete failed")

    monkeypatch.setattr("pretalx_speakerops.workflow_action_tokens.cache.delete", delete_failed)
    client.force_login(users["chair"])
    url = (
        f"/orga/{event.slug}/speaker-operations/actions/speaker-nudges/"
        f"{correlation}/{snapshot.nonce}/confirm/"
    )
    assert client.post(url, {"targets": [task.pk], "confirm_action": "yes"}).status_code == 302
    assert client.post(url, {"targets": [task.pk], "confirm_action": "yes"}).status_code == 302
    with scope(event=event):
        assert WorkflowActionReceipt.objects.filter(correlation_id=correlation).count() == 1
        assert ReminderReceipt.objects.filter(task=task).count() == 1


@pytest.mark.django_db(transaction=True)
def test_legacy_retry_honors_logical_claim_and_shows_reconciliation(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        failed, _succeeded = _sync_items(event)
        claim = SyncWriteClaim.objects.create(
            event=event,
            local_type=failed.local_type,
            local_id=failed.local_id,
            actor=users["chair"],
            item=failed,
            status=SyncWriteClaim.AMBIGUOUS,
        )
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/sync-console/"
    response = client.post(
        url,
        {"action": "retry", "item_id": failed.pk, "confirm_sync": "yes"},
        follow=True,
    )
    assert response.status_code == 200
    assert claim in response.context["ambiguous_claims"]
    failed.refresh_from_db()
    assert failed.status == SyncItem.FAILED


@pytest.mark.django_db(transaction=True)
def test_organizer_can_audit_and_resolve_ambiguous_sync_claim(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        failed, _succeeded = _sync_items(event)
        claim = SyncWriteClaim.objects.create(
            event=event,
            local_type=failed.local_type,
            local_id=failed.local_id,
            actor=users["chair"],
            item=failed,
            status=SyncWriteClaim.AMBIGUOUS,
        )
        newer = SyncItem.objects.create(
            event=event,
            run=failed.run,
            action="update",
            local_type=failed.local_type,
            local_id=failed.local_id,
            status=SyncItem.SUCCEEDED,
            payload={},
            request_fingerprint="newer",
        )
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/sync-claims/{claim.pk}/resolve/"
    response = client.post(
        url,
        {
            "resolution": "verified_applied",
            "resolution_note": "Verified destination record and external identifier.",
            "confirm_resolution": "yes",
        },
    )
    assert response.status_code == 302
    claim.refresh_from_db()
    failed.refresh_from_db()
    newer.refresh_from_db()
    assert claim.active is False
    assert claim.resolution == "verified_applied"
    assert claim.resolved_by == users["chair"]
    assert claim.resolution_note.startswith("Verified destination")
    assert failed.status == SyncItem.RECONCILED
    assert newer.status == SyncItem.SUCCEEDED


@pytest.mark.django_db(transaction=True)
def test_verified_not_applied_marks_exact_running_item_failed(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save()
        item, _succeeded = _sync_items(event)
        item.status = SyncItem.RUNNING
        item.save(update_fields=["status", "updated"])
        claim = SyncWriteClaim.objects.create(
            event=event,
            local_type=item.local_type,
            local_id=item.local_id,
            actor=users["chair"],
            item=item,
            status=SyncWriteClaim.AMBIGUOUS,
        )
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/sync-claims/{claim.pk}/resolve/"
    response = client.post(
        url,
        {
            "resolution": "verified_not_applied",
            "resolution_note": "Verified no destination record exists.",
            "confirm_resolution": "yes",
        },
    )
    assert response.status_code == 302
    claim.refresh_from_db()
    item.refresh_from_db()
    assert claim.active is False
    assert claim.resolution == "verified_not_applied"
    assert item.status == SyncItem.FAILED
