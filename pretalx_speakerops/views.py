from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import User
from pretalx.submission.models import Review, ReviewScore, Submission, SubmissionStates

from .auth import is_speaker, require_event_permission
from .domain.commands import Command, execute
from .domain.state import StateMachine, Transition
from .integrations.sync import execute_item, execute_preview, preview
from .models import (
    AcceleventsConnection,
    CommandReceipt,
    OnboardingTask,
    OutboxEvent,
    Resource,
    ReviewRecommendation,
    SyncItem,
    SyncPreview,
    SyncRun,
)
from .onboarding.reminders import queue_reminders
from .onboarding.services import record_evidence
from .program.calendar import released_ical
from .program.policy import classify_warnings, release_schedule, schedule_slots
from .program.reviews import configure_review_rounds

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
        elif permission == "manage":
            require_event_permission(
                request.user, self.event, "event.update_event", "submission.orga_update_submission"
            )
        else:
            require_event_permission(
                request.user, self.event, "event.update_event", "submission.orga_update_submission"
            )


class DashboardView(EventContextMixin, TemplateView):
    permission = "dashboard"
    template_name = "pretalx_speakerops/dashboard.html"

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
        proposal_stats = proposals.aggregate(
            total=Count("pk", distinct=True),
            undecided=Count("pk", filter=Q(state=SubmissionStates.SUBMITTED), distinct=True),
            reviewed=Count("pk", filter=Q(reviews__isnull=False), distinct=True),
        )
        sync_error_count = SyncItem.objects.filter(event=self.event, status=SyncItem.FAILED).count()
        return {
            "counts": {
                "tasks": task_stats["active"],
                "undecided": proposal_stats["undecided"],
                "reviewed": proposal_stats["reviewed"],
                "proposals": proposal_stats["total"],
                "conflicts": conflicts,
                "missing_assets": task_stats["missing_assets"],
                "sync": sync_error_count,
                "sync_status": (
                    AcceleventsConnection.objects.filter(event=self.event)
                    .values_list("status", flat=True)
                    .first()
                    or "not configured"
                ),
            },
            "attention": {
                "overdue": task_stats["overdue"],
                "blocked_release": conflicts > 0,
                "sync_errors": sync_error_count,
            },
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
                    ).select_related("speaker", "definition")
                )
            elif kind == "undecided":
                rows = list(
                    Submission.objects.filter(event=self.event, state=SubmissionStates.SUBMITTED)
                )
            elif kind == "review":
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
                    ).select_related("speaker", "definition", "submission")
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
                .order_by("status", "due_date", "definition__position", "id")
            )
        today = timezone.localdate()
        pending, complete, waived = [], [], []
        for t in tasks:
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


class ReviewerScoringView(EventContextMixin, TemplateView):
    permission = "review"
    template_name = "pretalx_speakerops/reviewer_scoring.html"

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
        context.update(
            event=self.event,
            queue=queue,
            submission=submission,
            review=review,
            criteria=criteria,
            recommendation=recommendation,
            recommendation_choices=ReviewRecommendation.CHOICES,
        )
        return context

    def post(self, request, event, pk=None):
        with scope(event=self.event):
            configure_review_rounds(self.event)
            submission = self._submission()
            if not submission:
                raise Http404
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
            ReviewRecommendation.objects.update_or_create(
                event=self.event,
                submission=submission,
                reviewer=request.user,
                defaults={"recommendation": recommendation_value},
            )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"saved": True, "score": review.display_score, "updated": timezone.now()}
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            schedule = self.event.wip_schedule
            slots = schedule_slots(schedule) if schedule else []
            warnings = classify_warnings(schedule, slots=slots) if schedule else []
        context.update(
            event=self.event,
            schedule=schedule,
            slots=slots,
            warnings=warnings,
            blocking=[warning for warning in warnings if warning["blocking"]],
        )
        return context

    def post(self, request, event):
        if request.POST.get("confirm_release") != "yes":
            messages.error(request, "Confirm the public schedule release first.")
            return redirect(request.path)
        with scope(event=self.event):
            schedule = self.event.wip_schedule
            try:
                release_schedule(
                    schedule,
                    request.POST.get("name", "SpeakerOps release").strip() or "SpeakerOps release",
                    request.user,
                    notify_speakers=False,
                )
            except ValidationError as error:
                messages.error(request, "; ".join(error.messages))
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
        key = f"task:{task.pk}:complete"
        with transaction.atomic():
            if CommandReceipt.objects.filter(event=self.event, key=key).exists():
                complete = True
            else:
                upload = request.FILES.get("upload")
                value = {"response": request.POST.get("response", "")}
                try:
                    _, complete = record_evidence(
                        task,
                        request.user,
                        task.definition.completion_evaluator,
                        value=value,
                        upload=upload,
                    )
                except ValueError as error:
                    messages.error(request, str(error))
                    return redirect(
                        reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event})
                    )
            if not complete:
                messages.error(request, "The supplied evidence does not complete this task.")
                return redirect(
                    reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event})
                )
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
        messages.success(request, "Task completed.")
        return redirect(reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event}))


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
        key = request.POST.get("reminder_key", "onboarding-due")
        queued = queue_reminders(self.event, reminder_key=key)
        return JsonResponse({"queued": queued, "reminder_key": key})


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
                .select_related("submission", "room")
                .prefetch_related("submission__speakers")
                .order_by("start", "room__position")
            )
            speakers = []
            seen = set()
            for slot in slots:
                for speaker in slot.submission.speakers.all():
                    if speaker.pk not in seen:
                        seen.add(speaker.pk)
                        speakers.append(speaker)
        return TemplateView.as_view(
            template_name=self.template_name,
            extra_context={
                "event": event,
                "schedule": schedule,
                "slots": slots,
                "speakers": speakers,
            },
        )(request)


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
