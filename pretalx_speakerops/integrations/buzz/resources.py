"""Canonical resource registry backing docs/buzz-demo-map.md.

Pure data: which SpeakerOps routes anchor each judged benchmark row's Buzz
demo, and how exact each anchor really is. This module must not import
Django or any runtime plugin code; the cross-checks against the real URL
surface and the seeded role matrix live in
``tests/test_buzz_resource_registry.py``.

Honesty rules encoded here (from the PR #69 review):

- ``exactness`` distinguishes an exact operational record from a filtered
  collection, an aggregate console, or a public output. A judged row is not
  "covered" because one adjacent route happens to be record-addressable.
- ``demo_status`` is ``planned`` for every flow until a real end-to-end
  demonstration exists; nothing in this registry claims implemented AI
  capability.
- CRM is beyond the judging matrix and is excluded from ``CORE_ROWS``; it
  may never substitute for core benchmark coverage.
- ``audience`` names the least-privileged role the link is meant for, so
  demo scripts cannot hand an organizer surface to a speaker thread.
"""

from __future__ import annotations

from dataclasses import dataclass

# Judged matrix rows plus the PRD's content/production job ("which latest
# decks are AV-ready?"), which the matrix folds into speaker management but
# the benchmark scores hardest.
JUDGED_ROWS = (
    "custom-submission-forms",
    "speaker-portal",
    "abstract-management",
    "review-workflows",
    "agenda-schedule",
    "content-production",
    "embeds-publishing",
    "automated-communication",
    "performance-ux",
    "integrations-csv",
    "crm-relationships",
)

# Rows that count toward core benchmark coverage. CRM stays out by design.
CORE_ROWS = (
    "custom-submission-forms",
    "speaker-portal",
    "abstract-management",
    "review-workflows",
    "agenda-schedule",
    "content-production",
    "embeds-publishing",
)

EXACT_RECORD = "exact-record"
FILTERED_COLLECTION = "filtered-collection"
AGGREGATE_SCREEN = "aggregate-screen"
PUBLIC_OUTPUT = "public-output"
EXACTNESS = (EXACT_RECORD, FILTERED_COLLECTION, AGGREGATE_SCREEN, PUBLIC_OUTPUT)

PLANNED = "planned"
IMPLEMENTED = "implemented"

# links navigate (GET, shareable, never mutate); commands mutate (POST,
# receipted, never handed out as a link in a Buzz message).
LINK = "link"
COMMAND = "command"


@dataclass(frozen=True)
class ResourceLink:
    resource: str
    judged_row: str
    route_name: str
    url_kwargs: tuple[str, ...]
    audience: str
    object_kind: str
    exactness: str
    interaction: str = LINK
    demo_status: str = PLANNED
    note: str = ""


RESOURCES = (
    # 1. Custom submission forms
    ResourceLink(
        resource="cfp-routing-console",
        judged_row="custom-submission-forms",
        route_name="speakerops_cfp_routing",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="cfp-configuration",
        exactness=AGGREGATE_SCREEN,
        note="Form construction stays web-UI work; Buzz links to the console.",
    ),
    ResourceLink(
        resource="cfp-public-guide",
        judged_row="custom-submission-forms",
        route_name="speakerops_cfp_guide",
        url_kwargs=("event",),
        audience="public",
        object_kind="cfp-guide",
        exactness=PUBLIC_OUTPUT,
        note="What a submitter will actually see.",
    ),
    # 2. Speaker self-service portal
    ResourceLink(
        resource="speaker-checklist",
        judged_row="speaker-portal",
        route_name="speakerops_checklist",
        url_kwargs=("event",),
        audience="speaker",
        object_kind="onboarding-checklist",
        exactness=FILTERED_COLLECTION,
        note="Self-scoped: shows the signed-in speaker's tasks; cannot "
        "address an arbitrary task. Resolver gap: onboarding-task.",
    ),
    ResourceLink(
        resource="speaker-profile",
        judged_row="speaker-portal",
        route_name="speakerops_speaker_profile",
        url_kwargs=("event",),
        audience="speaker",
        object_kind="speaker-profile",
        exactness=FILTERED_COLLECTION,
        note="Self-scoped to the signed-in speaker.",
    ),
    # 3. Submission & abstract management
    ResourceLink(
        resource="abstract-console",
        judged_row="abstract-management",
        route_name="speakerops_abstract_management",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="submission-queue",
        exactness=AGGREGATE_SCREEN,
        note="Resolver gap: per-submission operational detail is a fragment.",
    ),
    ResourceLink(
        resource="submission-presenters",
        judged_row="abstract-management",
        route_name="speakerops_submission_presenters",
        url_kwargs=("event", "code"),
        audience="organiser",
        object_kind="submission",
        exactness=EXACT_RECORD,
    ),
    # 4. Evaluation & review workflows
    ResourceLink(
        resource="review-assignment",
        judged_row="review-workflows",
        route_name="speakerops_review",
        url_kwargs=("event", "pk"),
        audience="reviewer",
        object_kind="review-assignment",
        exactness=EXACT_RECORD,
        note="Reference demo: record-level route already exists.",
    ),
    ResourceLink(
        resource="round-review-assignment",
        judged_row="review-workflows",
        route_name="speakerops_round_review",
        url_kwargs=("event", "assignment"),
        audience="reviewer",
        object_kind="round-review-assignment",
        exactness=EXACT_RECORD,
    ),
    ResourceLink(
        resource="review-queue",
        judged_row="review-workflows",
        route_name="speakerops_review_queue",
        url_kwargs=("event",),
        audience="reviewer",
        object_kind="review-queue",
        exactness=FILTERED_COLLECTION,
    ),
    ResourceLink(
        resource="program-decisions",
        judged_row="review-workflows",
        route_name="speakerops_program_decisions",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="decision-wave",
        exactness=AGGREGATE_SCREEN,
        note="Decision waves confirm here; receipts mirror to the thread.",
    ),
    # 5. Agenda & schedule building
    ResourceLink(
        resource="agenda-release",
        judged_row="agenda-schedule",
        route_name="speakerops_agenda",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="schedule-release",
        exactness=AGGREGATE_SCREEN,
        note="Drag-and-drop editing is explicitly web-UI work.",
    ),
    ResourceLink(
        resource="conflicts-drilldown",
        judged_row="agenda-schedule",
        route_name="speakerops_drilldown",
        url_kwargs=("event", "kind"),
        audience="organiser",
        object_kind="exception-list",
        exactness=FILTERED_COLLECTION,
        note="kind=conflicts; also tasks/content/undecided/missing-assets. "
        "Resolver gap: schedule-conflict record.",
    ),
    # 6. Content & production (the PRD's 'which latest decks are AV-ready?')
    ResourceLink(
        resource="content-console",
        judged_row="content-production",
        route_name="speakerops_content_operations",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="content-queue",
        exactness=AGGREGATE_SCREEN,
        note="Stale/missing/requested-change rollup; fragments today.",
    ),
    ResourceLink(
        resource="session-content",
        judged_row="content-production",
        route_name="speakerops_session_content_edit",
        url_kwargs=("event", "pk"),
        audience="organiser",
        object_kind="session-content",
        exactness=EXACT_RECORD,
        interaction=COMMAND,
        note="POST-only edit command with receipt; the shareable GET "
        "destination is a content-console fragment (resolver gap).",
    ),
    ResourceLink(
        resource="speaker-content",
        judged_row="content-production",
        route_name="speakerops_speaker_content_edit",
        url_kwargs=("event", "pk"),
        audience="organiser",
        object_kind="speaker-content",
        exactness=EXACT_RECORD,
        interaction=COMMAND,
        note="POST-only edit command; shareable GET is a console fragment.",
    ),
    ResourceLink(
        resource="publication-approval",
        judged_row="content-production",
        route_name="speakerops_session_publication_approval",
        url_kwargs=("event", "pk"),
        audience="organiser",
        object_kind="publication-approval",
        exactness=EXACT_RECORD,
        interaction=COMMAND,
        note="POST-only AV-approval command for one session; approval state "
        "is read on the content console.",
    ),
    ResourceLink(
        resource="evidence-file",
        judged_row="content-production",
        route_name="speakerops_evidence_download",
        url_kwargs=("event", "pk"),
        audience="organiser",
        object_kind="evidence-version",
        exactness=EXACT_RECORD,
        note="Exact latest-version file; supersession is version-aware.",
    ),
    ResourceLink(
        resource="av-bundle",
        judged_row="content-production",
        route_name="speakerops_latest_evidence_zip",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="evidence-bundle",
        exactness=FILTERED_COLLECTION,
        note="Approved latest-files ZIP for production/AV handoff.",
    ),
    # 7. Embeds & web publishing
    ResourceLink(
        resource="embed-builder",
        judged_row="embeds-publishing",
        route_name="speakerops_embed_builder",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="embed-configuration",
        exactness=AGGREGATE_SCREEN,
    ),
    ResourceLink(
        resource="public-embed",
        judged_row="embeds-publishing",
        route_name="speakerops_embed",
        url_kwargs=("event",),
        audience="public",
        object_kind="schedule-embed",
        exactness=PUBLIC_OUTPUT,
    ),
    ResourceLink(
        resource="public-gallery",
        judged_row="embeds-publishing",
        route_name="speakerops_gallery",
        url_kwargs=("event",),
        audience="public",
        object_kind="speaker-gallery",
        exactness=PUBLIC_OUTPUT,
    ),
    ResourceLink(
        resource="public-speaker",
        judged_row="embeds-publishing",
        route_name="speakerops_public_speaker",
        url_kwargs=("event", "code"),
        audience="public",
        object_kind="public-speaker-page",
        exactness=EXACT_RECORD,
    ),
    ResourceLink(
        resource="public-session",
        judged_row="embeds-publishing",
        route_name="speakerops_public_session",
        url_kwargs=("event", "code"),
        audience="public",
        object_kind="public-session-page",
        exactness=EXACT_RECORD,
    ),
    ResourceLink(
        resource="schedule-ics",
        judged_row="embeds-publishing",
        route_name="speakerops_ics",
        url_kwargs=("event",),
        audience="public",
        object_kind="calendar-feed",
        exactness=PUBLIC_OUTPUT,
    ),
    # 8. Automated communication
    ResourceLink(
        resource="reminder-send",
        judged_row="automated-communication",
        route_name="speakerops_reminders",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="reminder-batch",
        exactness=AGGREGATE_SCREEN,
        interaction=COMMAND,
        note="POST-only confirmed send: the flagship bounded write "
        "(preview -> confirm -> receipt). Resolver gap: "
        "communication-receipt detail.",
    ),
    ResourceLink(
        resource="overdue-tasks",
        judged_row="automated-communication",
        route_name="speakerops_drilldown",
        url_kwargs=("event", "kind"),
        audience="organiser",
        object_kind="overdue-task-list",
        exactness=FILTERED_COLLECTION,
        note="kind=tasks: the recipient evidence a reminder preview cites.",
    ),
    # 9. System performance & UX
    ResourceLink(
        resource="status",
        judged_row="performance-ux",
        route_name="speakerops_status",
        url_kwargs=("event",),
        audience="public",
        object_kind="health-status",
        exactness=PUBLIC_OUTPUT,
        note="Machine-readable health for scheduled briefs.",
    ),
    ResourceLink(
        resource="operations-dashboard",
        judged_row="performance-ux",
        route_name="speakerops_dashboard",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="operations-rollup",
        exactness=AGGREGATE_SCREEN,
    ),
    # 10. Integrations & data handling
    ResourceLink(
        resource="sync-run-retry",
        judged_row="integrations-csv",
        route_name="speakerops_sync_run",
        url_kwargs=("event", "pk"),
        audience="organiser",
        object_kind="sync-run",
        exactness=EXACT_RECORD,
        interaction=COMMAND,
        note="POST-only idempotent retry command (ADR 011). Resolver gap: "
        "sync-run/sync-item GET detail for thread-per-exception links.",
    ),
    ResourceLink(
        resource="sync-console",
        judged_row="integrations-csv",
        route_name="speakerops_sync_console",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="sync-overview",
        exactness=AGGREGATE_SCREEN,
    ),
    ResourceLink(
        resource="speaker-import",
        judged_row="integrations-csv",
        route_name="speakerops_speaker_import",
        url_kwargs=("event",),
        audience="organiser",
        object_kind="csv-import",
        exactness=AGGREGATE_SCREEN,
        note="CSV in; exports hang off the abstract/speaker/CRM consoles.",
    ),
    # 11. CRM / speaker relationships (beyond the judging matrix)
    ResourceLink(
        resource="conference-memory",
        judged_row="crm-relationships",
        route_name="speakerops_conference_memory",
        url_kwargs=("event",),
        audience="reviewer",
        object_kind="history-search",
        exactness=AGGREGATE_SCREEN,
    ),
    ResourceLink(
        resource="conference-speaker",
        judged_row="crm-relationships",
        route_name="speakerops_conference_speaker",
        url_kwargs=("event", "pk"),
        audience="reviewer",
        object_kind="historical-speaker",
        exactness=EXACT_RECORD,
        note="Historical speaker detail with citations.",
    ),
    ResourceLink(
        resource="crm-directory",
        judged_row="crm-relationships",
        route_name="speakerops_crm_org",
        url_kwargs=("organiser",),
        audience="organiser",
        object_kind="crm-directory",
        exactness=AGGREGATE_SCREEN,
        note="Resolver gap: per-contact/pipeline-card resource. Sponsor "
        "objects do not exist; no sponsor demo until a real model does.",
    ),
)
