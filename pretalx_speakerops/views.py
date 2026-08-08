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
from pretalx.submission.models import Submission, SubmissionStates

from .auth import is_speaker, require_event_permission
from .domain.commands import Command, execute
from .domain.state import StateMachine, Transition
from .models import CommandReceipt, OnboardingTask, PreviewRun, Resource
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
            tasks = OnboardingTask.objects.filter(event=self.event)
            task_type = self.request.GET.get("task_type")
            if task_type:
                tasks = tasks.filter(definition__task_type=task_type)
            if self.request.GET.get("overdue") == "1":
                tasks = tasks.filter(due_date__lt=timezone.localdate())
            proposals = Submission.objects.filter(event=self.event)
            schedule = self.event.wip_schedule
            conflicts = len(schedule.get_all_talk_warnings()) if schedule else 0
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
                    "sync": PreviewRun.objects.filter(event=self.event).count(),
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
                    rows = schedule.get_all_talk_warnings() if schedule else []
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


class PreviewView(EventContextMixin, TemplateView):
    permission = "manage"
    template_name = "pretalx_speakerops/preview.html"

    def post(self, request, event):
        run = PreviewRun.objects.create(
            event=self.event,
            status="previewed",
            payload={"adapter": "mock", "mode": "preview", "items": []},
        )
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
