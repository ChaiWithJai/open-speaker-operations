from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import User
from pretalx.submission.models import Submission, SubmissionStates

from .auth import is_speaker, require_event_permission
from .domain.commands import Command, execute
from .domain.state import StateMachine, Transition
from .integrations.sync import execute_preview, preview
from .models import (
    AcceleventsConnection,
    CommandReceipt,
    OnboardingTask,
    PreviewRun,
    Resource,
    SyncRun,
)
from .onboarding.reminders import queue_reminders
from .onboarding.services import record_evidence
from .program.calendar import released_ical

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

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            today = timezone.localdate()
            tasks = OnboardingTask.objects.filter(event=self.event)
            proposals = Submission.objects.filter(event=self.event)
            schedule = self.event.wip_schedule
            conflicts = len(schedule.get_all_talk_warnings()) if schedule else 0
            overdue_tasks = tasks.filter(
                due_date__lt=today,
                status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED),
            ).count()
            context.update(
                event=self.event,
                counts={
                    "tasks": tasks.filter(
                        status__in=(OnboardingTask.PENDING, OnboardingTask.REOPENED)
                    ).count(),
                    "undecided": proposals.filter(state=SubmissionStates.SUBMITTED).count(),
                    "reviewed": proposals.filter(reviews__isnull=False).distinct().count(),
                    "proposals": proposals.count(),
                    "conflicts": conflicts,
                    "sync": SyncRun.objects.filter(event=self.event).count(),
                    "sync_status": (
                        AcceleventsConnection.objects.filter(event=self.event)
                        .values_list("status", flat=True)
                        .first()
                        or "not configured"
                    ),
                },
                attention={
                    "overdue": overdue_tasks,
                    "blocked_release": conflicts > 0,
                },
            )
            return context


class DrilldownView(DashboardView):
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
            elif kind in {"sync", "conflicts"}:
                if kind == "conflicts":
                    schedule = self.event.wip_schedule
                    raw = schedule.get_all_talk_warnings() if schedule else {}
                    rows = []
                    for talk, warnings in raw.items():
                        title = talk.submission.title if talk.submission else str(talk)
                        for w in warnings:
                            msg = w.get("message") if isinstance(w, dict) else str(w)
                            rows.append(f"{title}: {msg}")
                else:
                    rows = list(PreviewRun.objects.filter(event=self.event))
            else:
                rows = []
        context.update(kind=kind, rows=rows)
        return context


class ChecklistView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/checklist.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event"] = self.event
        with scope(event=self.event):
            context["tasks"] = list(
                OnboardingTask.objects.filter(event=self.event, speaker=self.request.user)
                .select_related("definition", "submission")
                .order_by("status", "due_date", "definition__position", "id")
            )
        context["today"] = timezone.localdate()
        return context


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
            speaker_ids = Submission.objects.filter(
                event=self.event, state=SubmissionStates.ACCEPTED
            ).values_list("speakers", flat=True)
            payloads = [
                (
                    "speaker",
                    speaker.pk,
                    {
                        "firstName": speaker.name.split(" ", 1)[0],
                        "lastName": speaker.name.split(" ", 1)[-1],
                        "email": speaker.email,
                    },
                )
                for speaker in User.objects.filter(pk__in=speaker_ids)
            ]
            result = preview(self.event, payloads)
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


class ResourceView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/resource.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with scope(event=self.event):
            resource = get_object_or_404(Resource, event=self.event, slug=self.kwargs["resource"])
            version = (
                resource.versions.filter(published_at__isnull=False).order_by("-version").first()
            )
        context.update(event=self.event, resource=resource, version=version)
        return context


class PublishedIcsView(View):
    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        with scope(event=event):
            if not event.current_schedule:
                raise Http404
            return HttpResponse(released_ical(event), content_type="text/calendar")


class PublishedEmbedView(View):
    def get(self, request, event):
        event = get_object_or_404(Event, slug=event)
        with scope(event=event):
            if not event.current_schedule:
                raise Http404
            return TemplateView.as_view(
                template_name="pretalx_speakerops/embed.html",
                extra_context={"event": event, "schedule": event.current_schedule},
            )(request)
