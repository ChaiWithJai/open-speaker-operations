"""Read-only Buzz operations answers for integration and executive workflows.

These reads intentionally return bounded, JSON-safe summaries.  They never
execute a synchronization retry, expose connector credentials or source
payloads, or include private review/content comments.  A model can explain
the current state and link a human to evidence; authority remains in the
system of record.
"""

from __future__ import annotations

import uuid

from django.db.models import Count, Q
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.submission.models import Submission, SubmissionStates

from pretalx_speakerops.models import (
    AcceleventsConnection,
    OnboardingTask,
    OutboxEvent,
    ProgramDecision,
    SessionPublicationApproval,
    SyncItem,
    SyncRun,
    TaskEvidence,
    WorkflowActionReceipt,
)
from pretalx_speakerops.program.policy import classify_warnings
from pretalx_speakerops.workflow_action_tokens import ACTION_BATCH_LIMIT, create_action_snapshot

from ..sync_state import latest_failed_sync_items

DEFAULT_BASE_URL = "http://localhost:8000"


def _event(event_slug):
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    return event


def _base(base_url):
    return base_url.rstrip("/")


def _go(base_url, resource, opaque_id):
    return f"{_base(base_url)}/go/{resource}/{opaque_id}/"


def _safe_error(value):
    """Classify an error without relaying its attacker-controlled detail.

    Connector errors may contain submitted payload values, names, email
    addresses, request IDs, credentials, or an upstream response body.  A
    small allowlist of operational classes is enough for an executive or
    operator answer; the protected console remains the exact evidence source.
    """
    if not value:
        return None
    text = str(value).casefold()
    classifications = (
        (("rate limit", "too many requests", "429"), "Destination rate limit reached."),
        (
            ("credential", "unauthorized", "authentication", "401"),
            "Connector authentication failed.",
        ),
        (("timeout", "timed out"), "Destination request timed out."),
        (("duplicate", "already exists", "4068906"), "Destination reported a duplicate record."),
        (("connection", "network", "unreachable"), "Destination connection failed."),
    )
    for needles, label in classifications:
        if any(needle in text for needle in needles):
            return label
    return "Synchronization attempt failed; inspect the protected console for details."


def _iso(value):
    return value.isoformat() if value else None


def sync_recovery(
    event_slug,
    base_url=DEFAULT_BASE_URL,
    requesting_principal="speakerops-direct-read",
    claimed_channel_id="",
    claimed_trigger_event_id="",
):
    """Answer "Why is Accelevents out of sync?" without performing a write."""
    event = _event(event_slug)
    correlation_id = str(uuid.uuid4())
    with scope(event=event):
        connection = AcceleventsConnection.objects.filter(event=event).first()
        latest_run = SyncRun.objects.filter(event=event).order_by("-created", "-pk").first()
        failed = list(
            latest_failed_sync_items(event)
            .select_related("run")
            .prefetch_related("attempt_history")
            .order_by("-updated", "local_type", "local_id", "pk")
        )

        failed_items = []
        for item in failed:
            attempt = max(
                item.attempt_history.all(),
                key=lambda row: (row.number, row.started_at, row.pk),
                default=None,
            )
            failed_items.append(
                {
                    "sync_item_id": item.pk,
                    "run_id": item.run_id,
                    "record_type": item.local_type,
                    "local_id": item.local_id,
                    "action": item.action,
                    "attempt_count": item.attempts,
                    "last_error": _safe_error(item.error or (attempt.error if attempt else "")),
                    "last_attempt": (
                        {
                            "number": attempt.number,
                            "status": attempt.status,
                            "started_at": _iso(attempt.started_at),
                            "finished_at": _iso(attempt.finished_at),
                            "error": _safe_error(attempt.error),
                        }
                        if attempt
                        else None
                    ),
                    "evidence_link": (
                        f"{_go(base_url, 'sync-console', event.slug)}#sync-item-{item.pk}"
                    ),
                    "link_exactness": "exact-page-fragment",
                }
            )

        console_link = _go(base_url, "sync-console", event.slug)
        links = {
            "sync_console": console_link,
            "latest_run": (
                f"{console_link}#sync-run-{latest_run.pk}" if latest_run is not None else None
            ),
            "failed_items": [
                {
                    "sync_item_id": item["sync_item_id"],
                    "url": item["evidence_link"],
                    "exactness": item["link_exactness"],
                }
                for item in failed_items
            ],
        }
        action_target_ids = [item["sync_item_id"] for item in failed_items[:ACTION_BATCH_LIMIT]]
        try:
            snapshot = create_action_snapshot(
                event=event,
                workflow=WorkflowActionReceipt.SYNC_RECOVERY,
                correlation_id=correlation_id,
                target_ids=action_target_ids,
                principal=requesting_principal,
                claimed_channel_id=claimed_channel_id,
                claimed_trigger_event_id=claimed_trigger_event_id,
            )
        except Exception:
            snapshot = None
        retry_preview = {
            "available": snapshot is not None,
            "mode": "selective_failed_items_only",
            "eligible_count": len(action_target_ids),
            "eligible_item_ids": action_target_ids,
            "total_latest_failed_count": len(failed_items),
            "batch_limit": ACTION_BATCH_LIMIT,
            "truncated_count": max(0, len(failed_items) - len(action_target_ids)),
            "preserves_successful_items": True,
            "requires_human_confirmation": True,
            "executable_command_exposed": False,
            "mutation_performed": False,
            "correlation_id": correlation_id,
            "confirmation_url": (
                _go(
                    base_url,
                    "sync-retry-preview",
                    f"{event.slug}~{correlation_id}~{snapshot.nonce}",
                )
                if snapshot
                else None
            ),
            "limitation": (
                None
                if snapshot
                else "Confirmation preview unavailable because shared cache is unavailable."
            ),
            "receipt_tool": "workflow_action_receipts",
        }
        trace = [
            f"Resolved event `{event.slug}`.",
            "Read connector status and the latest synchronization run.",
            f"Selected {len(failed_items)} latest logical SyncItem records whose status is failed.",
            "Selected the highest-numbered attempt for each failed item.",
            "Removed payloads, responses, request IDs, credentials, and personal contact data.",
            "Built read-only console fragments; no retry command was invoked or exposed.",
            (
                "Built a correlated GET-safe retry preview; it requires explicit web confirmation."
                if snapshot
                else "Shared cache was unavailable; returned the typed read without an action link."
            ),
            f"Capped the confirmable batch at {ACTION_BATCH_LIMIT} targets.",
        ]
        result = {
            "event": event.slug,
            "out_of_sync": bool(failed_items)
            or bool(connection and connection.status != AcceleventsConnection.STATUS_CONNECTED),
            "connection": {
                "configured": connection is not None,
                "status": connection.status if connection else "not_configured",
                "last_verified_at": _iso(connection.last_verified) if connection else None,
                "last_error": _safe_error(connection.last_error) if connection else None,
            },
            "latest_run": (
                {
                    "run_id": latest_run.pk,
                    "status": latest_run.status,
                    "started_at": _iso(latest_run.started_at),
                    "finished_at": _iso(latest_run.finished_at),
                    "error": _safe_error(latest_run.error),
                }
                if latest_run
                else None
            ),
            "failed_count": len(failed_items),
            "failed_items": failed_items,
            "retry_preview": retry_preview,
            "links": links,
            "sources": [
                {
                    "model": "AcceleventsConnection",
                    "fields": ["status", "last_verified", "last_error"],
                },
                {
                    "model": "SyncRun",
                    "fields": ["status", "started_at", "finished_at", "error"],
                },
                {
                    "model": "SyncItem",
                    "fields": ["status", "action", "local_type", "local_id", "attempts", "error"],
                },
                {
                    "model": "SyncAttempt",
                    "fields": ["number", "status", "started_at", "finished_at", "error"],
                },
            ],
            "trace": trace,
            "generated_at": timezone.now().isoformat(),
        }
        result["rendered_sync_recovery_message"] = render_sync_recovery(result)
        return result


def render_sync_recovery(result):
    """Render the grounded operator answer included in ``sync_recovery``."""
    lines = [f"# Accelevents sync recovery — {result['event']}", ""]
    if result["out_of_sync"]:
        lines.append(f"**Out of sync** — {result['failed_count']} failed record(s) need review.")
    else:
        lines.append("**In sync** — no failed records are eligible for selective retry.")
    lines.extend(
        [
            "",
            f"- Connection: {result['connection']['status']}",
            f"- Latest run: {(result['latest_run'] or {}).get('status', 'none')}",
            "",
            "## Failed records",
            "",
        ]
    )
    if not result["failed_items"]:
        lines.append("- None.")
    for item in result["failed_items"]:
        error = item["last_error"] or "No sanitized error was recorded."
        lines.append(
            f"- `{item['record_type']}:{item['local_id']}` — {item['action']} — "
            f"{error} — [inspect item]({item['evidence_link']})"
        )
        attempt = item["last_attempt"]
        if attempt:
            lines.append(
                f"  - Latest attempt: SyncItem {item['sync_item_id']} / attempt "
                f"{attempt['number']} — {attempt['status']} — started "
                f"{attempt['started_at'] or 'unknown'}; finished "
                f"{attempt['finished_at'] or 'not finished'}."
            )
        else:
            lines.append(
                f"  - Latest attempt: SyncItem {item['sync_item_id']} / no attempt record."
            )
    preview = result["retry_preview"]
    lines.extend(
        [
            "",
            "## Safe selective retry preview",
            "",
            f"- Eligible failed items: {preview['eligible_count']}",
            "- Successful items are preserved.",
            "- A human confirmation is required in SpeakerOps.",
            "- This answer did not execute or expose a retry command.",
            (
                f"- [Review and confirm selective retry]({preview['confirmation_url']})"
                if preview["available"]
                else f"- Action unavailable: {preview['limitation']}"
            ),
            f"- Correlation: `{preview['correlation_id']}`",
            "",
            "## Evidence",
            "",
            f"- [Synchronization console]({result['links']['sync_console']})",
        ]
    )
    if result["links"]["latest_run"]:
        lines.append(f"- [Latest run]({result['links']['latest_run']})")
    lines.extend(["", "## Trace", ""])
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    lines.extend(["", f"Generated {result['generated_at']} (ISO-8601)."])
    return "\n".join(lines)


def sync_recovery_message(event_slug, base_url=DEFAULT_BASE_URL, **kwargs):
    return sync_recovery(event_slug, base_url, **kwargs)["rendered_sync_recovery_message"]


_RECEIPT_RESULT_FIELDS = {
    WorkflowActionReceipt.SPEAKER_NUDGES: (
        "outcome",
        "eligible_count",
        "completed_count",
        "failed_count",
        "ambiguous_count",
        "queued_count",
        "noop_count",
        "not_attempted_count",
        "task_ids",
        "attempted_task_ids",
        "reminder_receipt_ids",
    ),
    WorkflowActionReceipt.SYNC_RECOVERY: (
        "outcome",
        "eligible_count",
        "completed_count",
        "failed_count",
        "ambiguous_count",
        "not_attempted_count",
        "sync_item_ids",
        "attempted_item_ids",
        "ambiguous_item_id",
        "claim_resolution",
        "claim_resolved_by_id",
        "claim_resolved_at",
    ),
}


def workflow_action_receipts(
    event_slug,
    correlation_id,
    base_url=DEFAULT_BASE_URL,
    requesting_principal="speakerops-direct-read",
):
    """Return one principal-scoped receipt for its originating correlation."""
    event = _event(event_slug)
    with scope(event=event):
        receipt = (
            WorkflowActionReceipt.objects.filter(
                event=event,
                requesting_principal=requesting_principal,
                correlation_id=correlation_id,
            )
            .select_related("actor")
            .first()
        )
    if receipt is None:
        raise KeyError("no action receipt matches this correlation and principal")
    allowed = _RECEIPT_RESULT_FIELDS.get(receipt.workflow, ("outcome",))
    safe_result = {key: receipt.result[key] for key in allowed if key in receipt.result}
    row = {
        "receipt_id": receipt.pk,
        "correlation_id": str(receipt.correlation_id),
        "requesting_principal": receipt.requesting_principal,
        "claimed_channel_id": receipt.claimed_channel_id,
        "claimed_trigger_event_id": receipt.claimed_trigger_event_id,
        "provenance_attested": False,
        "workflow": receipt.workflow,
        "action": receipt.action,
        "status": receipt.status,
        "actor": {
            "user_id": receipt.actor_id,
            "display_name": receipt.actor.get_display_name()
            if receipt.actor_id
            else "Deleted user",
        },
        "confirmed_at": _iso(receipt.confirmed_at),
        "completed_at": _iso(receipt.completed_at),
        "target_count": receipt.target_count,
        "result": safe_result,
        "receipt_link": _go(
            base_url,
            "workflow-action-receipt",
            f"{event.slug}~{receipt.pk}",
        ),
    }
    result = {
        "event": event.slug,
        "read_only": True,
        "receipt": row,
        "trace": [
            f"Resolved event `{event.slug}`.",
            "Matched exactly one correlation within the deployment principal scope.",
            "Serialized only allowlisted high-level outcomes, actor identity, and correlation.",
            "Reported channel and trigger identifiers as caller-claimed, not attested provenance.",
            "Excluded connector payloads, responses, request IDs, credentials, and contact data.",
            "Performed no action or receipt mutation.",
        ],
        "generated_at": timezone.now().isoformat(),
    }
    result["rendered_workflow_action_receipts_message"] = render_workflow_action_receipts(result)
    return result


def render_workflow_action_receipts(result):
    lines = [f"# Workflow action receipts — {result['event']}", ""]
    receipt = result["receipt"]
    lines.extend(
        [
            f"## {receipt['workflow']} · {receipt['status']}",
            "",
            f"- Correlation: `{receipt['correlation_id']}`",
            f"- Actor: {receipt['actor']['display_name']} (user {receipt['actor']['user_id']})",
            f"- Claimed channel: `{receipt['claimed_channel_id'] or 'not supplied'}`",
            f"- Claimed trigger event: `{receipt['claimed_trigger_event_id'] or 'not supplied'}`",
            "- Provenance attested: no",
            f"- Targets: {receipt['target_count']}",
            f"- Confirmed: {receipt['confirmed_at']}",
            f"- Completed: {receipt['completed_at'] or 'not completed'}",
            f"- [Open receipt]({receipt['receipt_link']})",
            f"- Sanitized result: `{receipt['result']}`",
            "",
            "## Trace",
            "",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    lines.extend(["", f"Generated {result['generated_at']} (ISO-8601)."])
    return "\n".join(lines)


def workflow_action_receipts_message(
    event_slug, correlation_id, base_url=DEFAULT_BASE_URL, **kwargs
):
    return workflow_action_receipts(event_slug, correlation_id, base_url, **kwargs)[
        "rendered_workflow_action_receipts_message"
    ]


def _lifecycle_ids(event):
    submitted = set(
        Submission.objects.filter(event=event)
        .exclude(state=SubmissionStates.DRAFT)
        .values_list("pk", flat=True)
    )
    reviewed = set(
        Submission.objects.filter(event=event, pk__in=submitted, reviews__isnull=False)
        .distinct()
        .values_list("pk", flat=True)
    )
    decided = set(
        ProgramDecision.objects.filter(event=event).values_list("submission_id", flat=True)
    )
    task_states = {}
    for submission_id, status in OnboardingTask.objects.filter(
        event=event, submission__isnull=False
    ).values_list("submission_id", "status"):
        task_states.setdefault(submission_id, []).append(status)
    onboarded = {
        submission_id
        for submission_id, states in task_states.items()
        if states
        and all(state in (OnboardingTask.COMPLETE, OnboardingTask.WAIVED) for state in states)
    }
    wip = event.wip_schedule
    scheduled = (
        set(
            wip.talks.filter(submission__isnull=False, start__isnull=False).values_list(
                "submission_id", flat=True
            )
        )
        if wip
        else set()
    )
    current = event.current_schedule
    published = (
        set(
            current.talks.filter(submission__isnull=False, start__isnull=False).values_list(
                "submission_id", flat=True
            )
        )
        if current
        else set()
    )
    synchronized = set(
        SyncItem.objects.filter(
            event=event,
            local_type="session",
            status__in=(SyncItem.SUCCEEDED, SyncItem.NOOP, SyncItem.RECONCILED),
        ).values_list("local_id", flat=True)
    )
    return {
        "submitted": submitted,
        "reviewed": reviewed,
        "decided": decided,
        "onboarded": onboarded,
        "scheduled": scheduled,
        "published": published,
        "synchronized": synchronized,
    }


def executive_readiness(event_slug, base_url=DEFAULT_BASE_URL):
    """Answer "Are we ready?" with public-safe aggregate evidence only."""
    event = _event(event_slug)
    with scope(event=event):
        lifecycle = _lifecycle_ids(event)
        denominator = len(lifecycle["submitted"])
        funnel = [
            {
                "stage": stage,
                "count": len(lifecycle[stage]),
                "denominator": denominator,
                "gap": max(denominator - len(lifecycle[stage]), 0),
            }
            for stage in (
                "submitted",
                "reviewed",
                "decided",
                "onboarded",
                "scheduled",
                "published",
                "synchronized",
            )
        ]

        today = timezone.localdate()
        active_states = (OnboardingTask.PENDING, OnboardingTask.REOPENED)
        task_counts = OnboardingTask.objects.filter(event=event).aggregate(
            overdue=Count("pk", filter=Q(status__in=active_states, due_date__lt=today)),
            missing_assets=Count(
                "pk",
                filter=Q(
                    status__in=active_states,
                    definition__completion_evaluator="upload",
                ),
            ),
        )
        schedule = event.wip_schedule
        conflicts = len(classify_warnings(schedule)) if schedule else 0
        exception_counts = {
            "schedule_conflicts": conflicts,
            "overdue_tasks": task_counts["overdue"],
            "missing_assets": task_counts["missing_assets"],
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
        severity = {
            "schedule_conflicts": "critical",
            "sync_failures": "high",
            "overdue_tasks": "high",
            "missing_assets": "high",
            "unapproved_content": "high",
            "undecided_proposals": "medium",
            "pending_evidence_review": "medium",
            "outbox_backlog": "medium",
        }
        rank = {"critical": 0, "high": 1, "medium": 2}
        risks = sorted(
            (
                {"code": code, "severity": severity[code], "count": count}
                for code, count in exception_counts.items()
                if count
            ),
            key=lambda row: (rank[row["severity"]], row["code"]),
        )
        status_link = _go(base_url, "status", event.slug)
        complete_funnel = denominator > 0 and all(row["gap"] == 0 for row in funnel)
        trace = [
            f"Resolved event `{event.slug}`.",
            f"Counted {denominator} non-draft submissions as the common funnel denominator.",
            "Computed each lifecycle stage from system-of-record evidence.",
            f"Counted {sum(exception_counts.values())} aggregate operational exceptions.",
            "Excluded people, emails, source payloads, credentials, notes, "
            "comments, and admin links.",
            "Linked only the public machine-readable status endpoint.",
        ]
        result = {
            "event": event.slug,
            "ready": complete_funnel and not risks,
            "verdict": (
                "ready"
                if complete_funnel and not risks
                else "not_ready"
                if denominator or risks
                else "insufficient_evidence"
            ),
            "funnel": funnel,
            "exceptions": exception_counts,
            "risks": risks,
            "evidence_links": [
                {
                    "resource": "status",
                    "url": status_link,
                    "audience": "public",
                    "exactness": "public-output",
                }
            ],
            "capabilities": {"read_only": True, "admin": False, "commands": []},
            "sources": [
                {"model": "Submission", "evidence": "aggregate lifecycle counts"},
                {"model": "OnboardingTask", "evidence": "aggregate completion and due state"},
                {"model": "SessionPublicationApproval", "evidence": "aggregate approval state"},
                {"model": "SyncItem", "evidence": "aggregate synchronization state"},
                {"model": "OutboxEvent", "evidence": "aggregate unprocessed count"},
            ],
            "trace": trace,
            "generated_at": timezone.now().isoformat(),
        }
        result["rendered_executive_readiness_message"] = render_executive_readiness(result)
        return result


def render_executive_readiness(result):
    """Render the sanitized executive answer included in the payload."""
    lines = [f"# Executive readiness — {result['event']}", ""]
    if result["ready"]:
        lines.append("**Ready** — the lifecycle funnel is complete and no aggregate risks remain.")
    elif result["verdict"] == "insufficient_evidence":
        lines.append("**Insufficient evidence** — there is no program funnel to declare ready.")
    else:
        lines.append("**Not ready** — lifecycle gaps or operational exceptions remain.")
    lines.extend(
        [
            "",
            "## Program funnel",
            "",
            "| Stage | Complete | Total | Gap |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in result["funnel"]:
        lines.append(
            f"| {row['stage'].replace('_', ' ').title()} | {row['count']} | "
            f"{row['denominator']} | {row['gap']} |"
        )
    lines.extend(["", "## Risks", ""])
    if not result["risks"]:
        lines.append("- None.")
    for risk in result["risks"]:
        lines.append(
            f"- **{risk['severity'].title()}** — {risk['code'].replace('_', ' ')}: {risk['count']}"
        )
    status = result["evidence_links"][0]
    lines.extend(
        [
            "",
            "## Public evidence",
            "",
            f"- [Machine-readable event status]({status['url']})",
            "",
            "## Trace",
            "",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    lines.extend(["", f"Generated {result['generated_at']} (ISO-8601)."])
    return "\n".join(lines)


def executive_readiness_message(event_slug, base_url=DEFAULT_BASE_URL):
    return executive_readiness(event_slug, base_url)["rendered_executive_readiness_message"]
