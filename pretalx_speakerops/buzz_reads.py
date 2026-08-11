"""Typed read tools backing the Buzz agent bridge.

Each function answers one workflow question from the system of record and
returns JSON-safe data plus the canonical ``go/`` links to the exact views
(see ``docs/product-standard-buzz-workflows.md``). The model never gets
database access; it gets these typed reads only. Each read has a
``*_message`` variant that renders the operator-facing answer (verdict,
canonical URL source list, trace of inference) for the agent to relay.

- ``release_readiness`` answers "can we release?" and "what blocks release?"
  (demo-map row 5).
- ``content_readiness`` answers "which latest decks are AV-ready, and who
  owns what's not?" (demo-map row 6).

Further workflow questions add functions here and expose them through
``tools/mcp_speakerops_server.py``.
"""

from django.db.models import Count, Q
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.submission.models import Submission, SubmissionStates

from .canonical_links import RESOURCES
from .models import (
    OnboardingTask,
    SessionPublicationApproval,
    SyncItem,
    TaskEvidence,
)
from .program.policy import classify_warnings

DEFAULT_BASE_URL = "http://localhost:8000"


def _go(resource, opaque_id):
    return f"/go/{resource}/{opaque_id}/"


def _conflict_row(row):
    talk = row["talk"]
    return {
        "type": row["category"],
        "message": row["message"],
        "resource": row["resource"],
        "blocking": row["blocking"],
        "talk": {
            "pk": talk.pk,
            "title": talk.submission.title,
            "start": f"{talk.start:%Y-%m-%d %H:%M}",
            "end": f"{talk.end:%H:%M}",
            "room": str(talk.room.name) if talk.room_id else "Unplaced",
        },
    }


def release_readiness(event_slug, base_url=DEFAULT_BASE_URL):
    """Answer "can we release?" for one event.

    Returns release-blocking schedule conflicts (named, with owner-facing
    detail), the attention rollup, schedule version state, and one-click
    ``go/`` links to the exact views.
    """
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    with scope(event=event):
        schedule = event.wip_schedule
        conflicts = classify_warnings(schedule) if schedule else []
        blocking = [row for row in conflicts if row["blocking"]]

        today = timezone.localdate()
        active_states = (OnboardingTask.PENDING, OnboardingTask.REOPENED)
        overdue = OnboardingTask.objects.filter(event=event).aggregate(
            value=Count("pk", filter=Q(due_date__lt=today, status__in=active_states)),
        )["value"]
        undecided = Submission.objects.filter(event=event, state=SubmissionStates.SUBMITTED).count()
        pending_content = SessionPublicationApproval.objects.filter(
            event=event, status=SessionPublicationApproval.PENDING
        ).count()
        sync_errors = SyncItem.objects.filter(event=event, status=SyncItem.FAILED).count()

        base = base_url.rstrip("/")
        return {
            "event": event.slug,
            "release_blocked": bool(blocking),
            "conflicts": [_conflict_row(row) for row in conflicts],
            "attention": {
                "overdue_tasks": overdue,
                "undecided_proposals": undecided,
                "unapproved_content": pending_content,
                "sync_errors": sync_errors,
            },
            "schedule": {
                "has_wip": schedule is not None,
                "published_version": (
                    event.current_schedule.version if event.current_schedule else None
                ),
            },
            "links": {
                "conflicts": f"{base}{_go('conflicts-drilldown', f'{event.slug}~conflicts')}",
                "agenda": f"{base}{_go('agenda-release', event.slug)}",
                "content": f"{base}{_go('content-console', event.slug)}",
                "decisions": f"{base}{_go('program-decisions', event.slug)}",
                "operations": f"{base}{_go('operations-dashboard', event.slug)}",
            },
            "generated_at": timezone.now().isoformat(),
        }


# Map a release_readiness link key to its canonical registry resource name so
# the message's source list can be cross-checked against canonical_links.py.
_SOURCE_RESOURCES = {
    "conflicts": "conflicts-drilldown",
    "agenda": "agenda-release",
    "content": "content-console",
    "decisions": "program-decisions",
    "operations": "operations-dashboard",
}


def _canonical(resource):
    return next((link for link in RESOURCES if link.resource == resource), None)


def render_release_readiness(result):
    """Render a release_readiness payload as the operator-facing message.

    One message, three parts: the verdict and what blocks release, the
    canonical URL source list (cross-checkable against the registry), and the
    trace of inference showing how each number was derived.
    """
    conflicts = result["conflicts"]
    blocking = [row for row in conflicts if row["blocking"]]
    attention = result["attention"]
    schedule = result["schedule"]
    base = result["links"]["operations"].rsplit("/go/", 1)[0]

    lines = [f"# Release readiness — {result['event']}", ""]
    if result["release_blocked"]:
        lines.append(
            f"**Blocked** — {len(blocking)} of {len(conflicts)} schedule "
            "warnings are release-blocking."
        )
    else:
        lines.append("**Release-ready** — no release-blocking schedule warnings.")
    lines.append("")

    if conflicts:
        lines.append("## What blocks release")
        lines.append("")
        for row in conflicts:
            mark = "release-blocking" if row["blocking"] else "non-blocking warning"
            talk = row["talk"]
            lines.append(
                f"- **[type: {row['type']}]** {row['message']} — `{mark}` — "
                f'talk #{talk["pk"]} "{talk["title"]}" '
                f"({talk['start']}–{talk['end']}, {talk['room']})"
            )
        lines.append("")

    lines.append("## Attention rollup")
    lines.append("")
    lines.append("| Signal | Count |")
    lines.append("| --- | --- |")
    for name, value in (
        ("overdue tasks", attention["overdue_tasks"]),
        ("undecided proposals", attention["undecided_proposals"]),
        ("unapproved content", attention["unapproved_content"]),
        ("sync errors", attention["sync_errors"]),
    ):
        lines.append(f"| {name} | {value} |")
    lines.append("")

    lines.append("## Schedule state")
    lines.append("")
    lines.append(f"- WIP schedule: {'present' if schedule['has_wip'] else 'absent'}")
    lines.append(f"- Published version: {schedule['published_version'] or 'none'}")
    lines.append("")

    lines.append(
        "## Sources — canonical URL list (check against `pretalx_speakerops/canonical_links.py`)"
    )
    lines.append("")
    lines.append("| Resource | go/ link | Routes to | Audience | Exactness |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, resource in _SOURCE_RESOURCES.items():
        canonical = _canonical(resource)
        lines.append(
            f"| {resource} | {result['links'][key]} | "
            f"{canonical.route_name if canonical else '?'} | "
            f"{canonical.audience if canonical else '?'} | "
            f"{canonical.exactness if canonical else '?'} |"
        )
    lines.append("")

    lines.append("## Trace of inference")
    lines.append("")
    trace = [
        f"Resolved event `{result['event']}` from the system of record.",
        f"Read WIP schedule; has_wip = {str(schedule['has_wip']).lower()}.",
        (
            "Classified schedule warnings via `classify_warnings`: "
            f"{len(conflicts)} rows, {len(blocking)} release-blocking."
        ),
        (
            "Computed attention rollup: "
            f"overdue {attention['overdue_tasks']}, "
            f"undecided {attention['undecided_proposals']}, "
            f"unapproved {attention['unapproved_content']}, "
            f"sync errors {attention['sync_errors']}."
        ),
        f"Read published schedule version: {schedule['published_version'] or 'none'}.",
        (
            f"Built {len(_SOURCE_RESOURCES)} go/ links from the canonical "
            f"registry, absolutized against {base}."
        ),
        (
            f"Verdict: release_blocked = {str(result['release_blocked']).lower()} "
            "because release-blocking schedule warnings exist."
            if result["release_blocked"]
            else "Verdict: release_blocked = false (no blocking warnings)."
        ),
    ]
    for index, step in enumerate(trace, 1):
        lines.append(f"{index}. {step}")
    lines.append("")
    lines.append(f"Generated {result['generated_at']} (ISO-8601).")
    return "\n".join(lines)


def release_readiness_message(event_slug, base_url=DEFAULT_BASE_URL):
    """Read-tool message variant: the operator-facing formatted answer.

    Runs the same query as ``release_readiness`` but returns the rendered
    message (verdict, canonical URL source list, inference trace) that the
    agent relays verbatim — the workflow answer must live in the message +
    links, not in a raw payload the agent has to translate.
    """
    return render_release_readiness(release_readiness(event_slug, base_url=base_url))


def _display_name(user):
    # Empty string for "no user" so call sites can apply their own fallback
    # label ("not yet reviewed", "unknown reviewer") with `or`.
    return user.get_display_name() if user else ""


def _evidence_info(evidence, event_slug, base_url):
    if evidence is None or evidence.upload is None:
        return None
    return {
        "version": evidence.version,
        "filename": evidence.upload.name.rsplit("/", 1)[-1],
        "size": evidence.size,
        "uploaded_at": evidence.created_at.isoformat(),
        "review_status": evidence.review_status,
        "review_note": evidence.review_note,
        "reviewed_by": _display_name(evidence.reviewed_by),
        "url": f"{base_url}{_go('evidence-file', f'{event_slug}~{evidence.pk}')}",
    }


def _classify_file_request(task, evidence, base_url):
    """Classify one upload file request into its state and owner.

    Returns ``(state, owner, stale, detail)`` where ``state`` is one of
    ``missing``, ``pending``, ``changes_requested``, ``stale``, ``approved``
    and ``detail`` is the latest-evidence info (or ``None``). ``stale`` means
    a previously approved version has been superseded by a newer upload that
    is not yet approved — the AV-ready approval no longer matches the latest
    file.
    """
    latest = evidence[0] if evidence else None
    if latest is None or latest.upload is None:
        return "missing", _display_name(task.speaker), False, None
    detail = _evidence_info(latest, task.event.slug, base_url)
    if latest.review_status == TaskEvidence.APPROVED:
        return "approved", _display_name(task.speaker), False, detail
    superseded = any(item.review_status == TaskEvidence.APPROVED for item in evidence[1:])
    if latest.review_status == TaskEvidence.CHANGES_REQUESTED:
        owner = _display_name(latest.reviewed_by) or "unknown reviewer"
        state = "stale" if superseded else "changes_requested"
        return state, owner, superseded, detail
    state = "stale" if superseded else "pending"
    return state, _display_name(task.speaker), superseded, detail


def content_readiness(event_slug, base_url=DEFAULT_BASE_URL):
    """Answer "which latest decks are AV-ready, and who owns what's not?".

    Groups every upload file request (``completion_evaluator="upload"``) by
    session, classifies each request by its latest ``TaskEvidence`` version,
    folds in the per-session publication gate, and returns the AV-ready and
    not-AV-ready sets with owners and canonical links.
    """
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    base = base_url.rstrip("/")
    with scope(event=event):
        tasks = list(
            OnboardingTask.objects.filter(
                event=event,
                definition__completion_evaluator="upload",
            )
            .select_related("speaker", "definition", "submission")
            .prefetch_related("evidence_items")
            .order_by("definition__position", "pk")
        )
        approvals = {
            approval.submission_id: approval
            for approval in SessionPublicationApproval.objects.filter(event=event)
        }

        sessions = {}
        order = []
        for task in tasks:
            if task.submission_id is not None:
                key = task.submission_id
                if key not in sessions:
                    submission = task.submission
                    sessions[key] = {
                        "submission": {
                            "pk": submission.pk,
                            "code": submission.code,
                            "title": submission.title,
                        },
                        "speakers": [u.get_display_name() for u in submission.speakers.all()],
                        "items": [],
                        "publication": None,
                    }
                    order.append(key)
                session = sessions[key]
                approval = approvals.get(key)
                if approval is not None and session["publication"] is None:
                    session["publication"] = {
                        "status": approval.status,
                        "owner": _display_name(approval.reviewed_by),
                        "note": approval.note,
                    }
            else:
                key = ("task", task.pk)
                sessions[key] = {
                    "submission": {
                        "pk": None,
                        "code": "",
                        "title": f"{task.speaker.get_display_name()} — {task.definition.name}",
                    },
                    "speakers": [_display_name(task.speaker)],
                    "items": [],
                    "publication": None,
                }
                order.append(key)
                session = sessions[key]

            evidence = list(task.evidence_items.all())
            state, owner, stale, detail = _classify_file_request(task, evidence, base)
            session["items"].append(
                {
                    "file_request": task.definition.name,
                    "task_pk": task.pk,
                    "state": state,
                    "owner": owner,
                    "stale": stale,
                    "note": detail["review_note"] if detail else "",
                    "due_date": task.due_date.isoformat() if task.due_date else None,
                    "latest_evidence": detail,
                }
            )

        rows = []
        for key in order:
            session = sessions[key]
            items = session["items"]
            blockers = [item for item in items if item["state"] != "approved"]
            publication = session["publication"]
            if (
                publication is not None
                and publication["status"] != SessionPublicationApproval.APPROVED
            ):
                state = (
                    "publication_pending"
                    if publication["status"] == SessionPublicationApproval.PENDING
                    else "publication_changes"
                )
                owner = publication["owner"] or "not yet reviewed"
            elif blockers:
                state = blockers[0]["state"]
                owner = blockers[0]["owner"]
            else:
                state = "ready"
                owner = ""
            session["state"] = state
            session["owner"] = owner
            session["blocked_by"] = None if state == "ready" else state
            rows.append(session)

        ready = [row for row in rows if row["state"] == "ready"]
        not_ready = [row for row in rows if row["state"] != "ready"]
        item_states = [item["state"] for row in rows for item in row["items"]]
        return {
            "event": event.slug,
            "ready": ready,
            "not_ready": not_ready,
            "rollup": {
                "upload_tasks": len(tasks),
                "sessions": len(rows),
                "ready": len(ready),
                "not_ready": len(not_ready),
                "missing_file_requests": item_states.count("missing"),
                "pending_review": item_states.count("pending"),
                "changes_requested": item_states.count("changes_requested"),
                "stale": item_states.count("stale"),
                "publication_approved": sum(
                    row["publication"] is not None
                    and row["publication"]["status"] == SessionPublicationApproval.APPROVED
                    for row in rows
                ),
                "publication_pending": sum(
                    row["publication"] is not None
                    and row["publication"]["status"] == SessionPublicationApproval.PENDING
                    for row in rows
                ),
                "publication_changes": sum(
                    row["publication"] is not None
                    and row["publication"]["status"] == SessionPublicationApproval.CHANGES_REQUESTED
                    for row in rows
                ),
            },
            "sources": {
                "console": f"{base}{_go('content-console', event.slug)}",
                "evidence": f"{base}/go/evidence-file/{event.slug}~{{evidence_pk}}/",
            },
            "generated_at": timezone.now().isoformat(),
        }


# Map a content_readiness source key to its canonical registry resource so
# the message's source list can be cross-checked against canonical_links.py.
_CONTENT_SOURCE_RESOURCES = {
    "console": "content-console",
    "evidence": "evidence-file",
}


def render_content_readiness(result):
    """Render a content_readiness payload as the operator-facing message.

    Same shape as ``render_release_readiness``: the verdict and the not-ready
    set with owners, the canonical URL source list, and the trace of
    inference.
    """
    ready = result["ready"]
    not_ready = result["not_ready"]
    rollup = result["rollup"]
    base = result["sources"]["console"].rsplit("/go/", 1)[0]

    lines = [f"# Content readiness — {result['event']}", ""]
    if not_ready:
        lines.append(
            f"**Not AV-ready** — {len(not_ready)} of {rollup['sessions']} "
            "sessions have outstanding content."
        )
    else:
        lines.append(f"**AV-ready** — all {rollup['sessions']} sessions are ready.")
    lines.append("")

    if not_ready:
        lines.append("## Not AV-ready (owner)")
        lines.append("")
        for row in not_ready:
            subject = row["submission"]
            code = f" #{subject['code']}" if subject["code"] else ""
            label = f"{subject['title']}{code}"
            if row["state"].startswith("publication"):
                publication = row["publication"]
                note = f' — "{publication["note"]}"' if publication and publication["note"] else ""
                lines.append(
                    f"- **{label}** — **[publication: {row['state']}]** "
                    f"gate owner **{row['owner']}**{note}"
                )
                continue
            for item in row["items"]:
                if item["state"] == "approved":
                    continue
                note = f' — "{item["note"]}"' if item["note"] else ""
                evidence = item["latest_evidence"]
                link = (
                    f" — [evidence v{evidence['version']}]({evidence['url']})" if evidence else ""
                )
                lines.append(
                    f"- **{label}** — **[type: {item['state']}]** "
                    f"{item['file_request']} — owner **{item['owner']}**{note}{link}"
                )
        lines.append("")

    lines.append(f"## AV-ready ({len(ready)})")
    lines.append("")
    if ready:
        for row in ready:
            subject = row["submission"]
            code = f" #{subject['code']}" if subject["code"] else ""
            label = f"{subject['title']}{code}"
            versions = ", ".join(
                f"{item['file_request']} v{item['latest_evidence']['version']}"
                for item in row["items"]
                if item["latest_evidence"]
            )
            lines.append(f"- {label} — {versions}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Rollup")
    lines.append("")
    lines.append("| Signal | Count |")
    lines.append("| --- | --- |")
    for name, value in (
        ("upload file requests", rollup["upload_tasks"]),
        ("sessions", rollup["sessions"]),
        ("ready", rollup["ready"]),
        ("not ready", rollup["not_ready"]),
        ("missing file requests", rollup["missing_file_requests"]),
        ("pending review", rollup["pending_review"]),
        ("changes requested", rollup["changes_requested"]),
        ("stale (approved superseded)", rollup["stale"]),
    ):
        lines.append(f"| {name} | {value} |")
    lines.append("")

    lines.append(
        "## Sources — canonical URL list (check against `pretalx_speakerops/canonical_links.py`)"
    )
    lines.append("")
    lines.append("| Resource | go/ link | Routes to | Audience | Exactness |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, resource in _CONTENT_SOURCE_RESOURCES.items():
        canonical = _canonical(resource)
        lines.append(
            f"| {resource} | {result['sources'][key]} | "
            f"{canonical.route_name if canonical else '?'} | "
            f"{canonical.audience if canonical else '?'} | "
            f"{canonical.exactness if canonical else '?'} |"
        )
    lines.append("")

    lines.append("## Trace of inference")
    lines.append("")
    trace = [
        f"Resolved event `{result['event']}` from the system of record.",
        (
            f"Read {rollup['upload_tasks']} upload file-request tasks "
            "(completion_evaluator='upload') from the system of record."
        ),
        "For each task, read the latest TaskEvidence version and its review state.",
        (
            f"Classified per file request: {rollup['missing_file_requests']} missing, "
            f"{rollup['pending_review']} pending review, "
            f"{rollup['changes_requested']} changes requested, "
            f"{rollup['stale']} stale (approved version superseded)."
        ),
        (
            f"Read the publication gate per session: "
            f"{rollup['publication_approved']} approved, "
            f"{rollup['publication_pending']} pending, "
            f"{rollup['publication_changes']} changes requested."
        ),
        (
            "Built go/ links from the canonical registry "
            "(content-console, evidence-file), absolutized against "
            f"{base}."
        ),
        (f"Verdict: {rollup['not_ready']} of {rollup['sessions']} sessions not AV-ready."),
    ]
    for index, step in enumerate(trace, 1):
        lines.append(f"{index}. {step}")
    lines.append("")
    lines.append(f"Generated {result['generated_at']} (ISO-8601).")
    return "\n".join(lines)


def content_readiness_message(event_slug, base_url=DEFAULT_BASE_URL):
    """Read-tool message variant for content readiness (row 6)."""
    return render_content_readiness(content_readiness(event_slug, base_url=base_url))
