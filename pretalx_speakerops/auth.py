from django.db.models import Q
from django.http import Http404
from django.urls import reverse

MANAGE_PERMISSIONS = ("event.update_event", "submission.orga_update_submission")
REVIEWER_TEAM_NAME = "SpeakerOps reviewers"
TEAM_PERMISSION_FIELDS = (
    "can_create_events",
    "can_change_teams",
    "can_change_organiser_settings",
    "can_change_event_settings",
    "can_change_submissions",
    "is_reviewer",
)


def require_event_permission(user, event, *permissions):
    if user.is_administrator:
        return
    if not any(user.has_perm(permission, event) for permission in permissions):
        raise Http404


def is_speaker(user, event):
    return event.submissions.filter(speakers__pk=user.pk).exists()


def can_review(user, event):
    if user.is_administrator:
        return True
    authorized_events = getattr(user, "_speakerops_review_event_ids", set())
    if event.pk in authorized_events:
        return True
    # SpeakerOps review access is intentionally independent from pretalx's
    # native ``is_reviewer`` team role. That native role also exposes the
    # organiser speaker directory and profile pages, which defeats blind
    # review. The named, event-limited team is an invitation/provisioning
    # boundary for our custom queues and carries no native permissions.
    # Resolve the two valid team boundaries in one query: a native event
    # manager/chair, or the dedicated permission-free SpeakerOps reviewer
    # team. Avoiding pretalx's broad ``is_reviewer`` role keeps native speaker
    # identities closed while preserving the custom queue.
    team_rows = list(
        user.teams.filter(organiser=event.organiser)
        .filter(Q(all_events=True) | Q(limit_events=event))
        .values("name", *TEAM_PERMISSION_FIELDS)
    )
    native_permissions = {
        permission for row in team_rows for permission in TEAM_PERMISSION_FIELDS if row[permission]
    }
    allowed = bool(
        {"can_change_submissions", "can_change_event_settings"} & native_permissions
    ) or any(row["name"] == REVIEWER_TEAM_NAME for row in team_rows)
    if not allowed:
        from .models import ReviewerPool, RoundReviewAssignment, RoundReviewer

        allowed = (
            ReviewerPool.objects.filter(event=event, reviewers=user).exists()
            or RoundReviewer.objects.filter(event=event, reviewer=user).exists()
            or RoundReviewAssignment.objects.filter(event=event, reviewer=user).exists()
            or event.submissions.filter(assigned_reviewers=user).exists()
        )
    if allowed:
        authorized_events.add(event.pk)
        user._speakerops_review_event_ids = authorized_events
    # pretalx treats an empty event-permission set as a cache miss. A
    # permission-free user would otherwise repeat the same team lookup
    # throughout one request. Cache the complete native permission set, or a
    # namespaced marker that no native rule recognizes.
    native_cache = getattr(user, "event_permission_cache", None)
    if native_cache is not None and not native_cache.get(event.pk):
        native_cache[event.pk] = native_permissions or {"speakerops_reviewer"}
    return allowed


def can_manage(user, event):
    if user.is_administrator:
        return True
    cache = getattr(user, "_speakerops_manage_permissions", {})
    if event.pk in cache:
        return cache[event.pk]
    allowed = any(user.has_perm(permission, event) for permission in MANAGE_PERMISSIONS)
    cache[event.pk] = allowed
    user._speakerops_manage_permissions = cache
    return allowed


def has_round_assignments(user, event):
    """Return whether the reviewer has a canonical round-review queue."""
    from .models import RoundReviewAssignment

    cache = getattr(user, "_speakerops_round_assignment_presence", {})
    if event.pk in cache:
        return cache[event.pk]
    result = (
        RoundReviewAssignment.objects.filter(event=event, reviewer=user)
        .exclude(status=RoundReviewAssignment.RECUSED)
        .exists()
    )
    cache[event.pk] = result
    user._speakerops_round_assignment_presence = cache
    return result


def role_navigation(user, event, current_path=""):
    """Return only the Speaker Operations destinations this user can open."""
    if not user.is_authenticated:
        return []

    destinations = []
    # Keep organizer/reviewer pages focused on their current authority. The
    # role-entry route still exposes the speaker workspace for dual-role users.
    if not current_path.startswith("/orga/") and is_speaker(user, event):
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
        if has_round_assignments(user, event):
            destinations.append(
                {
                    "label": "Assigned round reviews",
                    "url": reverse(
                        "plugins:speakerops:speakerops_round_review_queue",
                        kwargs={"event": event.slug},
                    ),
                    "section": "round-review",
                }
            )
        else:
            destinations.append(
                {
                    "label": "Review queue",
                    "url": reverse(
                        "plugins:speakerops:speakerops_review_queue",
                        kwargs={"event": event.slug},
                    ),
                    "section": "reviewer",
                }
            )
        destinations.append(
            {
                "label": "Conference memory",
                "url": reverse(
                    "plugins:speakerops:speakerops_conference_memory",
                    kwargs={"event": event.slug},
                ),
                "section": "conference-memory",
            }
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
                    "label": "Content & files",
                    "url": reverse(
                        "plugins:speakerops:speakerops_content_operations",
                        kwargs={"event": event.slug},
                    ),
                    "section": "content",
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
                    "/content/",
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
    preferred_sections = ("operations", "round-review", "reviewer", "checklist")
    for section in preferred_sections:
        if destination := next((item for item in navigation if item["section"] == section), None):
            return destination["url"]
    return None
