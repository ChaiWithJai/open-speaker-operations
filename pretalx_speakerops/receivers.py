from django.dispatch import receiver
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from pretalx.cfp.signals import html_head as cfp_html_head
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


@receiver(cfp_html_head)
def speakerops_cfp_assets(sender, request, **kwargs):
    """Enhance the native CFP without overriding pretalx templates."""
    if "/submit/" not in request.path and "/talk/" not in request.path:
        return ""
    return format_html(
        '<link rel="stylesheet" href="{}"><script defer src="{}"></script>',
        static("pretalx_speakerops/speakerops.css"),
        static("pretalx_speakerops/cfp-form.js"),
    )


@receiver(schedule_release)
def schedule_release_preview(sender, schedule, user, **kwargs):
    PreviewRun.objects.get_or_create(
        event=sender,
        status="schedule-released",
        payload={"schedule": schedule.pk},
    )
