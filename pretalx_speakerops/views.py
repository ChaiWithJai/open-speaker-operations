import csv
import logging
import re
import uuid
from urllib.parse import urlencode

from csp.decorators import csp_update
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import TemplateView, View
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.orga.forms.schedule import ScheduleReleaseForm
from pretalx.person.models import User
from pretalx.schedule.models import Room
from pretalx.submission.models import Review, ReviewScore, Submission, SubmissionStates, Track

from .auth import (
    can_manage,
    has_round_assignments,
    is_speaker,
    require_event_permission,
    role_home_url,
    role_navigation,
)
from .cfp_forms import ConditionalQuestionRuleForm, ReviewerPoolForm
from .conference_memory import (
    conference_coverage,
    find_related_talks,
    memory_decision_support,
    resolve_source_identity,
    speaker_memory_summary,
)
from .domain.commands import Command, execute
from .domain.state import StateMachine, Transition
from .integrations.sync import execute_item, execute_preview, preview
from .models import (
    AcceleventsConnection,
    AcceptanceWave,
    CommandReceipt,
    ConditionalQuestionRule,
    ConferenceSeries,
    CRMContact,
    CRMPipelineCard,
    HistoricalIdentityDecision,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalTalk,
    OnboardingTask,
    OutboxEvent,
    ProgramDecision,
    Resource,
    ReviewerPool,
    ReviewRecommendation,
    RoundReviewAssignment,
    SessionPublicationApproval,
    SpeakerMemoryProfile,
    SubmissionPresenterRole,
    SyncItem,
    SyncPreview,
    SyncRun,
    TaskEvidence,
    TransitionLog,
)
from .onboarding.reminders import queue_reminders
from .onboarding.services import record_evidence
from .presenter_roles import presenter_rows
from .program.auto_schedule import apply_schedule_proposal, build_schedule_proposal
from .program.calendar import released_ical
from .program.decisions import (
    finalize_rejections,
    release_acceptance_wave,
    stage_program_decision,
)
from .program.policy import classify_warnings, release_schedule, schedule_slots
from .program.reviews import configure_review_rounds

logger = logging.getLogger(__name__)

TASK_MACHINE = StateMachine(
    states=frozenset(
        {
            OnboardingTask.PENDING,
            OnboardingTask.REOPENED,
            OnboardingTask.COMPLETE,
            OnboardingTask.WAIVED,
        }
    ),
    transitions=(
        Transition(OnboardingTask.PENDING, OnboardingTask.COMPLETE, frozenset({"speaker"})),
        Transition(OnboardingTask.REOPENED, OnboardingTask.COMPLETE, frozenset({"speaker"})),
        Transition(OnboardingTask.COMPLETE, OnboardingTask.REOPENED, frozenset({"organiser"})),
        Transition(OnboardingTask.COMPLETE, OnboardingTask.WAIVED, frozenset({"organiser"})),
        Transition(OnboardingTask.PENDING, OnboardingTask.WAIVED, frozenset({"organiser"})),
        Transition(OnboardingTask.REOPENED, OnboardingTask.WAIVED, frozenset({"organiser"})),
    ),
)

DASHBOARD_SNAPSHOT_SECONDS = 2


def _lifecycle_record_ids(event):
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
    wip_schedule = event.wip_schedule
    scheduled = (
        set(
            wip_schedule.talks.filter(submission__isnull=False, start__isnull=False).values_list(
                "submission_id", flat=True
            )
        )
        if wip_schedule
        else set()
    )
    current_schedule = event.current_schedule
    published = (
        set(
            current_schedule.talks.filter(
                submission__isnull=False, start__isnull=False
            ).values_list("submission_id", flat=True)
        )
        if current_schedule
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


def _gap_explanation(label, prior_label, count, prior_count):
    if count == prior_count:
        return f"All {prior_label} records have {label} evidence."
    if count < prior_count:
        gap = prior_count - count
        return f"{gap} {prior_label} record{'s' if gap != 1 else ''} still need {label} evidence."
    extra = count - prior_count
    return (
        f"{extra} {label} record{'s' if extra != 1 else ''} came from an inherited or "
        f"recovery path without matching {prior_label} evidence."
    )


class EventContextMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        is_orga = request.path.startswith("/orga/")
        with scope(event=self.event):
            if is_orga:
                if self.kwargs.get("kind") == "review":
                    self.permission = "review"
                self.authorize_organiser(request)
            elif not is_speaker(request.user, self.event):
                raise Http404
            return super().dispatch(request, *args, **kwargs)

    def authorize_organiser(self, request):
        permission = getattr(self, "permission", "dashboard")
        if permission == "review":
            require_event_permission(request.user, self.event, "submission.orga_list_submission")
            authorized_events = getattr(request.user, "_speakerops_review_event_ids", set())
            authorized_events.add(self.event.pk)
            request.user._speakerops_review_event_ids = authorized_events
        elif permission == "manage":
            require_event_permission(
                request.user, self.event, "event.update_event", "submission.orga_update_submission"
            )
        else:
            require_event_permission(
                request.user, self.event, "event.update_event", "submission.orga_update_submission"
            )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("event", self.event)
        context["speakerops_navigation"] = role_navigation(
            self.request.user, self.event, self.request.path
        )
        return context


class RoleEntryView(View):
    """Route a signed-in participant to their authorized event workspace."""

    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        if "pretalx_speakerops" not in event.plugin_list:
            raise Http404
        if not request.user.is_authenticated:
            login_url = reverse("cfp:event.login", kwargs={"event": event.slug})
            return redirect(f"{login_url}?{urlencode({'next': request.path})}")
        with scope(event=event):
            destination = role_home_url(request.user, event)
        if not destination:
            raise Http404
        return redirect(destination)


class PublicCfpGuideView(TemplateView):
    template_name = "pretalx_speakerops/cfp_guide.html"

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        if "pretalx_speakerops" not in self.event.plugin_list:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        kwargs["event"] = self.event
        return super().get_context_data(**kwargs)


class ConferenceMemoryView(EventContextMixin, TemplateView):
    permission = "review"
    template_name = "pretalx_speakerops/conference_memory.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        series_slug = self.request.GET.get("series", "").strip()
        timing = self.request.GET.get("timing", "all").strip()
        if timing not in {"all", "past", "upcoming", "undated"}:
            timing = "all"
        talks = HistoricalTalk.objects.select_related("edition__series").prefetch_related(
            "credits__speaker"
        )
        if query:
            talks = talks.filter(
                Q(title__icontains=query)
                | Q(abstract__icontains=query)
                | Q(track__icontains=query)
                | Q(session_format__icontains=query)
                | Q(level__icontains=query)
                | Q(topics__icontains=query)
                | Q(speakers__name__icontains=query)
                | Q(edition__name__icontains=query)
            ).distinct()
        if series_slug:
            talks = talks.filter(edition__series__slug=series_slug)
        today = timezone.localdate()
        if timing == "past":
            talks = talks.filter(edition__date_from__lte=today)
        elif timing == "upcoming":
            talks = talks.filter(edition__date_from__gt=today)
        elif timing == "undated":
            talks = talks.filter(edition__date_from__isnull=True)
        talks = talks.order_by("-edition__date_from", "title")
        result_count = talks.count()
        page = Paginator(talks, 50).get_page(self.request.GET.get("page"))
        context.update(
            event=self.event,
            query=query,
            selected_series=series_slug,
            selected_timing=timing,
            conference_series=ConferenceSeries.objects.prefetch_related("editions"),
            historical_talks=page.object_list,
            page_obj=page,
            result_count=result_count,
            historical_talk_count=HistoricalTalk.objects.count(),
            memory_insights=memory_decision_support(talks),
            coverage_series=conference_coverage(),
        )
        return context


class ConferenceSpeakerView(EventContextMixin, TemplateView):
    permission = "review"
    template_name = "pretalx_speakerops/conference_speaker.html"

    def _speaker(self):
        return get_object_or_404(HistoricalSpeaker, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        speaker = self._speaker()
        profile = (
            SpeakerMemoryProfile.objects.filter(event=self.event, speaker=speaker)
            .select_related("updated_by")
            .first()
        )
        talks = list(
            speaker.historical_talks.select_related("edition__series")
            .prefetch_related("credits__speaker")
            .order_by("-edition__date_from", "title")
        )
        summary = speaker_memory_summary(speaker, talks)
        active_identities = HistoricalSourceIdentity.objects.filter(
            speaker=speaker,
            active=True,
        )
        verified_edition_count = (
            active_identities.filter(resolution_status=HistoricalSourceIdentity.VERIFIED)
            .values("edition_id")
            .distinct()
            .count()
        )
        identity_summary = {
            "source_identity_count": active_identities.count(),
            "verified_edition_count": verified_edition_count,
            "unverified_count": active_identities.exclude(
                resolution_status=HistoricalSourceIdentity.VERIFIED
            ).count(),
            "verified_recurrence": verified_edition_count >= 2,
        }
        for talk in talks:
            credit = next(
                (credit for credit in talk.credits.all() if credit.speaker_id == speaker.pk),
                None,
            )
            talk.speakerops_name_at_source = credit.name_at_source if credit else speaker.name
        identity_query = Q()
        for name in summary["aliases"]:
            identity_query |= Q(submission__speakers__name__iexact=name)
        current_reviews = list(
            Review.objects.filter(
                submission__event=self.event,
            )
            .filter(identity_query)
            .select_related("submission", "user")
            .distinct()
            .order_by("-updated")
        )
        context.update(
            event=self.event,
            speaker=speaker,
            profile=profile,
            memory_summary=summary,
            identity_summary=identity_summary,
            historical_talks=talks,
            current_reviews=current_reviews,
            can_edit_profile=can_manage(self.request.user, self.event),
            crm_contacts=CRMContact.objects.filter(
                organiser=self.event.organiser,
                source_speaker=speaker,
                merged_into__isnull=True,
            ).order_by("name", "pk"),
            source_identities=HistoricalSourceIdentity.objects.filter(
                speaker=speaker,
                active=True,
            )
            .select_related("edition__series")
            .prefetch_related("decisions__actor")
            .order_by("edition__date_from", "edition__name", "source_key"),
            identity_action_choices=HistoricalIdentityDecision.ACTION_CHOICES,
        )
        return context

    def post(self, request, event, pk):
        if not can_manage(request.user, self.event):
            raise Http404
        speaker = self._speaker()
        if request.POST.get("action") == "resolve_identity":
            identity = get_object_or_404(
                HistoricalSourceIdentity,
                pk=request.POST.get("source_identity"),
                speaker=speaker,
                active=True,
            )
            decision_action = request.POST.get("identity_action", "")
            target_key = request.POST.get("target_key", "").strip()
            try:
                with transaction.atomic():
                    if decision_action == HistoricalIdentityDecision.SPLIT:
                        if not target_key:
                            raise ValueError("Split decisions require a new cluster key")
                        if len(target_key) > 200:
                            raise ValueError("Cluster keys must be 200 characters or fewer")
                        if HistoricalSpeaker.objects.filter(canonical_key=target_key).exists():
                            raise ValueError("The split cluster key already exists")
                        resolved_speaker = HistoricalSpeaker.objects.create(
                            canonical_key=target_key,
                            name=identity.display_name,
                            biography="",
                            source_url=identity.source_url,
                            source_updated_at=identity.source_updated_at,
                        )
                    else:
                        resolved_speaker = HistoricalSpeaker.objects.filter(
                            canonical_key=target_key
                        ).first()
                        if not resolved_speaker:
                            raise ValueError("Choose an existing target cluster key")
                    decision = resolve_source_identity(
                        identity,
                        resolved_speaker,
                        actor=request.user,
                        action=decision_action,
                        reason=request.POST.get("reason", ""),
                        evidence_url=request.POST.get("evidence_url", "").strip(),
                    )
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Recorded identity {decision.get_action_display().lower()} decision "
                    f"for {identity.display_name}.",
                )
            return redirect(request.path)
        if request.POST.get("action") == "add_to_crm":
            contact = CRMContact.objects.filter(
                organiser=self.event.organiser,
                source_speaker=speaker,
                merged_into__isnull=True,
            ).first()
            if contact:
                messages.info(request, f"{contact.name} is already linked in organization CRM.")
            else:
                profile = SpeakerMemoryProfile.objects.filter(
                    event=self.event,
                    speaker=speaker,
                ).first()
                contact = CRMContact.objects.create(
                    organiser=self.event.organiser,
                    source_speaker=speaker,
                    name=speaker.name,
                    biography=speaker.biography,
                    tags=profile.tags if profile else [],
                    internal_notes=profile.internal_notes if profile else "",
                )
                CRMPipelineCard.objects.create(
                    organiser=self.event.organiser,
                    contact=contact,
                )
                messages.success(
                    request,
                    f"Added {contact.name} to organization CRM with source provenance. "
                    "Review possible duplicates before outreach.",
                )
            return redirect(
                reverse(
                    "plugins:speakerops:speakerops_crm",
                    kwargs={"event": self.event.slug},
                )
                + f"#crm-contact-{contact.pk}"
            )
        tags = list(
            dict.fromkeys(
                tag.strip()[:80] for tag in request.POST.get("tags", "").split(",") if tag.strip()
            )
        )[:20]
        SpeakerMemoryProfile.objects.update_or_create(
            event=self.event,
            speaker=speaker,
            defaults={
                "tags": tags,
                "internal_notes": request.POST.get("internal_notes", "").strip(),
                "updated_by": request.user,
            },
        )
        messages.success(request, "Speaker CRM context saved; sourced history was not modified.")
        return redirect(request.path)


class ProgramDecisionsView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/program_decisions.html"

    def _review_results(self):
        submissions = list(
            Submission.objects.filter(event=self.event, reviews__isnull=False)
            .prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=Review.objects.select_related("user").prefetch_related(
                        "scores__category"
                    ),
                    to_attr="speakerops_reviews",
                )
            )
            .distinct()
        )
        results = []
        for submission in submissions:
            normalized_scores = []
            for review in submission.speakerops_reviews:
                scores = list(review.scores.all())
                total_weight = sum(score.category.weight for score in scores)
                if review.score is not None and total_weight:
                    normalized_scores.append(float(review.score) / float(total_weight))
            results.append(
                {
                    "submission": submission,
                    "review_count": len(submission.speakerops_reviews),
                    "aggregate": (
                        round(sum(normalized_scores) / len(normalized_scores), 2)
                        if normalized_scores
                        else None
                    ),
                    "reviews": submission.speakerops_reviews,
                }
            )
        descending = self.request.GET.get("sort", "desc") != "asc"
        return sorted(
            results,
            key=lambda item: (
                item["aggregate"] is not None,
                item["aggregate"] or 0,
                item["submission"].title,
            ),
            reverse=descending,
        )

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            with scope(event=self.event):
                results = self._review_results()
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="{self.event.slug}-weighted-review-results.csv"'
            )
            writer = csv.writer(response)
            writer.writerow(["code", "title", "weighted_average", "review_count"])
            for result in results:
                writer.writerow(
                    [
                        result["submission"].code,
                        result["submission"].title,
                        result["aggregate"] if result["aggregate"] is not None else "",
                        result["review_count"],
                    ]
                )
            return response
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            waves = list(
                AcceptanceWave.objects.filter(event=self.event)
                .annotate(
                    decision_count=Count("decisions", filter=Q(decisions__applied_at__isnull=True))
                )
                .order_by("position")
            )
            decisions = list(
                ProgramDecision.objects.filter(event=self.event)
                .select_related("submission", "wave", "decided_by")
                .order_by("status", "wave__position", "submission__title")
            )
            review_results = self._review_results()
        context.update(
            event=self.event,
            waves=waves,
            decisions=decisions,
            review_results=review_results,
        )
        return context

    def post(self, request, event):
        if request.POST.get("confirm") != "yes":
            messages.error(request, "Confirm before changing proposal states or sending mail.")
            return redirect(request.path)
        with scope(event=self.event):
            action = request.POST.get("action")
            if action == "release_wave":
                wave = get_object_or_404(
                    AcceptanceWave, event=self.event, pk=request.POST.get("wave")
                )
                try:
                    released = release_acceptance_wave(wave, request.user)
                except ValidationError as error:
                    messages.error(request, "; ".join(error.messages))
                else:
                    if released:
                        messages.success(
                            request,
                            f"Released {released} staged acceptance"
                            f"{'s' if released != 1 else ''} and queued the native speaker "
                            f"notification{'s' if released != 1 else ''}.",
                        )
                    else:
                        messages.info(
                            request,
                            "No staged acceptances were released; no speaker notifications "
                            "were queued.",
                        )
            elif action == "finalize_rejections":
                finalized = finalize_rejections(self.event, request.user)
                if finalized:
                    messages.success(
                        request,
                        f"Finalized {finalized} staged rejection"
                        f"{'s' if finalized != 1 else ''} and queued the native speaker "
                        f"notification{'s' if finalized != 1 else ''}.",
                    )
                else:
                    messages.info(
                        request,
                        "No staged rejections were finalized; no speaker notifications "
                        "were queued.",
                    )
            else:
                messages.error(request, "Choose a valid program decision action.")
        return redirect(request.path)


class CfpRoutingView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/cfp_routing.html"

    def _rule(self):
        rule_id = self.request.POST.get("rule_id") or self.request.GET.get("rule")
        if not rule_id:
            return None
        return get_object_or_404(ConditionalQuestionRule, event=self.event, pk=rule_id)

    def _pool(self):
        pool_id = self.request.POST.get("pool_id") or self.request.GET.get("pool")
        if not pool_id:
            return None
        return get_object_or_404(ReviewerPool, event=self.event, pk=pool_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event"] = self.event
        with scope(event=self.event):
            selected_rule = getattr(self, "selected_rule", None) or self._rule()
            selected_pool = getattr(self, "selected_pool", None) or self._pool()
            context.update(
                rules=ConditionalQuestionRule.objects.filter(event=self.event).select_related(
                    "controller_question", "trigger_option", "target_question"
                ),
                pools=ReviewerPool.objects.filter(event=self.event).prefetch_related(
                    "reviewers", "track_mappings__track"
                ),
                selected_rule=selected_rule,
                selected_pool=selected_pool,
                rule_form=getattr(self, "rule_form", None)
                or ConditionalQuestionRuleForm(event=self.event, instance=selected_rule),
                pool_form=getattr(self, "pool_form", None)
                or ReviewerPoolForm(event=self.event, pool=selected_pool),
            )
        return context

    def post(self, request, event):
        with scope(event=self.event):
            action = request.POST.get("action")
            if action == "save_rule":
                self.selected_rule = self._rule()
                self.rule_form = ConditionalQuestionRuleForm(
                    request.POST, event=self.event, instance=self.selected_rule
                )
                if self.rule_form.is_valid():
                    rule = self.rule_form.save()
                    messages.success(request, "Conditional CFP rule saved.")
                    return redirect(f"{request.path}?rule={rule.pk}")
            elif action == "save_pool":
                self.selected_pool = self._pool()
                self.pool_form = ReviewerPoolForm(
                    request.POST, event=self.event, pool=self.selected_pool
                )
                if self.pool_form.is_valid():
                    pool = self.pool_form.save()
                    messages.success(request, "Reviewer pool and category routes saved.")
                    return redirect(f"{request.path}?pool={pool.pk}")
            else:
                messages.error(request, "Choose a valid CFP routing action.")
        return self.get(request, event)


class DashboardView(EventContextMixin, TemplateView):
    permission = "dashboard"
    template_name = "pretalx_speakerops/dashboard.html"

    def _lifecycle(self, record_ids):
        stages = (
            ("submitted", "submitted"),
            ("reviewed", "review"),
            ("decided", "decision"),
            ("onboarded", "completed onboarding"),
            ("scheduled", "schedule"),
            ("published", "publication"),
            ("synchronized", "synchronization"),
        )
        denominator = len(record_ids["submitted"])
        result = []
        previous_key = None
        for key, evidence_label in stages:
            count = len(record_ids[key])
            explanation = (
                "This is the denominator for every downstream program stage."
                if previous_key is None
                else _gap_explanation(
                    evidence_label,
                    previous_key,
                    count,
                    len(record_ids[previous_key]),
                )
            )
            result.append(
                {
                    "key": key,
                    "label": key.title(),
                    "count": count,
                    "denominator": denominator,
                    "explanation": explanation,
                    "url": reverse(
                        "plugins:speakerops:speakerops_drilldown",
                        kwargs={"event": self.event.slug, "kind": key},
                    ),
                }
            )
            previous_key = key
        return result

    def _attention_items(self, record_ids, overdue_tasks, conflicts, failed_sync_items):
        items = []
        definitions = (
            (
                bool(conflicts),
                "Critical",
                0,
                f"{conflicts} schedule conflict{'s' if conflicts != 1 else ''}",
                "Publication is server-blocked until the overlapping records clear.",
                "Program chair",
                reverse("plugins:speakerops:speakerops_agenda", kwargs={"event": self.event.slug}),
                "Resolve conflicts",
            ),
        )
        for active, severity, rank, title, reason, owner, url, action in definitions:
            if active:
                items.append(
                    {
                        "severity": severity,
                        "rank": rank,
                        "title": title,
                        "reason": reason,
                        "owner": owner,
                        "url": url,
                        "action": action,
                    }
                )
        for task in overdue_tasks:
            items.append(
                {
                    "severity": "High",
                    "rank": 1,
                    "title": f"{task.definition.name} · {task.speaker.get_display_name()}",
                    "reason": (
                        f"Due {task.due_date.isoformat()}; required evidence is still unresolved."
                    ),
                    "owner": "Speaker + program operator",
                    "url": (
                        reverse(
                            "plugins:speakerops:speakerops_drilldown",
                            kwargs={"event": self.event.slug, "kind": "tasks"},
                        )
                        + f"#task-{task.pk}"
                    ),
                    "action": "Resolve this task",
                }
            )
        for item in failed_sync_items:
            record_name = (
                f"{item.payload.get('firstName', '')} {item.payload.get('lastName', '')}".strip()
                if item.local_type == "speaker"
                else item.payload.get("title", item.local_type.replace("_", " ").title())
            )
            items.append(
                {
                    "severity": "High",
                    "rank": 1,
                    "title": f"Synchronization failed · {record_name}",
                    "reason": "Retry only this failed record; successful writes remain preserved.",
                    "owner": "Integration operator",
                    "url": (
                        reverse(
                            "plugins:speakerops:speakerops_sync_console",
                            kwargs={"event": self.event.slug},
                        )
                        + f"#sync-item-{item.pk}"
                    ),
                    "action": "Retry this record",
                }
            )
        reviewed_undecided = len(record_ids["reviewed"] - record_ids["decided"])
        if reviewed_undecided:
            items.append(
                {
                    "severity": "Medium",
                    "rank": 2,
                    "title": f"{reviewed_undecided} reviewed proposal"
                    f"{'s' if reviewed_undecided != 1 else ''} without a recorded decision",
                    "reason": "Review evidence exists, but no staged chair decision reconciles it.",
                    "owner": "Program chair",
                    "url": reverse(
                        "plugins:speakerops:speakerops_program_decisions",
                        kwargs={"event": self.event.slug},
                    ),
                    "action": "Stage program decisions",
                }
            )
        return sorted(items, key=lambda item: (item["rank"], item["title"]))

    def _recent_evidence(self):
        transition_rows = list(
            TransitionLog.objects.filter(event=self.event)
            .select_related("actor")
            .order_by("-timestamp")[:4]
        )
        task_ids = [
            item.aggregate_id
            for item in transition_rows
            if item.aggregate_type.rsplit(".", 1)[-1].lower() == "onboardingtask"
        ]
        task_map = {
            task.pk: task
            for task in OnboardingTask.objects.filter(pk__in=task_ids).select_related(
                "speaker", "definition"
            )
        }
        transitions = []
        for item in transition_rows:
            task = task_map.get(item.aggregate_id)
            label = (
                f"{task.definition.name} for {task.speaker.get_display_name()}: "
                f"{item.from_state or 'created'} → {item.to_state}"
                if task
                else f"Operational record: {item.from_state or 'created'} → {item.to_state}"
            )
            transitions.append(
                {
                    "kind": "Speaker task" if task else "Transition",
                    "label": label,
                    "actor": item.actor.get_display_name() if item.actor else "System",
                    "timestamp": item.timestamp,
                    "url": (
                        reverse(
                            "plugins:speakerops:speakerops_drilldown",
                            kwargs={"event": self.event.slug, "kind": "tasks"},
                        )
                        + f"#task-{task.pk}"
                        if task
                        else ""
                    ),
                }
            )
        sync_runs = [
            {
                "kind": "Synchronization",
                "label": f"Recovery finished with {run.status.replace('_', ' ')} status",
                "actor": "Integration operator",
                "timestamp": run.finished_at or run.started_at or run.created,
                "url": reverse(
                    "plugins:speakerops:speakerops_sync_console",
                    kwargs={"event": self.event.slug},
                )
                + f"#sync-run-{run.pk}",
            }
            for run in SyncRun.objects.filter(event=self.event).order_by("-created")[:3]
        ]
        return sorted(transitions + sync_runs, key=lambda item: item["timestamp"], reverse=True)[:6]

    def _snapshot(self):
        today = timezone.localdate()
        tasks = OnboardingTask.objects.filter(event=self.event)
        proposals = Submission.objects.filter(event=self.event)
        schedule = self.event.wip_schedule
        conflicts = len(classify_warnings(schedule)) if schedule else 0
        active_states = (OnboardingTask.PENDING, OnboardingTask.REOPENED)
        task_stats = tasks.aggregate(
            active=Count("pk", filter=Q(status__in=active_states)),
            overdue=Count("pk", filter=Q(due_date__lt=today, status__in=active_states)),
            missing_assets=Count(
                "pk",
                filter=Q(
                    definition__completion_evaluator="upload",
                    status__in=active_states,
                ),
            ),
        )
        pending_content = TaskEvidence.objects.filter(
            event=self.event,
            upload__isnull=False,
            review_status=TaskEvidence.PENDING,
        ).count()
        proposal_stats = proposals.aggregate(
            total=Count("pk", distinct=True),
            undecided=Count("pk", filter=Q(state=SubmissionStates.SUBMITTED), distinct=True),
            reviewed=Count("pk", filter=Q(reviews__isnull=False), distinct=True),
        )
        sync_error_count = SyncItem.objects.filter(event=self.event, status=SyncItem.FAILED).count()
        overdue_tasks = list(
            tasks.filter(due_date__lt=today, status__in=active_states)
            .select_related("speaker", "definition")
            .order_by("due_date", "pk")
        )
        failed_sync_items = list(
            SyncItem.objects.filter(event=self.event, status=SyncItem.FAILED).order_by(
                "-updated", "pk"
            )
        )
        lifecycle_ids = _lifecycle_record_ids(self.event)
        return {
            "counts": {
                "tasks": task_stats["active"],
                "undecided": proposal_stats["undecided"],
                "reviewed": proposal_stats["reviewed"],
                "proposals": proposal_stats["total"],
                "conflicts": conflicts,
                "missing_assets": task_stats["missing_assets"],
                "pending_content": pending_content,
                "sync": sync_error_count,
                "sync_status": (
                    AcceleventsConnection.objects.filter(event=self.event)
                    .values_list("status", flat=True)
                    .first()
                    or "not configured"
                ),
                "due_reminders": task_stats["overdue"],
            },
            "attention": {
                "overdue": task_stats["overdue"],
                "blocked_release": conflicts > 0,
                "sync_errors": sync_error_count,
            },
            "lifecycle": self._lifecycle(lifecycle_ids),
            "attention_items": self._attention_items(
                lifecycle_ids, overdue_tasks, conflicts, failed_sync_items
            ),
            "recent_evidence": self._recent_evidence(),
        }

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            snapshot = cache.get_or_set(
                f"speakerops:dashboard:{self.event.pk}",
                self._snapshot,
                DASHBOARD_SNAPSHOT_SECONDS,
            )
            context.update(event=self.event, **snapshot)
            return context


class DrilldownView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/drilldown.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        kind = self.kwargs["kind"]
        with scope(event=self.event):
            if kind == "tasks":
                rows = list(
                    OnboardingTask.objects.filter(
                        event=self.event,
                        status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                    )
                    .select_related("speaker", "definition", "submission")
                    .order_by("due_date", "pk")
                )
            elif kind == "content":
                rows = list(
                    OnboardingTask.objects.filter(
                        event=self.event,
                        definition__completion_evaluator="upload",
                        evidence_items__isnull=False,
                    )
                    .select_related("speaker", "definition", "submission")
                    .prefetch_related(
                        Prefetch(
                            "evidence_items",
                            queryset=TaskEvidence.objects.select_related("reviewed_by").order_by(
                                "-version"
                            ),
                            to_attr="speakerops_evidence_items",
                        )
                    )
                    .distinct()
                    .order_by("speaker__name", "definition__position", "pk")
                )
            elif kind == "undecided":
                rows = list(
                    Submission.objects.filter(event=self.event, state=SubmissionStates.SUBMITTED)
                )
            elif kind in {"review", "reviewed"}:
                review_rows = Submission.objects.filter(event=self.event, reviews__isnull=False)
                if not self.request.user.has_perm("submission.orga_update_submission", self.event):
                    review_rows = review_rows.filter(reviews__user=self.request.user)
                rows = list(review_rows.distinct())
            elif kind == "missing-assets":
                rows = list(
                    OnboardingTask.objects.filter(
                        event=self.event,
                        definition__completion_evaluator="upload",
                        status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
                    )
                    .select_related("speaker", "definition", "submission")
                    .order_by("due_date", "pk")
                )
            elif kind in {"sync", "conflicts"}:
                if kind == "conflicts":
                    schedule = self.event.wip_schedule
                    rows = classify_warnings(schedule) if schedule else []
                else:
                    rows = list(
                        SyncItem.objects.filter(event=self.event, status=SyncItem.FAILED)
                        .select_related("run")
                        .order_by("-updated")
                    )
            elif kind in {
                "submitted",
                "reviewed",
                "decided",
                "onboarded",
                "scheduled",
                "published",
                "synchronized",
            }:
                rows = list(
                    Submission.objects.filter(
                        event=self.event, pk__in=_lifecycle_record_ids(self.event)[kind]
                    )
                )
            else:
                rows = []
        context.update(event=self.event, kind=kind, rows=rows, today=timezone.localdate())
        return context


class ChecklistView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/checklist.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event"] = self.event
        with scope(event=self.event):
            tasks = list(
                OnboardingTask.objects.filter(event=self.event, speaker=self.request.user)
                .select_related("definition", "submission")
                .prefetch_related(
                    Prefetch(
                        "evidence_items",
                        queryset=TaskEvidence.objects.prefetch_related("comments__author").order_by(
                            "-created_at"
                        ),
                        to_attr="speakerops_evidence_items",
                    )
                )
                .order_by("status", "due_date", "definition__position", "id")
            )
        today = timezone.localdate()
        pending, complete, waived = [], [], []
        for t in tasks:
            t.upload_request_id = uuid.uuid4().hex
            if t.status == OnboardingTask.COMPLETE:
                complete.append(t)
            elif t.status == OnboardingTask.WAIVED:
                waived.append(t)
            else:
                pending.append(t)
        context["tasks"] = tasks
        context["pending"] = pending
        context["complete"] = complete
        context["waived"] = waived
        context["today"] = today
        total = len(tasks)
        done = len(complete) + len(waived)
        context["progress"] = {"total": total, "done": done}
        return context


class SpeakerSubmissionPresentersView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/submission_presenters.html"

    def _submission(self, *, lock=False):
        submissions = Submission.objects.filter(
            event=self.event,
            code__iexact=self.kwargs["code"],
            speakers=self.request.user,
        ).prefetch_related("speakers", "speakerops_presenter_roles__speaker")
        if lock:
            submissions = submissions.select_for_update()
        # The native submission-speaker through table is unique per speaker, so this
        # filter cannot duplicate a submission. Avoid DISTINCT here because the POST
        # path also applies SELECT FOR UPDATE, a combination PostgreSQL rejects.
        return get_object_or_404(submissions)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        submission = self._submission()
        context.update(
            submission=submission,
            presenters=presenter_rows(submission),
            role_choices=SubmissionPresenterRole.ROLE_CHOICES,
        )
        return context

    def post(self, request, event, code):
        with transaction.atomic(), scope(event=self.event):
            submission = self._submission(lock=True)
            speakers = list(submission.speakers.order_by("pk"))
            choices = dict(SubmissionPresenterRole.ROLE_CHOICES)
            selected = {
                speaker.pk: request.POST.get(f"role_{speaker.pk}", "") for speaker in speakers
            }
            if any(role not in choices for role in selected.values()):
                messages.error(request, "Choose a valid role for every attached presenter.")
                return redirect(request.path)
            if list(selected.values()).count(SubmissionPresenterRole.PRIMARY_AUTHOR) != 1:
                messages.error(request, "Choose exactly one primary author.")
                return redirect(request.path)
            SubmissionPresenterRole.objects.filter(
                event=self.event,
                submission=submission,
                role=SubmissionPresenterRole.PRIMARY_AUTHOR,
            ).update(role=SubmissionPresenterRole.CO_PRESENTER)
            for speaker in speakers:
                SubmissionPresenterRole.objects.update_or_create(
                    event=self.event,
                    submission=submission,
                    speaker=speaker,
                    defaults={"role": selected[speaker.pk]},
                )
        messages.success(request, "Presenter role labels saved.")
        return redirect(request.path)


class ReviewerScoringView(EventContextMixin, TemplateView):
    permission = "review"
    template_name = "pretalx_speakerops/reviewer_scoring.html"

    def _round_review_destination(self):
        assignments = RoundReviewAssignment.objects.filter(
            event=self.event,
            reviewer=self.request.user,
        ).exclude(status=RoundReviewAssignment.RECUSED)
        if not has_round_assignments(self.request.user, self.event):
            return None
        if submission_id := self.kwargs.get("pk"):
            assignment = (
                assignments.filter(submission_id=submission_id)
                .order_by("round__position", "pk")
                .first()
            )
            if assignment:
                return reverse(
                    "plugins:speakerops:speakerops_round_review",
                    kwargs={"event": self.event.slug, "assignment": assignment.pk},
                )
        return reverse(
            "plugins:speakerops:speakerops_round_review_queue",
            kwargs={"event": self.event.slug},
        )

    def get(self, request, *args, **kwargs):
        with scope(event=self.event):
            if destination := self._round_review_destination():
                return redirect(destination)
        return super().get(request, *args, **kwargs)

    def _queue(self):
        queue = Submission.objects.filter(
            event=self.event,
            state=SubmissionStates.SUBMITTED,
        )
        if not self.request.user.has_perm("submission.orga_update_submission", self.event):
            queue = queue.filter(assigned_reviewers=self.request.user)
        return queue.distinct().order_by("title")

    def _submission(self, queue=None):
        queue = list(self._queue()) if queue is None else queue
        if self.kwargs.get("pk"):
            requested = int(self.kwargs["pk"])
            submission = next(
                (submission for submission in queue if submission.pk == requested), None
            )
            if submission is None:
                raise Http404
            return submission
        return queue[0] if queue else None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            configure_review_rounds(self.event)
            queue = list(self._queue())
            submission = self._submission(queue)
            review = None
            recommendation = None
            program_decision = None
            historical_matches = []
            criteria = []
            if submission:
                review = (
                    Review.objects.filter(submission=submission, user=self.request.user)
                    .prefetch_related("scores")
                    .first()
                )
                selected = (
                    {score.category_id: score.pk for score in review.scores.all()} if review else {}
                )
                criteria = [
                    {
                        "category": category,
                        "options": category.speakerops_score_options,
                        "selected": selected.get(category.pk),
                    }
                    for category in submission.score_categories.prefetch_related(
                        Prefetch(
                            "scores",
                            queryset=ReviewScore.objects.order_by("value"),
                            to_attr="speakerops_score_options",
                        )
                    )
                ]
                recommendation = ReviewRecommendation.objects.filter(
                    event=self.event,
                    submission=submission,
                    reviewer=self.request.user,
                ).first()
                program_decision = ProgramDecision.objects.filter(
                    event=self.event, submission=submission
                ).first()
                historical_matches = find_related_talks(submission)
            acceptance_waves = list(
                AcceptanceWave.objects.filter(event=self.event).order_by("position")
            )
            next_submission = None
            if submission and len(queue) > 1:
                next_submission = queue[(queue.index(submission) + 1) % len(queue)]
            presenters = (
                presenter_rows(submission)
                if submission and can_manage(self.request.user, self.event)
                else []
            )
        context.update(
            event=self.event,
            queue=queue,
            submission=submission,
            review=review,
            criteria=criteria,
            recommendation=recommendation,
            recommendation_choices=ReviewRecommendation.CHOICES,
            program_decision=program_decision,
            program_decision_choices=ProgramDecision.STATUS_CHOICES,
            acceptance_waves=acceptance_waves,
            can_decide=can_manage(self.request.user, self.event),
            historical_matches=historical_matches,
            next_submission=next_submission,
            presenters=presenters,
        )
        return context

    def post(self, request, event, pk=None):
        with scope(event=self.event):
            if destination := self._round_review_destination():
                return redirect(destination)
            configure_review_rounds(self.event)
            submission = self._submission()
            if not submission:
                raise Http404
            if request.POST.get("decision_action") == "stage":
                if not can_manage(request.user, self.event):
                    raise Http404
                wave = None
                if wave_pk := request.POST.get("wave"):
                    wave = get_object_or_404(AcceptanceWave, event=self.event, pk=wave_pk)
                try:
                    stage_program_decision(
                        submission,
                        request.POST.get("program_decision", ""),
                        request.user,
                        wave=wave,
                        rationale=request.POST.get("decision_rationale", ""),
                    )
                except ValidationError as error:
                    messages.error(request, "; ".join(error.messages))
                else:
                    messages.success(
                        request,
                        "Program decision staged. No speaker notification has been sent.",
                    )
                return redirect(request.path)
            with transaction.atomic():
                recommendation, _ = ReviewRecommendation.objects.select_for_update().get_or_create(
                    event=self.event,
                    submission=submission,
                    reviewer=request.user,
                )
                save_session = request.POST.get("save_session", "")[:64]
                try:
                    client_revision = max(0, int(request.POST.get("client_revision", 0)))
                except (TypeError, ValueError):
                    client_revision = 0
                try:
                    save_version = max(0, int(request.POST.get("save_version", 0)))
                except (TypeError, ValueError):
                    save_version = 0
                if (
                    save_session
                    and recommendation.save_session == save_session
                    and client_revision <= recommendation.client_revision
                ):
                    return JsonResponse(
                        {
                            "saved": True,
                            "stale": True,
                            "revision": recommendation.client_revision,
                            "save_version": recommendation.save_version,
                            "updated": recommendation.updated,
                        }
                    )
                if save_session and save_version != recommendation.save_version:
                    return JsonResponse(
                        {
                            "saved": False,
                            "conflict": True,
                            "error": (
                                "A newer review was saved in another tab or browser. "
                                "Reload to compare it before retrying."
                            ),
                            "save_version": recommendation.save_version,
                            "updated": recommendation.updated,
                        },
                        status=409,
                    )
                review, _ = Review.objects.get_or_create(
                    submission=submission,
                    user=request.user,
                )
                chosen_scores = []
                for category in submission.score_categories:
                    score_pk = request.POST.get(f"score_{category.pk}")
                    if score_pk:
                        chosen_scores.append(
                            get_object_or_404(ReviewScore, pk=score_pk, category=category)
                        )
                review.text = request.POST.get("comments", "").strip()
                review.save(update_score=False)
                review.scores.set(chosen_scores)
                review.save()
                recommendation_value = request.POST.get("recommendation", ReviewRecommendation.HOLD)
                if recommendation_value not in dict(ReviewRecommendation.CHOICES):
                    recommendation_value = ReviewRecommendation.HOLD
                recommendation.recommendation = recommendation_value
                if save_session:
                    recommendation.save_session = save_session
                    recommendation.client_revision = client_revision
                    recommendation.save_version += 1
                recommendation.save()
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "saved": True,
                    "score": review.display_score,
                    "revision": recommendation.client_revision,
                    "save_version": recommendation.save_version,
                    "updated": recommendation.updated,
                }
            )
        messages.success(request, "Review saved.")
        return redirect(
            reverse(
                "plugins:speakerops:speakerops_review",
                kwargs={"event": event, "pk": submission.pk},
            )
        )


class AgendaReleaseView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/agenda_release.html"
    MAX_ROOM_CAPACITY = 2_147_483_647

    def _next_release_name(self):
        base = "SpeakerOps release"
        used = {
            name.casefold()
            for name in self.event.schedules.exclude(version__isnull=True).values_list(
                "version", flat=True
            )
        }
        if base.casefold() not in used:
            return base
        suffix = 2
        while f"{base} {suffix}".casefold() in used:
            suffix += 1
        return f"{base} {suffix}"

    def _conflict_feedback(self, blocking):
        session_key = f"speakerops:agenda-conflicts:{self.event.pk}"
        current_keys = {warning["conflict_key"] for warning in blocking}
        previous_keys = set(self.request.session.get(session_key, []))
        feedback = None
        if self.request.GET.get("recheck") == "1":
            cleared = previous_keys - current_keys
            if not current_keys:
                feedback = {
                    "cleared": True,
                    "title": "Conflict check complete · release gate clear",
                    "message": (
                        f"{len(cleared)} conflict{'' if len(cleared) == 1 else 's'} "
                        "cleared. The server found no remaining room or speaker conflicts."
                    ),
                }
            elif cleared:
                feedback = {
                    "cleared": False,
                    "title": "Conflict check complete · still blocked",
                    "message": (
                        f"{len(cleared)} conflict{'' if len(cleared) == 1 else 's'} "
                        f"cleared; {len(current_keys)} still block"
                        f"{'' if len(current_keys) != 1 else 's'} release."
                    ),
                }
            else:
                feedback = {
                    "cleared": False,
                    "title": "No conflicts cleared · still blocked",
                    "message": (
                        f"The server still finds {len(current_keys)} blocking conflict"
                        f"{'' if len(current_keys) == 1 else 's'}. Edit a session and recheck."
                    ),
                }
        self.request.session[session_key] = sorted(current_keys)
        return feedback

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            schedule = self.event.wip_schedule
            slots = schedule_slots(schedule) if schedule else []
            scheduled_submission_ids = {
                slot.submission_id for slot in slots if slot.submission_id is not None
            }
            unscheduled = list(
                Submission.objects.filter(event=self.event, state=SubmissionStates.ACCEPTED)
                .exclude(pk__in=scheduled_submission_ids)
                .select_related("track")
                .prefetch_related("speakers")
                .order_by("title", "pk")
            )
            warnings = classify_warnings(schedule, slots=slots) if schedule else []
            for warning in warnings:
                warning["resolve_url"] = warning["talk"].submission.orga_urls.quick_schedule
                warning["competitor_resolve_url"] = warning[
                    "competitor"
                ].submission.orga_urls.quick_schedule
        blocking = [warning for warning in warnings if warning["blocking"]]
        context.update(
            event=self.event,
            schedule=schedule,
            slots=slots,
            rooms=self.event.rooms.order_by("position", "name"),
            tracks=self.event.tracks.order_by("position", "name"),
            unscheduled=unscheduled,
            warnings=warnings,
            blocking=blocking,
            release_name=self._next_release_name(),
            gate_feedback=self._conflict_feedback(blocking),
            proposed_placements=kwargs.get("proposed_placements"),
            can_edit_structure=self.request.user.is_administrator
            or self.request.user.has_perm("event.update_event", self.event),
        )
        return context

    def _create_room(self, request):
        require_event_permission(request.user, self.event, "event.update_event")
        name = request.POST.get("room_name", "").strip()
        capacity_raw = request.POST.get("room_capacity", "").strip()
        if not name:
            messages.error(request, "Room name is required.")
            return redirect(f"{request.path}#program-setup")
        if capacity_raw and (
            not capacity_raw.isdigit() or int(capacity_raw) > self.MAX_ROOM_CAPACITY
        ):
            messages.error(request, "Room capacity must be a whole number within range.")
            return redirect(f"{request.path}#program-setup")
        with scope(event=self.event):
            if any(str(room.name).casefold() == name.casefold() for room in self.event.rooms.all()):
                messages.error(request, f"A room named {name} already exists.")
                return redirect(f"{request.path}#program-setup")
            Room.objects.create(
                event=self.event,
                name=name,
                capacity=int(capacity_raw) if capacity_raw else None,
            )
        messages.success(request, f"Room {name} added and ready for scheduling.")
        return redirect(f"{request.path}#program-setup")

    def _create_track(self, request):
        require_event_permission(request.user, self.event, "event.update_event")
        name = request.POST.get("track_name", "").strip()
        color = request.POST.get("track_color", "").strip() or "#3aa57c"
        if not name:
            messages.error(request, "Track name is required.")
            return redirect(f"{request.path}#program-setup")
        if not re.fullmatch(r"#([0-9A-Fa-f]{3}){1,2}", color):
            messages.error(request, "Track colour must be a hex value like #3aa57c.")
            return redirect(f"{request.path}#program-setup")
        with scope(event=self.event):
            if any(
                str(track.name).casefold() == name.casefold() for track in self.event.tracks.all()
            ):
                messages.error(request, f"A track named {name} already exists.")
                return redirect(f"{request.path}#program-setup")
            Track.objects.create(event=self.event, name=name, color=color)
        messages.success(request, f"Track {name} added and ready for submissions.")
        return redirect(f"{request.path}#program-setup")

    def post(self, request, event):
        action = request.POST.get("action")
        if action == "create_room":
            return self._create_room(request)
        if action == "create_track":
            return self._create_track(request)
        if action == "preview_assisted_schedule":
            try:
                with scope(event=self.event):
                    proposal = build_schedule_proposal(self.event.wip_schedule)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
                return redirect(request.path)
            context = self.get_context_data(proposed_placements=proposal)
            return self.render_to_response(context)
        if action == "apply_assisted_schedule":
            if request.POST.get("confirm_assisted_schedule") != "yes":
                messages.error(request, "Confirm the assisted agenda proposal first.")
                return redirect(request.path)
            try:
                with scope(event=self.event):
                    placements, changed = apply_schedule_proposal(self.event.wip_schedule)
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
            else:
                messages.success(
                    request,
                    f"Assisted agenda applied: {len(placements)} sessions placed, "
                    f"{changed} changed, zero room or speaker overlaps.",
                )
            return redirect(f"{request.path}?recheck=1#conflicts")
        if request.POST.get("confirm_release") != "yes":
            messages.error(request, "Confirm the public schedule release first.")
            return redirect(request.path)
        with scope(event=self.event):
            schedule = self.event.wip_schedule
            default_release_name = self._next_release_name()
            release_name = (
                request.POST.get("name", default_release_name).strip() or default_release_name
            )
            release_form = ScheduleReleaseForm(
                data={
                    "version": release_name,
                    "comment": "",
                    "notify_speakers": False,
                },
                event=self.event,
                locales=self.event.locales,
            )
            if not release_form.is_valid():
                error_text = " ".join(
                    str(error) for errors in release_form.errors.values() for error in errors
                )
                messages.error(request, error_text or "Choose a valid schedule revision name.")
                return redirect(request.path)
            try:
                release_schedule(
                    schedule,
                    release_form.cleaned_data["version"],
                    request.user,
                    notify_speakers=release_form.cleaned_data["notify_speakers"],
                    comment=release_form.cleaned_data["comment"],
                )
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
            except Exception:
                logger.exception(
                    "Schedule release failed for event %s",
                    self.event.slug,
                )
                messages.error(
                    request,
                    "The schedule could not be released. No release was published; "
                    "review the draft and try again.",
                )
            else:
                messages.success(request, "Schedule released.")
        return redirect(request.path)


def _accepted_speaker_payloads(event):
    speaker_ids = Submission.objects.filter(
        event=event, state=SubmissionStates.ACCEPTED
    ).values_list("speakers", flat=True)
    return [
        (
            "speaker",
            speaker.pk,
            {
                "firstName": (speaker.name or "Speaker").split(" ", 1)[0],
                "lastName": (speaker.name or "Speaker").split(" ", 1)[-1],
                "email": speaker.email,
            },
        )
        for speaker in User.objects.filter(pk__in=speaker_ids)
    ]


class SyncConsoleView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/sync_console.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            connection = AcceleventsConnection.objects.filter(event=self.event).first()
            previews = list(
                SyncPreview.objects.filter(event=self.event).order_by("-created_at")[:5]
            )
            runs = list(
                SyncRun.objects.filter(event=self.event)
                .select_related("preview")
                .prefetch_related("items__attempt_history")
                .order_by("-created")[:10]
            )
        context.update(event=self.event, connection=connection, previews=previews, runs=runs)
        return context

    def post(self, request, event):
        action = request.POST.get("action")
        with scope(event=self.event):
            if action == "preview":
                preview(self.event, _accepted_speaker_payloads(self.event))
                messages.success(request, "Synchronization preview created.")
            elif action == "run" and request.POST.get("confirm_sync") == "yes":
                try:
                    execute_preview(self.event, request.POST["preview_id"], request.user)
                except (ValueError, KeyError) as error:
                    messages.error(request, str(error))
                else:
                    messages.success(request, "Synchronization run created.")
            elif action == "retry" and request.POST.get("confirm_sync") == "yes":
                item = get_object_or_404(
                    SyncItem,
                    pk=request.POST.get("item_id"),
                    event=self.event,
                    status=SyncItem.FAILED,
                )
                execute_item(item, request.user)
                messages.success(request, "Failed item retried.")
            else:
                messages.error(request, "Choose an action and confirm external writes.")
        return redirect(request.path)


class CompleteTaskView(EventContextMixin, View):
    def post(self, request, event, pk):
        task = get_object_or_404(OnboardingTask, pk=pk, event=self.event, speaker=request.user)
        request_id = request.POST.get("upload_request_id", "")[:64]
        key = f"task:{task.pk}:evidence:{request_id}" if request_id else f"task:{task.pk}:complete"
        evidence = None
        with transaction.atomic():
            if CommandReceipt.objects.filter(event=self.event, key=key).exists():
                complete = True
                evidence = (
                    task.evidence_items.filter(upload__isnull=False).order_by("-created_at").first()
                )
            else:
                upload = request.FILES.get("upload")
                value = {"response": request.POST.get("response", "")}
                try:
                    evidence, complete = record_evidence(
                        task,
                        request.user,
                        task.definition.completion_evaluator,
                        value=value,
                        upload=upload,
                    )
                except ValueError as error:
                    if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse({"saved": False, "error": str(error)}, status=400)
                    messages.error(request, str(error))
                    return redirect(
                        reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event})
                    )
            if not complete:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "saved": False,
                            "error": "The supplied evidence does not complete this task.",
                        },
                        status=400,
                    )
                messages.error(request, "The supplied evidence does not complete this task.")
                return redirect(
                    reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event})
                )
            if task.status != OnboardingTask.COMPLETE:
                execute(
                    Command(
                        event=self.event,
                        aggregate_model=OnboardingTask,
                        aggregate_id=task.pk,
                        action="onboarding.complete",
                        target_state=OnboardingTask.COMPLETE,
                        state_machine=TASK_MACHINE,
                        actor_role="speaker",
                    ),
                    request.user,
                    key=key,
                    expected_version=task.version,
                )
            elif not CommandReceipt.objects.filter(event=self.event, key=key).exists():
                CommandReceipt.objects.create(
                    event=self.event,
                    key=key,
                    command="evidence.replace",
                    aggregate_type="TaskEvidence",
                    aggregate_id=evidence.pk,
                    result={"evidence_id": evidence.pk, "version": evidence.version},
                )
        messages.success(
            request,
            "File version submitted for organizer review."
            if evidence and evidence.upload
            else "Task completed.",
        )
        redirect_url = reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event})
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "saved": True,
                    "redirect": redirect_url,
                    "filename": (
                        evidence.upload.name.rsplit("/", 1)[-1]
                        if evidence and evidence.upload
                        else ""
                    ),
                    "created_at": evidence.created_at if evidence else timezone.now(),
                }
            )
        return redirect(redirect_url)


class TaskAdminView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk, action):
        task = get_object_or_404(OnboardingTask, pk=pk, event=self.event)
        if action == "reopen":
            target = OnboardingTask.REOPENED
        elif action == "waive" and request.POST.get("reason", "").strip():
            target = OnboardingTask.WAIVED
            task.waiver_reason = request.POST["reason"].strip()
            task.save(update_fields=["waiver_reason", "updated"])
        else:
            messages.error(request, "A waiver reason is required.")
            return redirect(
                reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event})
            )
        execute(
            Command(
                event=self.event,
                aggregate_model=OnboardingTask,
                aggregate_id=task.pk,
                action=f"onboarding.{action}",
                target_state=target,
                state_machine=TASK_MACHINE,
                actor_role="organiser",
                payload={"reason": request.POST.get("reason", "")},
            ),
            request.user,
            key=f"task:{task.pk}:{action}:{task.version}",
            expected_version=task.version,
        )
        return redirect(reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event}))


class EvidenceAdminView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk, action):
        evidence = get_object_or_404(
            TaskEvidence.objects.select_related("task"), pk=pk, event=self.event
        )
        if action not in {"approve", "request-changes"}:
            raise Http404
        note = request.POST.get("review_note", "").strip()
        if action == "request-changes" and not note:
            messages.error(request, "Explain the requested change before returning the file.")
            return redirect(
                reverse(
                    "plugins:speakerops:speakerops_drilldown",
                    kwargs={"event": event, "kind": "content"},
                )
            )
        with transaction.atomic():
            evidence = TaskEvidence.objects.select_for_update().get(pk=evidence.pk)
            evidence.review_status = (
                TaskEvidence.APPROVED if action == "approve" else TaskEvidence.CHANGES_REQUESTED
            )
            evidence.review_note = note
            evidence.reviewed_at = timezone.now()
            evidence.reviewed_by = request.user
            evidence.save(
                update_fields=[
                    "review_status",
                    "review_note",
                    "reviewed_at",
                    "reviewed_by",
                    "updated",
                ]
            )
            task = evidence.task
            if action == "request-changes" and task.status == OnboardingTask.COMPLETE:
                execute(
                    Command(
                        event=self.event,
                        aggregate_model=OnboardingTask,
                        aggregate_id=task.pk,
                        action="onboarding.request_changes",
                        target_state=OnboardingTask.REOPENED,
                        state_machine=TASK_MACHINE,
                        actor_role="organiser",
                        payload={"evidence_id": evidence.pk, "note": note},
                    ),
                    request.user,
                    key=f"evidence:{evidence.pk}:request-changes",
                    expected_version=task.version,
                )
        messages.success(
            request,
            f"Version {evidence.version} approved."
            if action == "approve"
            else f"Changes requested on version {evidence.version}; the speaker task reopened.",
        )
        return redirect(
            reverse(
                "plugins:speakerops:speakerops_drilldown",
                kwargs={"event": event, "kind": "content"},
            )
        )


class SyncPreviewView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event):
        with scope(event=self.event):
            result = preview(self.event, _accepted_speaker_payloads(self.event))
        return JsonResponse({"id": result.pk, "items": result.payload["items"]})


class SyncRunView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event, pk):
        with scope(event=self.event):
            run = execute_preview(self.event, pk, request.user)
        return JsonResponse({"id": run.pk, "status": run.status})


class ReminderView(EventContextMixin, View):
    permission = "manage"

    def post(self, request, event):
        if request.POST.get("confirm_reminders") != "yes":
            messages.error(request, "Confirm the outstanding reminder recipients first.")
            return redirect(
                reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event})
            )
        today = timezone.localdate()
        with scope(event=self.event):
            task_ids = {int(value) for value in request.POST.getlist("tasks") if value.isdigit()}
            outstanding_tasks = OnboardingTask.objects.filter(
                event=self.event,
                status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
            ).select_related("speaker", "submission", "definition")
            if task_ids:
                outstanding_tasks = outstanding_tasks.filter(pk__in=task_ids)
                reminder_key = f"onboarding-selected:{today.isoformat()}"
                label = "selected outstanding"
            else:
                outstanding_tasks = outstanding_tasks.filter(due_date__lt=today)
                reminder_key = f"onboarding-overdue:{today.isoformat()}"
                label = "overdue"
            queued = queue_reminders(
                self.event,
                tasks=outstanding_tasks,
                reminder_key=reminder_key,
            )
        if queued:
            messages.success(
                request,
                f"Queued {queued} {label} reminder{'s' if queued != 1 else ''}.",
            )
        else:
            messages.info(request, f"No new {label} reminders were queued.")
        return redirect(reverse("plugins:speakerops:speakerops_dashboard", kwargs={"event": event}))


class ResourceView(TemplateView):
    template_name = "pretalx_speakerops/resource.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(Event, slug=self.kwargs["event"])
        with scope(event=event):
            resource = get_object_or_404(Resource, event=event, slug=self.kwargs["resource"])
            version = (
                resource.versions.filter(published_at__isnull=False).order_by("-version").first()
            )
        context.update(event=event, resource=resource, version=version)
        return context


class PublishedIcsView(View):
    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        with scope(event=event):
            if not event.current_schedule:
                raise Http404
            return HttpResponse(released_ical(event), content_type="text/calendar")


class PublishedScheduleMixin:
    template_name = "pretalx_speakerops/embed.html"

    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        with scope(event=event):
            schedule = event.current_schedule
            if not schedule:
                raise Http404
            slots = list(
                schedule.talks.filter(is_visible=True, submission__isnull=False)
                .exclude(
                    submission__speakerops_publication_approval__status__in=(
                        SessionPublicationApproval.PENDING,
                        SessionPublicationApproval.CHANGES_REQUESTED,
                    )
                )
                .select_related("submission", "submission__track", "room")
                .prefetch_related("submission__speakers")
                .order_by("start", "room__position")
            )
            days_by_key = {}
            tracks_by_pk = {}
            rooms_by_pk = {}
            for slot in slots:
                slot.public_start = timezone.localtime(slot.start, event.tz)
                day_key = slot.public_start.date().isoformat()
                day = days_by_key.setdefault(
                    day_key,
                    {
                        "key": day_key,
                        "label": slot.public_start.strftime("%A, %B %-d"),
                        "slots": [],
                    },
                )
                day["slots"].append(slot)
                if slot.submission.track:
                    tracks_by_pk[slot.submission.track.pk] = slot.submission.track
                if slot.room:
                    rooms_by_pk[slot.room.pk] = slot.room
            speakers = []
            speaker_cards = []
            cards_by_speaker = {}
            seen = set()
            for slot in slots:
                for speaker in slot.submission.speakers.all():
                    if speaker.pk not in seen:
                        seen.add(speaker.pk)
                        speakers.append(speaker)
                        cards_by_speaker[speaker.pk] = {"speaker": speaker, "sessions": []}
                        speaker_cards.append(cards_by_speaker[speaker.pk])
                    cards_by_speaker[speaker.pk]["sessions"].append(slot.submission)
        return TemplateView.as_view(
            template_name=self.template_name,
            extra_context={
                "event": event,
                "schedule": schedule,
                "slots": slots,
                "days": list(days_by_key.values()),
                "tracks": sorted(tracks_by_pk.values(), key=lambda track: str(track.name)),
                "rooms": sorted(rooms_by_pk.values(), key=lambda room: str(room.name)),
                "speakers": speakers,
                "speaker_cards": speaker_cards,
            },
        )(request)


@method_decorator(xframe_options_exempt, name="dispatch")
@method_decorator(csp_update({"frame-ancestors": ["*"]}), name="dispatch")
class PublishedEmbedView(PublishedScheduleMixin, View):
    pass


class PublishedGalleryView(PublishedScheduleMixin, View):
    template_name = "pretalx_speakerops/gallery.html"


class StatusView(View):
    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        with scope(event=event):
            outbox_backlog = OutboxEvent.objects.filter(event=event, processed__isnull=True).count()
            sync_connection = (
                AcceleventsConnection.objects.filter(event=event)
                .values_list("status", flat=True)
                .first()
            )
            last_sync = (
                SyncRun.objects.filter(event=event)
                .order_by("-created")
                .values_list("status", "created")
                .first()
            )
            tasks_total = OnboardingTask.objects.filter(event=event).count()
            tasks_done = OnboardingTask.objects.filter(
                event=event, status__in=(OnboardingTask.COMPLETE, OnboardingTask.WAIVED)
            ).count()
        return JsonResponse(
            {
                "event": event.slug,
                "outbox_backlog": outbox_backlog,
                "sync_connection": sync_connection or "not configured",
                "last_sync_status": last_sync[0] if last_sync else None,
                "last_sync_at": last_sync[1].isoformat() if last_sync else None,
                "onboarding_total": tasks_total,
                "onboarding_done": tasks_done,
            }
        )
