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
- ``conference_memory`` answers the issue #41 differentiation question with
  sourced corpus coverage and verified returning-speaker evidence.

Further workflow questions add functions here and expose them through
``tools/mcp_speakerops_server.py``.
"""

from django.db.models import Count, Q
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.submission.models import Submission, SubmissionStates

from .canonical_links import RESOURCES
from .conference_memory import SOURCE_NOT_PROVIDED, memory_decision_support
from .models import (
    ConferenceEdition,
    ConferenceSeries,
    HistoricalSourceIdentity,
    HistoricalSpeaker,
    HistoricalSpeakerCredit,
    HistoricalTalk,
    OnboardingTask,
    SessionPublicationApproval,
    SyncItem,
    TaskEvidence,
)
from .program.policy import classify_warnings

DEFAULT_BASE_URL = "http://localhost:8000"


def _go(resource, opaque_id):
    return f"/go/{resource}/{opaque_id}/"


def _conflict_row(row, event_slug, base_url):
    talk = row["talk"]
    competitor = row["competitor"]
    agenda = f"{base_url}{_go('agenda-release', event_slug)}"
    return {
        "conflict_key": row["conflict_key"],
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
        "competitor": {
            "pk": competitor.pk,
            "title": competitor.submission.title,
            "start": f"{competitor.start:%Y-%m-%d %H:%M}",
            "end": f"{competitor.end:%H:%M}",
            "room": str(competitor.room.name) if competitor.room_id else "Unplaced",
        },
        "links": {
            "conflict": f"{agenda}#conflict-{row['conflict_key']}",
            "talk_slot": f"{agenda}#slot-{talk.pk}",
            "competitor_slot": f"{agenda}#slot-{competitor.pk}",
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

        attention = {
            "overdue_tasks": overdue,
            "undecided_proposals": undecided,
            "unapproved_content": pending_content,
            "sync_errors": sync_errors,
        }
        blocking_reasons = []
        if schedule is None:
            blocking_reasons.append("missing_schedule")
        if blocking:
            blocking_reasons.append("schedule_conflicts")
        blocking_reasons.extend(name for name, count in attention.items() if count)

        base = base_url.rstrip("/")
        return {
            "event": event.slug,
            "release_blocked": bool(blocking_reasons),
            "blocking_reasons": blocking_reasons,
            "conflicts": [_conflict_row(row, event.slug, base) for row in conflicts],
            "attention": attention,
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
    blocking_reasons = result.get("blocking_reasons", [])
    base = result["links"]["operations"].rsplit("/go/", 1)[0]

    lines = [f"# Release readiness — {result['event']}", ""]
    if result["release_blocked"]:
        labels = ", ".join(reason.replace("_", " ") for reason in blocking_reasons)
        lines.append(f"**Blocked** — {labels or 'a release gate is unresolved'}.")
    else:
        lines.append("**Release-ready** — no release-blocking schedule warnings.")
    lines.append("")

    if conflicts or blocking_reasons:
        lines.append("## What blocks release")
        lines.append("")
        if "missing_schedule" in blocking_reasons:
            lines.append("- No work-in-progress schedule exists.")
        for key, label in (
            ("overdue_tasks", "overdue onboarding tasks"),
            ("undecided_proposals", "undecided proposals"),
            ("unapproved_content", "unapproved content records"),
            ("sync_errors", "failed synchronization records"),
        ):
            if attention[key]:
                lines.append(f"- {attention[key]} {label}.")
        for row in conflicts:
            mark = "release-blocking" if row["blocking"] else "non-blocking warning"
            talk = row["talk"]
            competitor = row["competitor"]
            lines.append(
                f"- **[type: {row['type']}]** "
                f"[conflict record]({row['links']['conflict']}) — `{mark}` — "
                f"[talk #{talk['pk']} “{talk['title']}”]({row['links']['talk_slot']}) "
                f"({talk['start']}–{talk['end']}, {talk['room']}) conflicts with "
                f"[talk #{competitor['pk']} “{competitor['title']}”]"
                f"({row['links']['competitor_slot']}) "
                f"({competitor['start']}–{competitor['end']}, {competitor['room']})."
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
            f"because these gates are unresolved: {', '.join(blocking_reasons)}."
            if result["release_blocked"]
            else "Verdict: release_blocked = false (all release gates are clear)."
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
            .prefetch_related("evidence_items", "submission__speakers")
            .order_by("definition__position", "pk")
        )
        approval_rows = list(
            SessionPublicationApproval.objects.filter(event=event)
            .select_related("submission", "reviewed_by")
            .prefetch_related("submission__speakers")
        )
        approvals = {approval.submission_id: approval for approval in approval_rows}

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
                        "owner": (
                            _display_name(approval.reviewed_by) if approval.reviewed_by_id else ""
                        ),
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

        # A publication decision is itself a content gate even when a session
        # has no upload request. Omitting it would let a pending gate disappear
        # from the AV-readiness answer.
        for approval in approval_rows:
            if approval.submission_id in sessions:
                continue
            submission = approval.submission
            sessions[submission.pk] = {
                "submission": {
                    "pk": submission.pk,
                    "code": submission.code,
                    "title": submission.title,
                },
                "speakers": [u.get_display_name() for u in submission.speakers.all()],
                "items": [],
                "publication": {
                    "status": approval.status,
                    "owner": (
                        _display_name(approval.reviewed_by) if approval.reviewed_by_id else ""
                    ),
                    "note": approval.note,
                },
            }
            order.append(submission.pk)

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
                "bundle": f"{base}{_go('av-bundle', event.slug)}",
            },
            "generated_at": timezone.now().isoformat(),
        }


# Map a content_readiness source key to its canonical registry resource so
# the message's source list can be cross-checked against canonical_links.py.
_CONTENT_SOURCE_RESOURCES = {
    "console": "content-console",
    "evidence": "evidence-file",
    "bundle": "av-bundle",
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
            "(content-console, evidence-file, av-bundle), absolutized against "
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


_CONFERENCE_MEMORY_SOURCE_RESOURCES = {
    "memory": "conference-memory",
    "crm": "crm-directory",
}


def conference_memory(event_slug, query="", base_url=DEFAULT_BASE_URL):
    """Return sourced conference-memory evidence without inventing identity links."""

    event = Event.objects.filter(slug=event_slug).select_related("organiser").first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    query = " ".join(query.strip().split())
    if len(query) > 160:
        raise ValueError("conference memory query must be at most 160 characters")

    all_talks = HistoricalTalk.objects.select_related("edition__series").prefetch_related(
        "credits__speaker"
    )
    talks = all_talks
    if query:
        talks = talks.filter(
            Q(title__icontains=query)
            | Q(abstract__icontains=query)
            | Q(track__icontains=query)
            | Q(session_format__icontains=query)
            | Q(level__icontains=query)
            | Q(topics__icontains=query)
            | Q(speakers__name__icontains=query)
            | Q(edition__name__icontains=query)
        ).distinct()
    insights = memory_decision_support(talks)
    full_insights = insights if not query else memory_decision_support(all_talks)
    base = base_url.rstrip("/")

    matching_evidence = []
    for talk in talks.order_by(
        "-edition__date_from", "edition__series__name", "edition__name", "title", "pk"
    )[:8]:
        matching_evidence.append(
            {
                "talk_pk": talk.pk,
                "title": talk.title,
                "series": talk.edition.series.name,
                "edition": talk.edition.name,
                "edition_date": (
                    talk.edition.date_from.isoformat() if talk.edition.date_from else None
                ),
                "session_format": talk.session_format or SOURCE_NOT_PROVIDED,
                "track": talk.track or SOURCE_NOT_PROVIDED,
                "topics": list(talk.topics or []),
                "speakers": [credit.name_at_source for credit in talk.credits.all()],
                "source_url": talk.source_url,
                "source_updated_at": (
                    talk.source_updated_at.isoformat() if talk.source_updated_at else None
                ),
            }
        )

    returning = []
    for speaker in insights["returning_speakers"]:
        verified_sources = list(
            HistoricalSourceIdentity.objects.filter(
                speaker=speaker,
                active=True,
                resolution_status=HistoricalSourceIdentity.VERIFIED,
                edition__series__slug="ai-engineer",
                credits__talk__in=talks,
            )
            .select_related("edition__series")
            .distinct()
            .order_by("edition__date_from", "edition__name")
        )
        returning.append(
            {
                "speaker_pk": speaker.pk,
                "name": speaker.name,
                "appearance_count": speaker.appearance_count,
                "edition_count": speaker.edition_count,
                "latest_appearance": (
                    speaker.latest_appearance.isoformat() if speaker.latest_appearance else None
                ),
                "link": f"{base}{_go('conference-speaker', f'{event.slug}~{speaker.pk}')}",
                "verified_sources": [
                    {
                        "series": identity.edition.series.name,
                        "edition": identity.edition.name,
                        "display_name": identity.display_name,
                        "source_url": identity.source_url,
                    }
                    for identity in verified_sources
                ],
            }
        )

    identity_counts = {
        row["resolution_status"]: row["count"]
        for row in HistoricalSourceIdentity.objects.filter(active=True)
        .values("resolution_status")
        .annotate(count=Count("pk"))
    }
    return {
        "event": event.slug,
        "query": query,
        "matching_talks": talks.count(),
        "scope": {
            "query_applied": bool(query),
            "matching_talks": talks.count(),
            "corpus_totals_are_unfiltered": True,
        },
        "corpus": {
            "series": ConferenceSeries.objects.count(),
            "editions": ConferenceEdition.objects.count(),
            "talks": HistoricalTalk.objects.count(),
            "speaker_credits": HistoricalSpeakerCredit.objects.count(),
            "source_identities": HistoricalSourceIdentity.objects.filter(active=True).count(),
            "people": HistoricalSpeaker.objects.count(),
        },
        "aie": {
            "talks": insights["aie"]["talks"],
            "editions": insights["aie"]["editions"],
            "missing_format": insights["aie_missing_format"],
            "missing_track": insights["aie_missing_track"],
        },
        "aie_corpus": {
            "talks": full_insights["aie"]["talks"],
            "editions": full_insights["aie"]["editions"],
            "missing_format": full_insights["aie_missing_format"],
            "missing_track": full_insights["aie_missing_track"],
        },
        "corpus_gaps": {
            "missing_format": all_talks.filter(
                session_format__in=("", SOURCE_NOT_PROVIDED)
            ).count(),
            "missing_track": all_talks.filter(track__in=("", SOURCE_NOT_PROVIDED)).count(),
        },
        "evidence_sample": matching_evidence,
        "topic_signals": insights["topics"],
        "format_signals": insights["formats"],
        "track_signals": insights["tracks"],
        "returning_speakers": returning,
        "identity_evidence": identity_counts,
        "missing_metadata_is_not_inferred": True,
        "links": {
            "memory": f"{base}{_go('conference-memory', event.slug)}",
            "crm": f"{base}{_go('crm-directory', event.organiser.slug)}",
        },
        "generated_at": timezone.now().isoformat(),
    }


def render_conference_memory(result):
    corpus = result["corpus"]
    aie = result["aie"]
    aie_corpus = result.get("aie_corpus", aie)
    corpus_gaps = result.get(
        "corpus_gaps",
        {"missing_format": aie["missing_format"], "missing_track": aie["missing_track"]},
    )
    lines = [f"# Conference Memory — {result['event']}", ""]
    lines.append(
        f"**Full evidence corpus (unfiltered):** {corpus['series']} series, "
        f"{corpus['talks']} sourced talks across {corpus['editions']} editions, "
        f"{corpus['speaker_credits']} speaker credits, "
        f"{corpus['source_identities']} active source identities, and {corpus['people']} people."
    )
    if result["query"]:
        lines.append(
            f"**Query-matched subset:** `{result['query']}` matched "
            f"{result['matching_talks']} sourced talks. Signals and returning-speaker "
            "counts below use only this subset."
        )
    lines.extend(("", "## What the evidence says", ""))
    for label, signals in (
        ("Topic", result.get("topic_signals", [])),
        ("Format", result.get("format_signals", [])),
        ("Track", result.get("track_signals", [])),
    ):
        if signals:
            lines.append(f"{label} frequency in the matching evidence (AIE / peer conferences):")
            for signal in signals:
                lines.append(f"- **{signal['label']}** — {signal['aie']} / {signal['peers']}")
        else:
            lines.append(
                f"No source-declared {label.casefold()} labels matched; none was inferred."
            )
    if result["evidence_sample"]:
        lines.extend(("", "Recent matching source records:", ""))
        for talk in result["evidence_sample"]:
            speakers = ", ".join(talk["speakers"]) or "speaker not supplied"
            labels = ", ".join(talk["topics"]) or "topics not supplied"
            lines.append(
                f"- [{talk['title']}]({talk['source_url']}) — {talk['series']} / "
                f"{talk['edition']}; {speakers}; format `{talk['session_format']}`; "
                f"track `{talk['track']}`; topics {labels}."
            )
    lines.append(
        "These are programming-memory signals, not acceptance recommendations; "
        "the chair retains judgment."
    )
    lines.extend(("", "## Verified returning AIE speakers", ""))
    if not result["returning_speakers"]:
        lines.append(
            "No speaker has verified source identities across at least two matching AIE editions."
        )
    for speaker in result["returning_speakers"]:
        lines.append(
            f"- [{speaker['name']}]({speaker['link']}) — {speaker['appearance_count']} talks "
            f"across {speaker['edition_count']} verified editions."
        )
        for source in speaker["verified_sources"]:
            lines.append(
                f"  - [{source['series']} / {source['edition']}]({source['source_url']}) "
                f"as {source['display_name']}"
            )
    provenance_scope = []
    if result["query"]:
        provenance_scope.append(
            f"- Query-matched AIE subset: {aie['talks']} talks across "
            f"{aie['editions']} editions; format omitted on {aie['missing_format']} and "
            f"track omitted on {aie['missing_track']}."
        )
    provenance_scope.extend(
        (
            f"- Full AIE corpus: {aie_corpus['talks']} talks across "
            f"{aie_corpus['editions']} editions; format omitted on "
            f"{aie_corpus['missing_format']} and track omitted on "
            f"{aie_corpus['missing_track']}.",
            f"- Full corpus omissions: {corpus_gaps['missing_format']} formats and "
            f"{corpus_gaps['missing_track']} tracks remain `{SOURCE_NOT_PROVIDED}` or blank.",
        )
    )
    lines.extend(
        (
            "",
            "## Provenance limits",
            "",
            *provenance_scope,
            "- Missing metadata and unverified identity recurrence are never inferred.",
            "",
            "## Continue in the system of record",
            "",
            f"- [Conference Memory evidence]({result['links']['memory']})",
            f"- [Source-linked CRM]({result['links']['crm']})",
            "",
            "## Trace of inference",
            "",
            f"1. Resolved event `{result['event']}` under the bridge's allowed event scope.",
            f"2. Queried {result['matching_talks']} matching sourced talk records and returned "
            f"a bounded sample of {len(result['evidence_sample'])} source-linked records.",
            "3. Counted recurrence only where active source identities are explicitly verified "
            "across at least two AIE editions in the current evidence scope.",
            "4. Preserved source-declared metadata gaps without filling them.",
            "5. Built permission-aware Conference Memory and CRM links from the "
            "canonical registry.",
            "",
            f"Generated {result['generated_at']} (ISO-8601).",
        )
    )
    return "\n".join(lines)


def conference_memory_message(event_slug, query="", base_url=DEFAULT_BASE_URL):
    return render_conference_memory(conference_memory(event_slug, query=query, base_url=base_url))
