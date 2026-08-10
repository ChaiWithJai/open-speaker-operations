from django.http import Http404
from django.urls import reverse

REVIEW_PERMISSION = "submission.orga_list_submission"
MANAGE_PERMISSIONS = ("event.update_event", "submission.orga_update_submission")


def require_event_permission(user, event, *permissions):
    if user.is_administrator:
        return
    if not any(user.has_perm(permission, event) for permission in permissions):
        raise Http404


def is_speaker(user, event):
    return event.submissions.filter(speakers__pk=user.pk).exists()


def can_review(user, event):
    return user.is_administrator or user.has_perm(REVIEW_PERMISSION, event)


def can_manage(user, event):
    return user.is_administrator or any(
        user.has_perm(permission, event) for permission in MANAGE_PERMISSIONS
    )


def role_navigation(user, event, current_path=""):
    """Return only the Speaker Operations destinations this user can open."""
    if not user.is_authenticated:
        return []

    destinations = []
    if is_speaker(user, event):
        destinations.extend(
            (
                {
                    "label": "Speaker tasks",
                    "url": reverse(
                        "plugins:speakerops:speakerops_checklist",
                        kwargs={"event": event.slug},
                    ),
                    "section": "checklist",
                },
                {
                    "label": "Profile",
                    "url": reverse(
                        "plugins:speakerops:speakerops_speaker_profile",
                        kwargs={"event": event.slug},
                    ),
                    "section": "profile",
                },
            )
        )
    if can_review(user, event):
        destinations.extend(
            (
                {
                    "label": "Review queue",
                    "url": reverse(
                        "plugins:speakerops:speakerops_review_queue",
                        kwargs={"event": event.slug},
                    ),
                    "section": "reviewer",
                },
                {
                    "label": "Round reviews",
                    "url": reverse(
                        "plugins:speakerops:speakerops_round_review_queue",
                        kwargs={"event": event.slug},
                    ),
                    "section": "round-review",
                },
                {
                    "label": "Conference memory",
                    "url": reverse(
                        "plugins:speakerops:speakerops_conference_memory",
                        kwargs={"event": event.slug},
                    ),
                    "section": "conference-memory",
                },
            )
        )
    if can_manage(user, event):
        destinations.extend(
            (
                {
                    "label": "Operations",
                    "url": reverse(
                        "plugins:speakerops:speakerops_dashboard",
                        kwargs={"event": event.slug},
                    ),
                    "section": "operations",
                },
                {
                    "label": "Speakers",
                    "url": reverse(
                        "plugins:speakerops:speakerops_speakers",
                        kwargs={"event": event.slug},
                    ),
                    "section": "speakers",
                },
                {
                    "label": "Speaker CRM",
                    "url": reverse(
                        "plugins:speakerops:speakerops_crm_org",
                        kwargs={"organiser": event.organiser.slug},
                    ),
                    "section": "crm",
                },
                {
                    "label": "Agenda / release",
                    "url": reverse(
                        "plugins:speakerops:speakerops_agenda",
                        kwargs={"event": event.slug},
                    ),
                    "section": "agenda",
                },
                {
                    "label": "Program decisions",
                    "url": reverse(
                        "plugins:speakerops:speakerops_program_decisions",
                        kwargs={"event": event.slug},
                    ),
                    "section": "program-decisions",
                },
                {
                    "label": "Abstract management",
                    "url": reverse(
                        "plugins:speakerops:speakerops_abstract_management",
                        kwargs={"event": event.slug},
                    ),
                    "section": "abstract-management",
                },
                {
                    "label": "CFP routing",
                    "url": reverse(
                        "plugins:speakerops:speakerops_cfp_routing",
                        kwargs={"event": event.slug},
                    ),
                    "section": "cfp-routing",
                },
                {
                    "label": "Sync",
                    "url": reverse(
                        "plugins:speakerops:speakerops_sync_console",
                        kwargs={"event": event.slug},
                    ),
                    "section": "sync",
                },
            )
        )

    for destination in destinations:
        url = destination["url"]
        if destination["section"] == "operations":
            destination["active"] = current_path.startswith(url) and not any(
                marker in current_path
                for marker in (
                    "/reviewer/",
                    "/speakers/",
                    "/agenda/",
                    "/conference-memory/",
                    "/crm/",
                    "/cfp-routing/",
                    "/program-decisions/",
                    "/abstract-management/",
                    "/round-review/",
                    "/sync-console/",
                )
            )
        else:
            destination["active"] = current_path == url or current_path.startswith(url)
    return destinations


def role_home_url(user, event):
    """Choose the highest-authority useful home for one event."""
    navigation = role_navigation(user, event)
    preferred_sections = ("operations", "reviewer", "checklist")
    for section in preferred_sections:
        if destination := next((item for item in navigation if item["section"] == section), None):
            return destination["url"]
    return None
