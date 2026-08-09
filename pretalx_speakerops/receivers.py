from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html, format_html_join, json_script
from pretalx.cfp.signals import footer_link, html_above_submission_list
from pretalx.cfp.signals import html_head as cfp_html_head
from pretalx.orga.signals import html_above_orga_page, nav_event
from pretalx.orga.signals import html_head as orga_html_head
from pretalx.schedule.signals import schedule_release
from pretalx.submission.signals import submission_state_change

from .auth import is_speaker, role_home_url, role_navigation
from .cfp import conditional_rules_for_browser
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
    navigation = role_navigation(request.user, sender, request.path)
    if not navigation:
        return []
    return [
        {
            "label": "Speaker Operations",
            "url": role_home_url(request.user, sender),
            "icon": "users",
            "active": "speakerops" in request.path,
            "children": navigation,
        }
    ]


@receiver(html_above_orga_page)
def speakerops_role_navigation(sender, request, **kwargs):
    if "/speaker-operations/" not in request.path:
        return ""
    navigation = role_navigation(request.user, sender, request.path)
    if not navigation:
        return ""

    def render_link(item):
        if item["active"]:
            return format_html(
                '<li><a href="{}" aria-current="page">{}</a></li>',
                item["url"],
                item["label"],
            )
        return format_html('<li><a href="{}">{}</a></li>', item["url"], item["label"])

    links = format_html_join("", "{}", ((render_link(item),) for item in navigation))
    return format_html(
        '<nav class="speakerops-role-nav" aria-label="Speaker Operations">'
        '<a class="speakerops-role-nav__home" href="{}">Speaker Operations</a>'
        "<ul>{}</ul></nav>",
        role_home_url(request.user, sender),
        links,
    )


@receiver(footer_link)
def speakerops_speaker_footer_link(sender, request, **kwargs):
    links = []
    if sender.current_schedule:
        links.append(
            {
                "label": "Released schedule",
                "url": reverse(
                    "plugins:speakerops:speakerops_embed", kwargs={"event": sender.slug}
                ),
            }
        )
    links.append(
        {
            "label": "How to write a proposal",
            "url": reverse(
                "plugins:speakerops:speakerops_cfp_guide", kwargs={"event": sender.slug}
            ),
        }
    )
    if request.user.is_authenticated and is_speaker(request.user, sender):
        links.append(
            {
                "label": "Speaker tasks",
                "url": reverse(
                    "plugins:speakerops:speakerops_entry", kwargs={"event": sender.slug}
                ),
            }
        )
    return links


@receiver(html_above_submission_list)
def speakerops_speaker_home_callout(sender, request, **kwargs):
    if not request.user.is_authenticated or not is_speaker(request.user, sender):
        return ""
    return format_html(
        '<aside class="speakerops-entry-callout" aria-labelledby="speakerops-entry-title">'
        '<div><strong id="speakerops-entry-title">Speaker workspace</strong>'
        "<p>See what the program team needs from you next.</p></div>"
        '<a class="btn btn-primary" href="{}">Open speaker tasks</a></aside>',
        reverse("plugins:speakerops:speakerops_entry", kwargs={"event": sender.slug}),
    )


@receiver(user_logged_in)
def speakerops_post_login_home(sender, request, user, **kwargs):
    """Give event-scoped sign-ins a role home while preserving explicit deep links."""
    event = getattr(request, "event", None)
    if not event or "pretalx_speakerops" not in event.plugin_list or request.GET.get("next"):
        return
    if not role_home_url(user, event):
        return
    params = request.GET.copy()
    params["next"] = reverse("plugins:speakerops:speakerops_entry", kwargs={"event": event.slug})
    request.GET = params


@receiver(orga_html_head)
def speakerops_orga_assets(sender, request, **kwargs):
    return format_html(
        '<script defer src="{}"></script>',
        static("pretalx_speakerops/orga-a11y.js"),
    )


@receiver(cfp_html_head)
def speakerops_cfp_assets(sender, request, **kwargs):
    """Enhance the native CFP without overriding pretalx templates."""
    shared_assets = format_html(
        '<link rel="stylesheet" href="{}"><script defer src="{}"></script>',
        static("pretalx_speakerops/speakerops.css"),
        static("pretalx_speakerops/cfp-a11y.js"),
    )
    if "/submit/" not in request.path and "/talk/" not in request.path:
        return shared_assets
    rules = conditional_rules_for_browser(sender)
    return format_html(
        '{}{}<script defer src="{}"></script>',
        json_script(rules, "speakerops-cfp-rules"),
        shared_assets,
        static("pretalx_speakerops/cfp-form.js"),
    )


@receiver(schedule_release)
def schedule_release_preview(sender, schedule, user, **kwargs):
    PreviewRun.objects.get_or_create(
        event=sender,
        status="schedule-released",
        payload={"schedule": schedule.pk},
    )
