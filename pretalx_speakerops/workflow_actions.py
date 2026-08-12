"""Human confirmation boundaries for the two Buzz-assisted write workflows."""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View
from django_scopes import scope

from .domain.commands import Command, execute
from .integrations.sync import SYNC_ITEM_MACHINE, execute_item
from .integrations.sync_claims import SyncClaimBlocked, release_sync_claim
from .integrations.sync_state import latest_failed_sync_items
from .models import (
    OnboardingTask,
    ReminderReceipt,
    SyncItem,
    SyncWriteClaim,
    WorkflowActionReceipt,
)
from .onboarding.reminders import queue_reminder_task
from .views import EventContextMixin
from .workflow_action_tokens import (
    ACTION_BATCH_LIMIT,
    consume_action_snapshot,
    load_action_snapshot,
)


class ActionClaimConflict(Exception):
    pass


def _receipt_url(event_slug, receipt_pk):
    return reverse(
        "plugins:speakerops:speakerops_workflow_action_receipt",
        kwargs={"event": event_slug, "pk": receipt_pk},
    )


def _snapshot_or_404(*, nonce, event_slug, workflow, correlation):
    snapshot = load_action_snapshot(
        nonce=nonce,
        event_slug=event_slug,
        workflow=workflow,
        correlation_id=correlation,
    )
    if snapshot is None:
        raise Http404
    return snapshot


def _receipt_defaults(snapshot, *, action, actor, target_count):
    return {
        "workflow": snapshot.workflow,
        "action": action,
        "actor": actor,
        "requesting_principal": snapshot.requesting_principal,
        "claimed_channel_id": snapshot.claimed_channel_id,
        "claimed_trigger_event_id": snapshot.claimed_trigger_event_id,
        "status": WorkflowActionReceipt.PENDING,
        "target_count": target_count,
        "result": {
            "outcome": "confirmed",
            "eligible_count": target_count,
            "completed_count": 0,
            "failed_count": 0,
            "ambiguous_count": 0,
            "not_attempted_count": target_count,
        },
    }


def _finish_receipt(receipt, *, status, result):
    receipt.status = status
    receipt.result = result
    receipt.completed_at = timezone.now()
    receipt.save(update_fields=["status", "result", "completed_at", "updated"])
    return receipt


def _posted_target_ids(request):
    values = request.POST.getlist("targets")
    if any(not value.isdigit() for value in values):
        raise Http404
    return sorted({int(value) for value in values})


def _preview_url(name, *, event, correlation, nonce):
    return reverse(
        f"plugins:speakerops:{name}",
        kwargs={"event": event, "correlation": correlation, "nonce": nonce},
    )


class SpeakerNudgeActionPreviewView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/workflow_action_preview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = _snapshot_or_404(
            nonce=self.kwargs["nonce"],
            event_slug=self.event.slug,
            workflow=WorkflowActionReceipt.SPEAKER_NUDGES,
            correlation=self.kwargs["correlation"],
        )
        today = timezone.localdate()
        with scope(event=self.event):
            targets = list(
                OnboardingTask.objects.filter(
                    event=self.event,
                    status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                    due_date__lt=today,
                    pk__in=snapshot.target_ids,
                )
                .select_related("speaker", "definition", "submission")
                .order_by("pk")
            )
        context.update(
            event=self.event,
            action_kind="speaker_nudges",
            action_title="Send overdue speaker reminders",
            action_summary=(
                "This confirmation is limited to at most "
                f"{ACTION_BATCH_LIMIT} server-snapshotted overdue tasks."
            ),
            correlation=self.kwargs["correlation"],
            targets=targets,
            stale=len(targets) != len(snapshot.target_ids),
            expires_at=snapshot.expires_at,
            batch_limit=ACTION_BATCH_LIMIT,
            confirm_url=_preview_url(
                "speakerops_speaker_nudge_confirm",
                event=self.event.slug,
                correlation=self.kwargs["correlation"],
                nonce=self.kwargs["nonce"],
            ),
        )
        return context


class SpeakerNudgeActionConfirmView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, correlation, nonce):
        preview_url = _preview_url(
            "speakerops_speaker_nudge_preview",
            event=event,
            correlation=correlation,
            nonce=nonce,
        )
        existing = WorkflowActionReceipt.objects.filter(
            event=self.event, correlation_id=correlation
        ).first()
        if existing:
            return redirect(_receipt_url(event, existing.pk))
        snapshot = _snapshot_or_404(
            nonce=nonce,
            event_slug=self.event.slug,
            workflow=WorkflowActionReceipt.SPEAKER_NUDGES,
            correlation=correlation,
        )
        if request.POST.get("confirm_action") != "yes":
            messages.error(request, "Explicitly confirm the reminder recipients first.")
            return redirect(preview_url)
        requested_ids = _posted_target_ids(request)
        if requested_ids != snapshot.target_ids:
            messages.error(request, "The submitted targets do not match the server snapshot.")
            return redirect(preview_url)
        today = timezone.localdate()
        try:
            with scope(event=self.event), transaction.atomic():
                if snapshot.expires_at <= timezone.now():
                    raise Http404
                targets = list(
                    OnboardingTask.objects.select_for_update()
                    .filter(
                        event=self.event,
                        pk__in=requested_ids,
                        status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                        due_date__lt=today,
                    )
                    .select_related("speaker", "definition", "submission")
                    .order_by("pk")
                )
                if [task.pk for task in targets] != requested_ids:
                    messages.error(request, "This preview is stale; request a fresh Buzz answer.")
                    return redirect(preview_url)
                receipt = WorkflowActionReceipt.objects.create(
                    event=self.event,
                    correlation_id=correlation,
                    **_receipt_defaults(
                        snapshot,
                        action="queue_overdue_reminders",
                        actor=request.user,
                        target_count=len(targets),
                    ),
                )
        except IntegrityError:
            existing = WorkflowActionReceipt.objects.filter(
                event=self.event, correlation_id=correlation
            ).first()
            if existing:
                return redirect(_receipt_url(event, existing.pk))
            raise
        consume_action_snapshot(nonce)

        # The pending receipt is committed before any mail/broker I/O begins.
        reminder_key = f"buzz-overdue:{today.isoformat()}"
        queued_count = 0
        noop_count = 0
        ambiguous_count = 0
        attempted_ids = []
        for task in targets:
            attempted_ids.append(task.pk)
            try:
                outcome, _reminder_receipt = queue_reminder_task(self.event, task, reminder_key)
            except Exception:
                ambiguous_count = 1
                break
            if outcome == "queued":
                queued_count += 1
            else:
                noop_count += 1
        reminder_receipt_ids = list(
            ReminderReceipt.objects.filter(
                event=self.event,
                task_id__in=[task.pk for task in targets],
                reminder_key=reminder_key,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        not_attempted_count = len(targets) - queued_count - noop_count - ambiguous_count
        if ambiguous_count:
            status = WorkflowActionReceipt.AMBIGUOUS
            outcome = "queue_outcome_ambiguous"
        elif queued_count:
            status = WorkflowActionReceipt.SUCCEEDED
            outcome = "queued"
        else:
            status = WorkflowActionReceipt.NOOP
            outcome = "already_queued"
        _finish_receipt(
            receipt,
            status=status,
            result={
                "outcome": outcome,
                "eligible_count": len(targets),
                "completed_count": queued_count,
                "failed_count": 0,
                "ambiguous_count": ambiguous_count,
                "not_attempted_count": not_attempted_count,
                "noop_count": noop_count,
                "queued_count": queued_count,
                "task_ids": [task.pk for task in targets],
                "attempted_task_ids": attempted_ids,
                "reminder_receipt_ids": reminder_receipt_ids,
            },
        )
        if ambiguous_count:
            messages.error(
                request,
                "Reminder queue outcome is ambiguous; later tasks were not attempted.",
            )
        elif queued_count:
            messages.success(request, f"Queued {queued_count} reminders; receipt recorded.")
        else:
            messages.info(request, "No new reminders were needed; no-op receipt recorded.")
        return redirect(_receipt_url(event, receipt.pk))


class SyncRecoveryActionPreviewView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/workflow_action_preview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = _snapshot_or_404(
            nonce=self.kwargs["nonce"],
            event_slug=self.event.slug,
            workflow=WorkflowActionReceipt.SYNC_RECOVERY,
            correlation=self.kwargs["correlation"],
        )
        with scope(event=self.event):
            targets = list(
                latest_failed_sync_items(self.event, target_ids=snapshot.target_ids)
                .select_related("run")
                .order_by("pk")
            )
        context.update(
            event=self.event,
            action_kind="sync_recovery",
            action_title="Retry only current failed synchronization items",
            action_summary=(
                "This confirmation is limited to at most "
                f"{ACTION_BATCH_LIMIT} latest logical records. Newer records invalidate it."
            ),
            correlation=self.kwargs["correlation"],
            targets=targets,
            stale=len(targets) != len(snapshot.target_ids),
            expires_at=snapshot.expires_at,
            batch_limit=ACTION_BATCH_LIMIT,
            confirm_url=_preview_url(
                "speakerops_sync_recovery_confirm",
                event=self.event.slug,
                correlation=self.kwargs["correlation"],
                nonce=self.kwargs["nonce"],
            ),
        )
        return context


class SyncRecoveryActionConfirmView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, correlation, nonce):
        preview_url = _preview_url(
            "speakerops_sync_recovery_preview",
            event=event,
            correlation=correlation,
            nonce=nonce,
        )
        existing = WorkflowActionReceipt.objects.filter(
            event=self.event, correlation_id=correlation
        ).first()
        if existing:
            return redirect(_receipt_url(event, existing.pk))
        snapshot = _snapshot_or_404(
            nonce=nonce,
            event_slug=self.event.slug,
            workflow=WorkflowActionReceipt.SYNC_RECOVERY,
            correlation=correlation,
        )
        if request.POST.get("confirm_action") != "yes":
            messages.error(request, "Explicitly confirm the failed synchronization items first.")
            return redirect(preview_url)
        requested_ids = _posted_target_ids(request)
        if requested_ids != snapshot.target_ids:
            messages.error(request, "The submitted targets do not match the server snapshot.")
            return redirect(preview_url)

        try:
            with scope(event=self.event), transaction.atomic():
                if snapshot.expires_at <= timezone.now():
                    raise Http404
                targets = list(
                    latest_failed_sync_items(self.event, target_ids=requested_ids, lock=True)
                    .select_related("run")
                    .order_by("pk")
                )
                if [item.pk for item in targets] != requested_ids:
                    messages.error(
                        request,
                        "This preview is stale or a newer sync record exists; "
                        "request a fresh answer.",
                    )
                    return redirect(preview_url)
                receipt = WorkflowActionReceipt.objects.create(
                    event=self.event,
                    correlation_id=correlation,
                    **_receipt_defaults(
                        snapshot,
                        action="retry_failed_sync_items",
                        actor=request.user,
                        target_count=len(targets),
                    ),
                )
            consume_action_snapshot(nonce)
        except IntegrityError:
            existing = WorkflowActionReceipt.objects.filter(
                event=self.event, correlation_id=correlation
            ).first()
            if existing:
                return redirect(_receipt_url(event, existing.pk))
            messages.error(request, "A selected sync item is already being retried; refresh first.")
            return redirect(preview_url)

        # Receipt and target claims are committed before connector I/O.
        completed_count = 0
        failed_count = 0
        ambiguous_count = 0
        ambiguous_item_id = None
        attempted_ids = []
        for item in targets:
            attempted_ids.append(item.pk)
            try:
                execute_item(item, request.user, workflow_receipt=receipt)
                item.refresh_from_db(fields=["status"])
            except SyncClaimBlocked:
                failed_count += 1
                continue
            except Exception:
                ambiguous_count = 1
                ambiguous_item_id = item.pk
                break
            if item.status in (SyncItem.SUCCEEDED, SyncItem.RECONCILED, SyncItem.NOOP):
                completed_count += 1
            else:
                failed_count += 1
        not_attempted_count = len(targets) - completed_count - failed_count - ambiguous_count
        if ambiguous_count:
            status = WorkflowActionReceipt.AMBIGUOUS
            outcome = "retry_outcome_ambiguous"
        elif failed_count and completed_count:
            status = WorkflowActionReceipt.PARTIAL
            outcome = "retry_partially_completed"
        elif failed_count:
            status = WorkflowActionReceipt.FAILED
            outcome = "retry_failed"
        elif targets:
            status = WorkflowActionReceipt.SUCCEEDED
            outcome = "retry_completed"
        else:
            status = WorkflowActionReceipt.NOOP
            outcome = "no_failed_items_selected"
        _finish_receipt(
            receipt,
            status=status,
            result={
                "outcome": outcome,
                "eligible_count": len(targets),
                "completed_count": completed_count,
                "failed_count": failed_count,
                "ambiguous_count": ambiguous_count,
                "not_attempted_count": not_attempted_count,
                "sync_item_ids": [item.pk for item in targets],
                "attempted_item_ids": attempted_ids,
                "ambiguous_item_id": ambiguous_item_id,
            },
        )
        if status == WorkflowActionReceipt.SUCCEEDED:
            messages.success(request, "Selective retry completed; receipt recorded.")
        elif status == WorkflowActionReceipt.PARTIAL:
            messages.warning(request, "Selective retry partially completed; inspect the receipt.")
        elif status == WorkflowActionReceipt.AMBIGUOUS:
            messages.error(request, "Retry outcome is ambiguous; do not retry before inspection.")
        elif status == WorkflowActionReceipt.FAILED:
            messages.error(request, "Selective retry failed; inspect the receipt.")
        else:
            messages.info(request, "No failed items remained; no-op receipt recorded.")
        return redirect(_receipt_url(event, receipt.pk))


class WorkflowActionReceiptListView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/workflow_action_receipts.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            context["receipts"] = list(
                WorkflowActionReceipt.objects.filter(event=self.event)
                .select_related("actor")
                .order_by("-confirmed_at", "-pk")[:100]
            )
        context["event"] = self.event
        return context


class WorkflowActionReceiptView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/workflow_action_receipt.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            receipt = get_object_or_404(
                WorkflowActionReceipt.objects.select_related("actor"),
                event=self.event,
                pk=self.kwargs["pk"],
            )
            context["receipt"] = receipt
            context["ambiguous_claims"] = list(
                receipt.sync_write_claims.filter(
                    active=True, status=SyncWriteClaim.AMBIGUOUS
                ).order_by("pk")
            )
        context["event"] = self.event
        return context


class SyncWriteClaimResolveView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        resolution = request.POST.get("resolution")
        note = request.POST.get("resolution_note", "").strip()[:500]
        if (
            request.POST.get("confirm_resolution") != "yes"
            or resolution not in {"verified_applied", "verified_not_applied"}
            or not note
        ):
            messages.error(request, "Choose a verified outcome, add a note, and confirm it.")
            return redirect(
                request.META.get("HTTP_REFERER")
                or reverse("plugins:speakerops:speakerops_sync_console", kwargs={"event": event})
            )
        with scope(event=self.event), transaction.atomic():
            claim = get_object_or_404(
                SyncWriteClaim.objects.select_for_update(),
                event=self.event,
                pk=pk,
                active=True,
                status=SyncWriteClaim.AMBIGUOUS,
            )
            item = claim.item
            if resolution == "verified_applied":
                if item.status in (SyncItem.FAILED, SyncItem.RUNNING):
                    execute(
                        Command(
                            event=self.event,
                            aggregate_model=SyncItem,
                            aggregate_id=item.pk,
                            action="sync.claim.resolve_reconciled",
                            target_state=SyncItem.RECONCILED,
                            state_machine=SYNC_ITEM_MACHINE,
                        ),
                        request.user,
                        key=f"sync-claim:{claim.pk}:verified-applied",
                        expected_version=item.version,
                    )
                else:
                    messages.error(
                        request,
                        "Only the exact failed or running item can be marked reconciled.",
                    )
                    return redirect(
                        request.META.get("HTTP_REFERER")
                        or reverse(
                            "plugins:speakerops:speakerops_sync_console",
                            kwargs={"event": event},
                        )
                    )
            elif item.status == SyncItem.RUNNING:
                execute(
                    Command(
                        event=self.event,
                        aggregate_model=SyncItem,
                        aggregate_id=item.pk,
                        action="sync.claim.resolve_not_applied",
                        target_state=SyncItem.FAILED,
                        state_machine=SYNC_ITEM_MACHINE,
                    ),
                    request.user,
                    key=f"sync-claim:{claim.pk}:verified-not-applied",
                    expected_version=item.version,
                )
            claim.resolved_by = request.user
            claim.resolution_note = note
            claim.save(update_fields=["resolved_by", "resolution_note", "updated"])
            release_sync_claim(claim, resolution=resolution)
            if claim.receipt_id:
                receipt = claim.receipt
                receipt.result = {
                    **receipt.result,
                    "claim_resolution": resolution,
                    "claim_resolved_by_id": request.user.pk,
                    "claim_resolved_at": timezone.now().isoformat(),
                }
                receipt.save(update_fields=["result", "updated"])
        messages.success(request, "Ambiguous synchronization claim resolved and audited.")
        if claim.receipt_id:
            return redirect(_receipt_url(event, claim.receipt_id))
        return redirect("plugins:speakerops:speakerops_sync_console", event=event)
