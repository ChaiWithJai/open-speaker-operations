"""Read-only Buzz answers for speaker coordination and speaker self-service.

These reads deliberately return evidence and links, never commands.  The
caller is responsible for binding the coordinator or speaker principal before
invoking them; ``speaker_next_actions`` additionally scopes its database query
to the supplied speaker email and never serializes co-presenters.
"""

import uuid
from urllib.parse import quote

from django.db.models import F
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import User

from pretalx_speakerops.canonical_links import RESOURCES
from pretalx_speakerops.models import OnboardingTask
from pretalx_speakerops.workflow_action_tokens import ACTION_BATCH_LIMIT, create_action_snapshot

DEFAULT_BASE_URL = "http://localhost:8000"
ACTIVE_TASK_STATES = (OnboardingTask.PENDING, OnboardingTask.REOPENED)


def _go(base_url, resource, opaque_id, fragment=""):
    url = f"{base_url.rstrip('/')}/go/{resource}/{opaque_id}/"
    return f"{url}#{fragment}" if fragment else url


def _canonical_source(resource, url, evidence):
    link = next(item for item in RESOURCES if item.resource == resource)
    return {
        "resource": resource,
        "url": url,
        "route_name": link.route_name,
        "audience": link.audience,
        "exactness": link.exactness,
        "interaction": link.interaction,
        "evidence": evidence,
    }


def _event(event_slug):
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    return event


def _task_row(task, task_url):
    submission = None
    if task.submission_id:
        submission = {
            "pk": task.submission_id,
            "code": task.submission.code,
            "title": task.submission.title,
        }
    return {
        "task_pk": task.pk,
        "name": task.definition.name,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "submission": submission,
        "url": task_url,
    }


def speaker_nudges(
    event_slug,
    base_url=DEFAULT_BASE_URL,
    requesting_principal="speakerops-direct-read",
    claimed_channel_id="",
    claimed_trigger_event_id="",
):
    """Answer the coordinator question, "Who needs a nudge today?"

    Only overdue pending/reopened tasks are returned.  Results are ranked by
    oldest deadline first and then deterministically by recipient and task.
    The result is a preview: it neither queues mail nor creates a receipt.
    """
    event = _event(event_slug)
    today = timezone.localdate()
    correlation_id = str(uuid.uuid4())
    filtered_url = _go(base_url, "overdue-tasks", f"{event.slug}~tasks")

    with scope(event=event):
        tasks = list(
            OnboardingTask.objects.filter(
                event=event,
                status__in=ACTIVE_TASK_STATES,
                due_date__lt=today,
            )
            .select_related("speaker", "definition", "submission")
            .order_by(
                "due_date",
                "speaker__name",
                "speaker__email",
                "definition__position",
                "pk",
            )
        )

    recipients = []
    recipient_rows = {}
    overdue_tasks = []
    for task in tasks:
        exact_url = f"{filtered_url}#task-{task.pk}"
        row = _task_row(task, exact_url)
        row["recipient"] = {
            "name": task.speaker.get_display_name(),
            "email": task.speaker.email,
        }
        row["days_overdue"] = (today - task.due_date).days
        overdue_tasks.append(row)

        recipient = recipient_rows.get(task.speaker_id)
        if recipient is None:
            recipient = {
                "speaker": row["recipient"],
                "overdue_task_count": 0,
                "earliest_due_date": row["due_date"],
                "tasks": [],
                "links": {
                    "filtered_overdue_tasks": filtered_url,
                    "first_exact_task": exact_url,
                    "contact": (
                        f"mailto:{quote(task.speaker.email)}"
                        f"?subject={quote(f'{event.name} — speaker action needed')}"
                    ),
                },
            }
            recipient_rows[task.speaker_id] = recipient
            recipients.append(recipient)
        recipient["tasks"].append(row)
        recipient["overdue_task_count"] += 1

    generated_at = timezone.now().isoformat()
    action_target_ids = [task.pk for task in tasks[:ACTION_BATCH_LIMIT]]
    try:
        snapshot = create_action_snapshot(
            event=event,
            workflow="speaker_nudges",
            correlation_id=correlation_id,
            target_ids=action_target_ids,
            principal=requesting_principal,
            claimed_channel_id=claimed_channel_id,
            claimed_trigger_event_id=claimed_trigger_event_id,
        )
    except Exception:
        snapshot = None
    confirmation_url = (
        _go(
            base_url,
            "speaker-nudge-preview",
            f"{event.slug}~{correlation_id}~{snapshot.nonce}",
        )
        if snapshot
        else None
    )
    sources = [
        _canonical_source(
            "overdue-tasks",
            filtered_url,
            (
                "Filtered to this event and active tasks whose due date is before "
                f"{today.isoformat()}; exact task URLs add the rendered row fragment."
            ),
        )
    ]
    return {
        "event": event.slug,
        "question": "Who needs a nudge today?",
        "as_of": today.isoformat(),
        "preview_only": True,
        "mutation_performed": False,
        "action_preview": {
            "available": snapshot is not None,
            "correlation_id": correlation_id,
            "confirmation_url": confirmation_url,
            "requires_authenticated_organiser": True,
            "requires_explicit_web_confirmation": True,
            "receipt_tool": "workflow_action_receipts",
            "batch_limit": ACTION_BATCH_LIMIT,
            "target_count": len(action_target_ids),
            "truncated_count": max(0, len(tasks) - len(action_target_ids)),
            "limitation": (
                None
                if snapshot
                else "Confirmation preview unavailable because shared cache is unavailable."
            ),
        },
        "recipients": recipients,
        "overdue_tasks": overdue_tasks,
        "rollup": {
            "recipients": len(recipients),
            "overdue_tasks": len(overdue_tasks),
        },
        "links": {"filtered_overdue_tasks": filtered_url},
        "sources": sources,
        "trace": [
            f"Resolved event `{event.slug}` from the system of record.",
            (
                "Selected only pending or reopened onboarding tasks with due_date "
                f"before {today.isoformat()}."
            ),
            "Ranked tasks by oldest deadline, recipient name/email, task position, and id.",
            f"Grouped {len(overdue_tasks)} tasks into {len(recipients)} named recipients.",
            "Built one canonical filtered collection link and exact rendered-row fragments.",
            (
                "Built a correlated GET-safe confirmation preview; "
                "it does not execute on navigation."
                if snapshot
                else "Shared cache was unavailable; returned the typed read without an action link."
            ),
            f"Capped the confirmable batch at {ACTION_BATCH_LIMIT} targets.",
            "Performed no reminder send, mail queue, receipt creation, or task mutation.",
        ],
        "generated_at": generated_at,
    }


def render_speaker_nudges(result):
    """Render a grounded, preview-only coordinator answer."""
    lines = [f"# Speaker nudges — {result['event']}", ""]
    if not result["recipients"]:
        lines.append(f"**No nudges due** as of {result['as_of']}.")
    else:
        lines.append(
            f"**Preview only:** {result['rollup']['recipients']} recipients have "
            f"{result['rollup']['overdue_tasks']} overdue tasks. Nothing has been sent."
        )
        lines.append("")
        for recipient in result["recipients"]:
            speaker = recipient["speaker"]
            lines.append(f"## {speaker['name']} <{speaker['email']}>")
            lines.append("")
            for task in recipient["tasks"]:
                session = task["submission"]["title"] if task["submission"] else "event-wide"
                lines.append(
                    f"- [{task['name']}]({task['url']}) — due {task['due_date']} "
                    f"({task['days_overdue']} days overdue), {session}"
                )
            lines.append("")
    lines.extend(
        [
            "## Source",
            "",
            f"- [Filtered overdue task list]({result['links']['filtered_overdue_tasks']})",
            (
                "- [Review and confirm this action]"
                f"({result['action_preview']['confirmation_url']})"
                if result["action_preview"]["available"]
                else f"- Action unavailable: {result['action_preview']['limitation']}"
            ),
            f"- Correlation: `{result['action_preview']['correlation_id']}`",
            "",
            "## Trace of inference",
            "",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    lines.extend(["", f"Generated {result['generated_at']} (ISO-8601)."])
    return "\n".join(lines)


def speaker_nudges_message(event_slug, base_url=DEFAULT_BASE_URL, **kwargs):
    return render_speaker_nudges(speaker_nudges(event_slug, base_url=base_url, **kwargs))


def speaker_next_actions(event_slug, subject_email, base_url=DEFAULT_BASE_URL):
    """Answer "What do I owe?" for exactly one event speaker.

    The email is an identity scope, not a search hint: it must match a user
    attached to a submission in this event.  No co-speaker identity is loaded
    or serialized.
    """
    event = _event(event_slug)
    normalized_email = subject_email.strip().lower()
    checklist_url = _go(base_url, "speaker-checklist", event.slug)
    profile_url = _go(base_url, "speaker-profile", event.slug)

    with scope(event=event):
        speaker = (
            User.objects.filter(
                submissions__event=event,
                email__iexact=normalized_email,
            )
            .distinct()
            .first()
        )
        if speaker is None:
            raise KeyError(f"speaker is not attached to event: {subject_email}")

        tasks = list(
            OnboardingTask.objects.filter(
                event=event,
                speaker=speaker,
                status__in=ACTIVE_TASK_STATES,
            )
            .select_related("definition", "submission")
            .order_by(F("due_date").asc(nulls_last=True), "definition__position", "pk")
        )
        submissions = list(
            event.submissions.filter(speakers=speaker)
            .only("pk", "code", "title")
            .order_by("title", "pk")
        )

    action_rows = []
    today = timezone.localdate()
    for task in tasks:
        row = _task_row(task, f"{checklist_url}#task-{task.pk}-title")
        row["overdue"] = bool(task.due_date and task.due_date < today)
        action_rows.append(row)

    sessions = [
        {
            "pk": submission.pk,
            "code": submission.code,
            "title": submission.title,
            "url": _go(
                base_url,
                "own-submission-presenters",
                f"{event.slug}~{submission.code}",
            ),
        }
        for submission in submissions
    ]
    source_rows = [
        _canonical_source(
            "speaker-checklist",
            checklist_url,
            "Self-scoped task collection; task links add exact rendered-heading fragments.",
        ),
        _canonical_source(
            "speaker-profile",
            profile_url,
            "Self-scoped event speaker profile.",
        ),
    ]
    source_rows.extend(
        _canonical_source(
            "own-submission-presenters",
            session["url"],
            f"Exact attached submission `{session['code']}`.",
        )
        for session in sessions
    )
    generated_at = timezone.now().isoformat()
    return {
        "event": event.slug,
        "question": "What do I owe?",
        "subject": {
            "name": speaker.get_display_name(),
            "email": speaker.email,
        },
        "tasks": action_rows,
        "sessions": sessions,
        "rollup": {
            "open_tasks": len(action_rows),
            "overdue_tasks": sum(task["overdue"] for task in action_rows),
            "sessions": len(sessions),
        },
        "links": {
            "checklist": checklist_url,
            "profile": profile_url,
        },
        "sources": source_rows,
        "trace": [
            f"Resolved event `{event.slug}` from the system of record.",
            "Matched exactly one event-attached speaker by normalized email.",
            "Selected only that speaker's pending or reopened onboarding tasks.",
            "Selected only submissions to which that speaker is attached.",
            "Did not load or serialize co-presenter identities.",
            f"Built {len(source_rows)} permission-aware canonical links.",
            "Performed no profile, submission, task, evidence, mail, or receipt mutation.",
        ],
        "generated_at": generated_at,
    }


def render_speaker_next_actions(result):
    """Render a grounded answer scoped to one speaker."""
    subject = result["subject"]
    lines = [f"# Your next actions — {result['event']}", "", f"For **{subject['name']}**.", ""]
    if result["tasks"]:
        lines.append(
            f"You have **{result['rollup']['open_tasks']} open tasks** "
            f"({result['rollup']['overdue_tasks']} overdue)."
        )
        lines.append("")
        for task in result["tasks"]:
            due = task["due_date"] or "no deadline set"
            overdue = " — **overdue**" if task["overdue"] else ""
            session = f" for {task['submission']['title']}" if task["submission"] else ""
            lines.append(f"- [{task['name']}]({task['url']}){session} — due {due}{overdue}")
    else:
        lines.append("**You are all caught up.** No open speaker tasks remain.")
    lines.extend(["", "## Your links", ""])
    lines.append(f"- [Open your checklist]({result['links']['checklist']})")
    lines.append(f"- [Update your speaker profile]({result['links']['profile']})")
    for session in result["sessions"]:
        lines.append(f"- [{session['title']}]({session['url']})")
    lines.extend(["", "## Trace of inference", ""])
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    lines.extend(["", f"Generated {result['generated_at']} (ISO-8601)."])
    return "\n".join(lines)


def speaker_next_actions_message(event_slug, subject_email, base_url=DEFAULT_BASE_URL):
    return render_speaker_next_actions(
        speaker_next_actions(event_slug, subject_email, base_url=base_url)
    )
