from django.urls import path

from .views import (
    ChecklistView,
    CompleteTaskView,
    DashboardView,
    DrilldownView,
    PreviewView,
    PublishedEmbedView,
    PublishedIcsView,
    ReminderView,
    ResourceView,
    TaskAdminView,
)

app_name = "speakerops"

urlpatterns = [
    path(
        "<slug:event>/speaker-operations/schedule.ics",
        PublishedIcsView.as_view(),
        name="speakerops_ics",
    ),
    path(
        "<slug:event>/speaker-operations/embed/",
        PublishedEmbedView.as_view(),
        name="speakerops_embed",
    ),
    path(
        "orga/<slug:event>/speaker-operations/preview/",
        PreviewView.as_view(),
        name="speakerops_preview",
    ),
    path(
        "orga/<slug:event>/speaker-operations/reminders/",
        ReminderView.as_view(),
        name="speakerops_reminders",
    ),
    path(
        "orga/<slug:event>/speaker-operations/",
        DashboardView.as_view(),
        name="speakerops_dashboard",
    ),
    path(
        "orga/<slug:event>/speaker-operations/<slug:kind>/",
        DrilldownView.as_view(),
        name="speakerops_drilldown",
    ),
    path(
        "<slug:event>/speaker-operations/checklist/",
        ChecklistView.as_view(),
        name="speakerops_checklist",
    ),
    path(
        "<slug:event>/speaker-operations/checklist/<int:pk>/complete/",
        CompleteTaskView.as_view(),
        name="speakerops_complete_task",
    ),
    path(
        "<slug:event>/speaker-operations/resources/<slug:resource>/",
        ResourceView.as_view(),
        name="speakerops_resource",
    ),
    path(
        "orga/<slug:event>/speaker-operations/tasks/<int:pk>/<slug:action>/",
        TaskAdminView.as_view(),
        name="speakerops_task_admin",
    ),
]
