"""Canonical resource registry backing docs/buzz-demo-map.md.

Pure data: which SpeakerOps routes anchor each judged benchmark row's Buzz
demo, and which resources still resolve only to an aggregate page (resolver
gaps for the #67 ``go/{resource}/{opaque-id}`` contract). This module must
not import Django or any runtime plugin code; the cross-check against the
real URL surface lives in ``tests/test_buzz_resource_registry.py``.

``audience`` names the least-privileged role the link is meant for, so demo
scripts cannot accidentally hand an organizer surface to a speaker thread.
"""

from __future__ import annotations

from dataclasses import dataclass

JUDGED_ROWS = (
    "custom-submission-forms",
    "speaker-portal",
    "abstract-management",
    "review-workflows",
    "agenda-schedule",
    "embeds-publishing",
    "automated-communication",
    "performance-ux",
    "integrations-csv",
    "crm-relationships",
)

# status values:
#   "detail"    — route lands on the exact record (addressable today)
#   "aggregate" — route lands on a console/aggregate page; the go/ resolver
#                 still owes this row a record-level resource
DETAIL = "detail"
AGGREGATE = "aggregate"


@dataclass(frozen=True)
class ResourceLink:
    resource: str
    judged_row: str
    route_name: str
    url_kwargs: tuple[str, ...]
    audience: str
    status: str
    note: str = ""


RESOURCES = (
    # 1. Custom submission forms
    ResourceLink(
        "cfp-routing-console", "custom-submission-forms",
        "speakerops_cfp_routing", ("event",), "organiser", AGGREGATE,
        "Form construction stays web-UI work; Buzz links to the console.",
    ),
    ResourceLink(
        "cfp-public-guide", "custom-submission-forms",
        "speakerops_cfp_guide", ("event",), "public", DETAIL,
        "What a submitter will actually see.",
    ),
    # 2. Speaker self-service portal
    ResourceLink(
        "speaker-checklist", "speaker-portal",
        "speakerops_checklist", ("event",), "speaker", DETAIL,
        "Per-user surface: detail for the speaker it addresses.",
    ),
    ResourceLink(
        "speaker-profile", "speaker-portal",
        "speakerops_speaker_profile", ("event",), "speaker", DETAIL,
    ),
    ResourceLink(
        "onboarding-task", "speaker-portal",
        "speakerops_checklist", ("event",), "speaker", AGGREGATE,
        "Resolver gap: tasks resolve to checklist anchors today.",
    ),
    # 3. Submission & abstract management
    ResourceLink(
        "abstract-console", "abstract-management",
        "speakerops_abstract_management", ("event",), "organiser", AGGREGATE,
    ),
    ResourceLink(
        "submission-presenters", "abstract-management",
        "speakerops_submission_presenters", ("event", "code"), "organiser", DETAIL,
    ),
    ResourceLink(
        "submission", "abstract-management",
        "speakerops_abstract_management", ("event",), "organiser", AGGREGATE,
        "Resolver gap: per-submission operational detail is a fragment.",
    ),
    # 4. Evaluation & review workflows
    ResourceLink(
        "review-assignment", "review-workflows",
        "speakerops_review", ("event", "pk"), "reviewer", DETAIL,
        "Reference demo: record-level route already exists.",
    ),
    ResourceLink(
        "round-review-assignment", "review-workflows",
        "speakerops_round_review", ("event", "assignment"), "reviewer", DETAIL,
    ),
    ResourceLink(
        "review-queue", "review-workflows",
        "speakerops_review_queue", ("event",), "reviewer", AGGREGATE,
    ),
    ResourceLink(
        "program-decisions", "review-workflows",
        "speakerops_program_decisions", ("event",), "organiser", AGGREGATE,
        "Decision waves confirm here; receipts mirror to the thread.",
    ),
    # 5. Agenda & schedule building
    ResourceLink(
        "agenda-release", "agenda-schedule",
        "speakerops_agenda", ("event",), "organiser", AGGREGATE,
        "Drag-and-drop editing is explicitly web-UI work.",
    ),
    ResourceLink(
        "conflicts-drilldown", "agenda-schedule",
        "speakerops_drilldown", ("event", "kind"), "organiser", AGGREGATE,
        "kind=conflicts; also tasks/content/undecided/missing-assets briefs. "
        "Resolver gap: per-conflict resource.",
    ),
    # 6. Embeds & web publishing
    ResourceLink(
        "embed-builder", "embeds-publishing",
        "speakerops_embed_builder", ("event",), "organiser", AGGREGATE,
    ),
    ResourceLink(
        "public-embed", "embeds-publishing",
        "speakerops_embed", ("event",), "public", DETAIL,
    ),
    ResourceLink(
        "public-gallery", "embeds-publishing",
        "speakerops_gallery", ("event",), "public", DETAIL,
    ),
    ResourceLink(
        "public-speaker", "embeds-publishing",
        "speakerops_public_speaker", ("event", "code"), "public", DETAIL,
    ),
    ResourceLink(
        "public-session", "embeds-publishing",
        "speakerops_public_session", ("event", "code"), "public", DETAIL,
    ),
    ResourceLink(
        "schedule-ics", "embeds-publishing",
        "speakerops_ics", ("event",), "public", DETAIL,
    ),
    # 7. Automated communication
    ResourceLink(
        "reminder-console", "automated-communication",
        "speakerops_reminders", ("event",), "organiser", AGGREGATE,
        "Flagship bounded write: preview -> confirm -> receipt. "
        "Resolver gap: communication-receipt detail.",
    ),
    # 8. System performance & UX
    ResourceLink(
        "status", "performance-ux",
        "speakerops_status", ("event",), "public", DETAIL,
        "Machine-readable health for scheduled briefs.",
    ),
    ResourceLink(
        "operations-dashboard", "performance-ux",
        "speakerops_dashboard", ("event",), "organiser", AGGREGATE,
    ),
    # 9. Integrations & data handling
    ResourceLink(
        "sync-run", "integrations-csv",
        "speakerops_sync_run", ("event", "pk"), "organiser", DETAIL,
        "Record-level route already exists; retries stay idempotent (ADR 011).",
    ),
    ResourceLink(
        "sync-console", "integrations-csv",
        "speakerops_sync_console", ("event",), "organiser", AGGREGATE,
        "Resolver gap: per-item resource for thread-per-exception.",
    ),
    ResourceLink(
        "speaker-import", "integrations-csv",
        "speakerops_speaker_import", ("event",), "organiser", AGGREGATE,
        "CSV in; exports hang off the abstract/speaker/CRM consoles.",
    ),
    # 10. CRM / speaker relationships
    ResourceLink(
        "conference-memory", "crm-relationships",
        "speakerops_conference_memory", ("event",), "reviewer", AGGREGATE,
    ),
    ResourceLink(
        "conference-speaker", "crm-relationships",
        "speakerops_conference_speaker", ("event", "pk"), "reviewer", DETAIL,
        "Historical speaker detail with citations.",
    ),
    ResourceLink(
        "crm-directory", "crm-relationships",
        "speakerops_crm_org", ("organiser",), "organiser", AGGREGATE,
        "Resolver gap: per-contact/pipeline-card resource. Sponsor objects "
        "do not exist; no sponsor demo until a real model does.",
    ),
)
