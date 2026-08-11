import json
from datetime import timedelta

from django.utils import timezone
from django_scopes import scope
from pretalx.submission.models import Submission, SubmissionStates

from pretalx_speakerops.integrations.buzz.operations_reads import (
    executive_readiness,
    executive_readiness_message,
    sync_recovery,
    sync_recovery_message,
)
from pretalx_speakerops.models import (
    AcceleventsConnection,
    CommandReceipt,
    OnboardingTask,
    OutboxEvent,
    ProgramDecision,
    SessionPublicationApproval,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
    TaskDefinition,
    TaskEvidence,
)

BASE_URL = "https://speakerops.example/"


def _all_keys(value):
    if isinstance(value, dict):
        yield from value
        for nested in value.values():
            yield from _all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_keys(nested)


def _clear_sync(event):
    SyncAttempt.objects.filter(event=event).delete()
    SyncItem.objects.filter(event=event).delete()
    SyncRun.objects.filter(event=event).delete()
    SyncPreview.objects.filter(event=event).delete()
    AcceleventsConnection.objects.filter(event=event).delete()


def _sync_run(event, status=SyncRun.PARTIAL, error=""):
    sync_preview = SyncPreview.objects.create(
        event=event,
        fingerprint="preview-fingerprint",
        payload={"items": [], "private": "preview-private-value"},
    )
    now = timezone.now()
    return SyncRun.objects.create(
        event=event,
        preview=sync_preview,
        status=status,
        started_at=now - timedelta(minutes=5),
        finished_at=now,
        error=error,
    )


def _sync_item(event, run, *, local_type, local_id, status, updated, error=""):
    item = SyncItem.objects.create(
        event=event,
        run=run,
        action="create",
        local_type=local_type,
        local_id=local_id,
        payload={
            "name": "Private Person",
            "email": "private.person@example.org",
            "comment": "private operator comment",
        },
        request_fingerprint=f"fingerprint-{local_id}",
        request_id=f"private-request-{local_id}",
        status=status,
        attempts=2 if status == SyncItem.FAILED else 1,
        error=error,
    )
    SyncItem.objects.filter(pk=item.pk).update(updated=updated)
    item.refresh_from_db()
    return item


def test_sync_recovery_empty_state_is_json_safe_read_only_and_grounded(event):
    with scope(event=event):
        _clear_sync(event)
        before_receipts = CommandReceipt.objects.filter(event=event).count()
        result = sync_recovery(event.slug, BASE_URL)

        assert json.loads(json.dumps(result)) == result
        assert result["out_of_sync"] is False
        assert result["failed_count"] == 0
        assert result["failed_items"] == []
        assert result["latest_run"] is None
        assert result["connection"] == {
            "configured": False,
            "status": "not_configured",
            "last_verified_at": None,
            "last_error": None,
        }
        assert result["retry_preview"] == {
            "mode": "selective_failed_items_only",
            "eligible_count": 0,
            "eligible_item_ids": [],
            "preserves_successful_items": True,
            "requires_human_confirmation": True,
            "executable_command_exposed": False,
            "mutation_performed": False,
        }
        assert result["links"] == {
            "sync_console": (f"https://speakerops.example/go/sync-console/{event.slug}/"),
            "latest_run": None,
            "failed_items": [],
        }
        assert {source["model"] for source in result["sources"]} == {
            "AcceleventsConnection",
            "SyncRun",
            "SyncItem",
            "SyncAttempt",
        }
        assert "**In sync**" in result["rendered_sync_recovery_message"]
        assert result["generated_at"] in result["rendered_sync_recovery_message"]
        assert "## Trace" in sync_recovery_message(event.slug, BASE_URL)
        assert CommandReceipt.objects.filter(event=event).count() == before_receipts
        assert not SyncRun.objects.filter(event=event).exists()
        assert not SyncItem.objects.filter(event=event).exists()


def test_sync_recovery_orders_failures_sanitizes_details_and_never_retries(event):
    now = timezone.now()
    with scope(event=event):
        _clear_sync(event)
        AcceleventsConnection.objects.create(
            event=event,
            base_url="https://destination.example/private-tenant",
            event_url="private-event",
            credential_ref="sk-private-connector-credential",
            status=AcceleventsConnection.STATUS_ERROR,
            last_error="Unauthorized token=sk-private admin@example.org",
            last_verified=now - timedelta(minutes=10),
        )
        run = _sync_run(
            event,
            error="Upstream returned Private Person private.person@example.org secret=run-secret",
        )
        older = _sync_item(
            event,
            run,
            local_type="speaker",
            local_id=410,
            status=SyncItem.FAILED,
            updated=now - timedelta(hours=2),
            error="Destination rate limit for private.person@example.org token=item-secret",
        )
        newer = _sync_item(
            event,
            run,
            local_type="session",
            local_id=420,
            status=SyncItem.FAILED,
            updated=now - timedelta(hours=1),
            error="",
        )
        succeeded = _sync_item(
            event,
            run,
            local_type="speaker",
            local_id=430,
            status=SyncItem.SUCCEEDED,
            updated=now,
        )
        SyncAttempt.objects.create(
            event=event,
            item=newer,
            number=1,
            status=SyncItem.FAILED,
            request_id="attempt-private-one",
            response={"body": "Private Person", "token": "response-secret"},
            error="Network error for private.person@example.org",
            started_at=now - timedelta(minutes=4),
            finished_at=now - timedelta(minutes=3),
        )
        latest_attempt = SyncAttempt.objects.create(
            event=event,
            item=newer,
            number=2,
            status=SyncItem.FAILED,
            request_id="attempt-private-two",
            response={"comment": "private response comment"},
            error="Timeout while sending Private Person token=attempt-secret",
            started_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=1),
        )
        item_snapshot = list(
            SyncItem.objects.filter(event=event)
            .order_by("pk")
            .values("pk", "status", "attempts", "payload", "request_id", "error")
        )
        attempt_snapshot = list(
            SyncAttempt.objects.filter(event=event)
            .order_by("pk")
            .values("pk", "status", "response", "request_id", "error")
        )
        receipt_count = CommandReceipt.objects.filter(event=event).count()

        result = sync_recovery(event.slug, BASE_URL)
        serialized = json.dumps(result, sort_keys=True)

        assert json.loads(serialized) == result
        assert result["out_of_sync"] is True
        assert result["failed_count"] == 2
        assert [row["sync_item_id"] for row in result["failed_items"]] == [newer.pk, older.pk]
        assert succeeded.pk not in result["retry_preview"]["eligible_item_ids"]
        assert result["retry_preview"]["eligible_item_ids"] == [newer.pk, older.pk]
        assert result["retry_preview"]["preserves_successful_items"] is True
        assert result["retry_preview"]["requires_human_confirmation"] is True
        assert result["retry_preview"]["executable_command_exposed"] is False
        assert result["retry_preview"]["mutation_performed"] is False
        assert result["failed_items"][0]["last_attempt"]["number"] == latest_attempt.number
        assert result["failed_items"][0]["last_attempt"]["error"] == (
            "Destination request timed out."
        )
        assert result["failed_items"][1]["last_error"] == "Destination rate limit reached."
        assert result["connection"]["last_error"] == "Connector authentication failed."
        assert result["latest_run"]["error"] == (
            "Synchronization attempt failed; inspect the protected console for details."
        )
        for row in result["failed_items"]:
            assert row["evidence_link"] == (
                f"https://speakerops.example/go/sync-console/{event.slug}/"
                f"#sync-item-{row['sync_item_id']}"
            )
            assert row["link_exactness"] == "exact-page-fragment"
        assert result["links"]["latest_run"].endswith(f"#sync-run-{run.pk}")
        assert "/go/sync-run-retry/" not in serialized
        assert "/admin/" not in serialized

        forbidden_values = (
            "Private Person",
            "private.person@example.org",
            "private operator comment",
            "sk-private-connector-credential",
            "item-secret",
            "attempt-secret",
            "response-secret",
            "attempt-private-one",
            "attempt-private-two",
            "private response comment",
            "private-tenant",
        )
        assert all(value not in serialized for value in forbidden_values)
        assert {"payload", "response", "request_id", "credential_ref"}.isdisjoint(
            set(_all_keys(result))
        )
        assert (
            list(
                SyncItem.objects.filter(event=event)
                .order_by("pk")
                .values("pk", "status", "attempts", "payload", "request_id", "error")
            )
            == item_snapshot
        )
        assert (
            list(
                SyncAttempt.objects.filter(event=event)
                .order_by("pk")
                .values("pk", "status", "response", "request_id", "error")
            )
            == attempt_snapshot
        )
        assert CommandReceipt.objects.filter(event=event).count() == receipt_count


def test_executive_readiness_empty_program_is_insufficient_public_evidence(event):
    with scope(event=event):
        _clear_sync(event)
        TaskEvidence.objects.filter(event=event).delete()
        OnboardingTask.objects.filter(event=event).delete()
        SessionPublicationApproval.objects.filter(event=event).delete()
        ProgramDecision.objects.filter(event=event).delete()
        OutboxEvent.objects.filter(event=event).delete()
        if event.wip_schedule:
            event.wip_schedule.talks.all().delete()
        if event.current_schedule and event.current_schedule != event.wip_schedule:
            event.current_schedule.talks.all().delete()
        Submission.objects.filter(event=event).update(state=SubmissionStates.DRAFT)

        result = executive_readiness(event.slug, BASE_URL)

        assert json.loads(json.dumps(result)) == result
        assert result["ready"] is False
        assert result["verdict"] == "insufficient_evidence"
        assert all(row["count"] == 0 for row in result["funnel"])
        assert all(row["denominator"] == 0 for row in result["funnel"])
        assert result["risks"] == []
        assert result["capabilities"] == {"read_only": True, "admin": False, "commands": []}
        assert result["evidence_links"] == [
            {
                "resource": "status",
                "url": f"https://speakerops.example/go/status/{event.slug}/",
                "audience": "public",
                "exactness": "public-output",
            }
        ]
        assert "**Insufficient evidence**" in result["rendered_executive_readiness_message"]
        assert result["generated_at"] in result["rendered_executive_readiness_message"]


def test_executive_readiness_matches_aggregates_orders_risks_and_leaks_no_people(event, users):
    now = timezone.now()
    with scope(event=event):
        _clear_sync(event)
        submission = (
            Submission.objects.filter(event=event).exclude(state=SubmissionStates.DRAFT).first()
        )
        assert submission is not None
        if not submission.speakers.exists():
            submission.speakers.add(users["speaker"])
        speaker = submission.speakers.first()
        speaker.name = "Private Executive Speaker"
        speaker.email = "private.executive@example.org"
        speaker.save(update_fields=["name", "email"])

        definition, _ = TaskDefinition.objects.update_or_create(
            event=event,
            slug="private-executive-deck",
            defaults={
                "name": "Private deck request",
                "instructions": "private instructions",
                "completion_criteria": "private criteria",
                "completion_evaluator": "upload",
            },
        )
        task, _ = OnboardingTask.objects.update_or_create(
            event=event,
            submission=submission,
            speaker=speaker,
            definition=definition,
            defaults={
                "status": OnboardingTask.PENDING,
                "due_date": timezone.localdate() - timedelta(days=2),
                "evidence": {"private": "task-private-value"},
            },
        )
        TaskEvidence.objects.update_or_create(
            event=event,
            task=task,
            version=1,
            defaults={
                "speaker": speaker,
                "kind": "upload",
                "upload": "speakerops/evidence/private-executive.pdf",
                "value": {"comment": "evidence-private-value"},
                "review_status": TaskEvidence.PENDING,
                "review_note": "private evidence review comment",
            },
        )
        SessionPublicationApproval.objects.update_or_create(
            event=event,
            submission=submission,
            defaults={
                "status": SessionPublicationApproval.CHANGES_REQUESTED,
                "note": "private publication comment",
                "reviewed_by": users["chair"],
                "reviewed_at": now,
            },
        )
        ProgramDecision.objects.update_or_create(
            event=event,
            submission=submission,
            defaults={
                "status": ProgramDecision.ACCEPT,
                "decided_by": users["chair"],
                "rationale": "private chair rationale",
            },
        )
        OutboxEvent.objects.create(
            event=event,
            kind="private-event",
            aggregate_type="submission",
            aggregate_id=submission.pk,
            payload={"email": speaker.email, "comment": "outbox-private-value"},
        )
        run = _sync_run(event)
        _sync_item(
            event,
            run,
            local_type="session",
            local_id=submission.pk,
            status=SyncItem.FAILED,
            updated=now,
            error="Private Executive Speaker private.executive@example.org",
        )
        receipt_count = CommandReceipt.objects.filter(event=event).count()
        expected = {
            "overdue_tasks": OnboardingTask.objects.filter(
                event=event,
                status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                due_date__lt=timezone.localdate(),
            ).count(),
            "missing_assets": OnboardingTask.objects.filter(
                event=event,
                status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                definition__completion_evaluator="upload",
            ).count(),
            "unapproved_content": SessionPublicationApproval.objects.filter(event=event)
            .exclude(status=SessionPublicationApproval.APPROVED)
            .count(),
            "pending_evidence_review": TaskEvidence.objects.filter(
                event=event,
                upload__isnull=False,
                review_status=TaskEvidence.PENDING,
            ).count(),
            "undecided_proposals": Submission.objects.filter(
                event=event, state=SubmissionStates.SUBMITTED
            ).count(),
            "sync_failures": SyncItem.objects.filter(event=event, status=SyncItem.FAILED).count(),
            "outbox_backlog": OutboxEvent.objects.filter(
                event=event, processed__isnull=True
            ).count(),
        }

        result = executive_readiness(event.slug, BASE_URL)
        serialized = json.dumps(result, sort_keys=True)

        assert json.loads(serialized) == result
        assert result["ready"] is False
        assert result["verdict"] == "not_ready"
        for code, count in expected.items():
            assert result["exceptions"][code] == count
        rank = {"critical": 0, "high": 1, "medium": 2}
        assert result["risks"] == sorted(
            result["risks"], key=lambda row: (rank[row["severity"]], row["code"])
        )
        assert {row["code"] for row in result["risks"]} >= {
            "overdue_tasks",
            "missing_assets",
            "unapproved_content",
            "pending_evidence_review",
            "sync_failures",
            "outbox_backlog",
        }
        submitted_count = (
            Submission.objects.filter(event=event).exclude(state=SubmissionStates.DRAFT).count()
        )
        assert result["funnel"][0] == {
            "stage": "submitted",
            "count": submitted_count,
            "denominator": submitted_count,
            "gap": 0,
        }
        assert [row["stage"] for row in result["funnel"]] == [
            "submitted",
            "reviewed",
            "decided",
            "onboarded",
            "scheduled",
            "published",
            "synchronized",
        ]
        assert result["capabilities"] == {"read_only": True, "admin": False, "commands": []}
        assert len(result["evidence_links"]) == 1
        assert result["evidence_links"][0]["audience"] == "public"
        assert result["evidence_links"][0]["url"].endswith(f"/go/status/{event.slug}/")
        assert "/admin/" not in serialized
        assert "/orga/" not in serialized
        assert "sync-run-retry" not in serialized
        forbidden_values = (
            "Private Executive Speaker",
            "private.executive@example.org",
            "task-private-value",
            "evidence-private-value",
            "private evidence review comment",
            "private publication comment",
            "private chair rationale",
            "outbox-private-value",
            "private-executive.pdf",
        )
        assert all(value not in serialized for value in forbidden_values)
        assert "## Public evidence" in executive_readiness_message(event.slug, BASE_URL)
        assert CommandReceipt.objects.filter(event=event).count() == receipt_count
