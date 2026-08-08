from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.submission.models import Submission, SubmissionStates

from .models import OnboardingTask, PreviewRun


class EventContextMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs["event"])
        is_orga = request.path.startswith("/orga/")
        if is_orga and not request.user.has_perm("event.update_event", self.event):
            raise Http404
        if not is_orga:
            with scope(event=self.event):
                if not self.event.submissions.filter(speakers=request.user).exists():
                    raise Http404
            with scope(event=self.event):
                return super().dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


class DashboardView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/dashboard.html"

    def get_context_data(self, **kwargs):
        with scope(event=self.event):
            context = super().get_context_data(**kwargs)
            tasks = OnboardingTask.objects.filter(event=self.event)
            proposals = Submission.objects.filter(event=self.event)
            schedule = self.event.wip_schedule
            conflicts = len(schedule.get_all_talk_warnings()) if schedule else 0
        context.update(
            event=self.event,
            counts={
                "tasks": tasks.filter(status=OnboardingTask.PENDING).count(),
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
        if kind == "tasks":
            rows = OnboardingTask.objects.filter(
                event=self.event, status=OnboardingTask.PENDING
            ).select_related("speaker", "definition")
        elif kind == "undecided":
            rows = Submission.objects.filter(event=self.event, state=SubmissionStates.SUBMITTED)
        elif kind == "review":
            rows = Submission.objects.filter(event=self.event, reviews__isnull=False).distinct()
        elif kind in {"sync", "conflicts"}:
            if kind == "conflicts":
                schedule = self.event.wip_schedule
                rows = schedule.get_all_talk_warnings() if schedule else []
            else:
                rows = PreviewRun.objects.filter(event=self.event)
        else:
            rows = []
        context.update(kind=kind, rows=rows)
        return context


class ChecklistView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/checklist.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["event"] = self.event
        context["tasks"] = OnboardingTask.objects.filter(
            event=self.event, speaker=self.request.user
        ).select_related("definition", "submission")
        return context


class CompleteTaskView(EventContextMixin, View):
    def post(self, request, event, pk):
        task = get_object_or_404(OnboardingTask, pk=pk, event=self.event, speaker=request.user)
        task.status = OnboardingTask.COMPLETE
        task.completed_at = timezone.now()
        task.version += 1
        task.save(update_fields=["status", "completed_at", "version", "updated"])
        messages.success(request, "Task completed.")
        return redirect(reverse("plugins:speakerops:speakerops_checklist", kwargs={"event": event}))


class PreviewView(EventContextMixin, TemplateView):
    template_name = "pretalx_speakerops/preview.html"

    def post(self, request, event):
        run = PreviewRun.objects.create(
            event=self.event,
            status="previewed",
            payload={"adapter": "mock", "mode": "preview", "items": []},
        )
        return JsonResponse({"id": run.pk, "status": run.status})
