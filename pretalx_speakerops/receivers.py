from django.dispatch import receiver
from django.urls import reverse
from pretalx.orga.signals import nav_event
from pretalx.schedule.signals import schedule_release
from pretalx.submission.signals import submission_state_change

from .models import PreviewRun
from .onboarding.services import ensure_acceptance_plan


@receiver(submission_state_change)
def create_acceptance_plan(sender, submission, old_state, user, **kwargs):
    if submission.state != "accepted":
        return
    from django.db import transaction

    transaction.on_commit(lambda: ensure_acceptance_plan(submission))


@receiver(nav_event)
def speakerops_navigation(sender, request, **kwargs):
    return [
        {
            "label": "Speaker Operations",
            "url": reverse(
                "plugins:speakerops:speakerops_dashboard", kwargs={"event": sender.slug}
            ),
            "icon": "users",
            "active": "speakerops" in request.path,
        }
    ]


@receiver(schedule_release)
def schedule_release_preview(sender, schedule, user, **kwargs):
    PreviewRun.objects.get_or_create(
        event=sender,
        status="schedule-released",
        payload={"schedule": schedule.pk},
    )
