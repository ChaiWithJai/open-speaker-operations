from django.urls import path

from .views import (
    ChecklistView,
    CompleteTaskView,
    DashboardView,
    DrilldownView,
    PreviewView,
)

app_name = "speakerops"

urlpatterns = [
    path(
        "orga/<slug:event>/speaker-operations/preview/",
        PreviewView.as_view(),
        name="speakerops_preview",
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
]
