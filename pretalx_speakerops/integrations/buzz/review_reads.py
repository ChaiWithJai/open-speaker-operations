"""Read-only Buzz answers for review leads and individual reviewers.

The lead read reports event-wide round progress from the review system of
record.  The reviewer read is deliberately narrower: ``subject_email`` is an
identity boundary, not a search term, and only that reviewer's open round
assignments are loaded or serialized.  Neither read writes, sends reminders,
or exposes a command.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from django_scopes import scope
from pretalx.event.models import Event
from pretalx.person.models import User

from pretalx_speakerops.canonical_links import RESOURCES
from pretalx_speakerops.models import (
    EvaluationCriterion,
    EvaluationRound,
    RoundReviewAssignment,
    RoundReviewer,
)

DEFAULT_BASE_URL = "http://localhost:8000"


def _event(event_slug):
    event = Event.objects.filter(slug=event_slug).first()
    if event is None:
        raise KeyError(f"unknown event: {event_slug}")
    return event


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


def _answer_value(answer):
    if answer.numeric_value is not None:
        return str(answer.numeric_value)
    if answer.choice_value:
        return answer.choice_value
    return answer.text_value


def _answer_is_filled(answer):
    if answer.criterion.field_type == EvaluationCriterion.NUMERIC:
        return answer.numeric_value is not None
    if answer.criterion.field_type == EvaluationCriterion.DROPDOWN:
        return bool(answer.choice_value.strip())
    return bool(answer.text_value.strip())


def _rubric(assignment):
    answers = {answer.criterion_id: answer for answer in assignment.answers.all()}
    criteria = []
    required_total = 0
    required_answered = 0
    saved_total = 0
    for criterion in assignment.round.criteria.all():
        answer = answers.get(criterion.pk)
        answered = answer is not None and _answer_is_filled(answer)
        required_total += int(criterion.required)
        required_answered += int(criterion.required and answered)
        saved_total += int(answered)
        criteria.append(
            {
                "criterion_pk": criterion.pk,
                "name": criterion.name,
                "field_type": criterion.field_type,
                "required": criterion.required,
                "weight": str(criterion.weight),
                "minimum": str(criterion.minimum) if criterion.minimum is not None else None,
                "maximum": str(criterion.maximum) if criterion.maximum is not None else None,
                "options": list(criterion.options),
                "saved": answered,
                "value": _answer_value(answer) if answered else None,
            }
        )
    return {
        "criteria": criteria,
        "required_total": required_total,
        "required_answered": required_answered,
        "saved_total": saved_total,
        "complete": required_answered == required_total,
    }


def _assignment_row(assignment, base_url, *, include_reviewer):
    rubric = _rubric(assignment)
    row = {
        "assignment_pk": assignment.pk,
        "round": {
            "pk": assignment.round_id,
            "name": assignment.round.name,
            "position": assignment.round.position,
            "closes_at": assignment.round.closes_at.isoformat(),
            "blinded": assignment.round.blinded,
        },
        "submission": {
            "pk": assignment.submission_id,
            "code": assignment.submission.code,
            "title": assignment.submission.title,
        },
        "status": assignment.status,
        "submitted_at": (assignment.submitted_at.isoformat() if assignment.submitted_at else None),
        "overdue": (
            assignment.status == RoundReviewAssignment.ASSIGNED
            and assignment.round.closes_at < timezone.localdate()
        ),
        "rubric": rubric,
        "save_state": {
            "has_saved_answers": bool(rubric["saved_total"]),
            "saved_criteria": rubric["saved_total"],
            "required_criteria": rubric["required_total"],
            "required_answered": rubric["required_answered"],
        },
        "url": _go(
            base_url,
            "round-review-assignment",
            f"{assignment.event.slug}~{assignment.pk}",
        ),
    }
    if include_reviewer:
        row["reviewer"] = {
            "name": assignment.reviewer.get_display_name(),
            "email": assignment.reviewer.email,
        }
    return row


def _assignment_queryset(event):
    return (
        RoundReviewAssignment.objects.filter(event=event)
        .select_related("round", "reviewer", "submission")
        .prefetch_related("round__criteria", "answers__criterion")
    )


def review_progress(event_slug, base_url=DEFAULT_BASE_URL):
    """Answer the reviewer-lead question, "Where is review stalled?"""
    event = _event(event_slug)
    today = timezone.localdate()
    organizer_url = _go(base_url, "abstract-console", event.slug, "progress")
    reviewer_queue_url = _go(base_url, "review-queue", event.slug)

    with scope(event=event):
        rounds = list(EvaluationRound.objects.filter(event=event).order_by("position", "pk"))
        memberships = list(
            RoundReviewer.objects.filter(event=event)
            .select_related("round", "reviewer")
            .order_by("round__position", "round_id", "reviewer__name", "reviewer__email", "pk")
        )
        assignments = list(
            _assignment_queryset(event).order_by(
                "round__position",
                "round_id",
                "reviewer__name",
                "reviewer__email",
                "submission__title",
                "pk",
            )
        )

    assignments_by_round = {}
    for assignment in assignments:
        assignments_by_round.setdefault(assignment.round_id, []).append(assignment)
    memberships_by_round = {}
    for membership in memberships:
        memberships_by_round.setdefault(membership.round_id, []).append(membership)

    round_rows = []
    incomplete = []
    total_complete = 0
    total_recused = 0
    for round_obj in rounds:
        round_assignments = assignments_by_round.get(round_obj.pk, [])
        reviewer_rows = []
        reviewer_ids = {assignment.reviewer_id for assignment in round_assignments} | {
            membership.reviewer_id for membership in memberships_by_round.get(round_obj.pk, [])
        }
        membership_map = {
            membership.reviewer_id: membership
            for membership in memberships_by_round.get(round_obj.pk, [])
        }
        assignment_map = {}
        for assignment in round_assignments:
            assignment_map.setdefault(assignment.reviewer_id, []).append(assignment)

        for reviewer_id in sorted(
            reviewer_ids,
            key=lambda pk: (
                (
                    membership_map.get(pk).reviewer.get_display_name()
                    if membership_map.get(pk)
                    else assignment_map[pk][0].reviewer.get_display_name()
                ).casefold(),
                pk,
            ),
        ):
            reviewer = (
                membership_map[reviewer_id].reviewer
                if reviewer_id in membership_map
                else assignment_map[reviewer_id][0].reviewer
            )
            owned = assignment_map.get(reviewer_id, [])
            assigned = sum(item.status == RoundReviewAssignment.ASSIGNED for item in owned)
            complete = sum(item.status == RoundReviewAssignment.COMPLETE for item in owned)
            recused = sum(item.status == RoundReviewAssignment.RECUSED for item in owned)
            overdue = sum(
                item.status == RoundReviewAssignment.ASSIGNED and round_obj.closes_at < today
                for item in owned
            )
            membership = membership_map.get(reviewer_id)
            reviewer_rows.append(
                {
                    "reviewer": {
                        "name": reviewer.get_display_name(),
                        "email": reviewer.email,
                    },
                    "assignment_limit": membership.assignment_limit if membership else None,
                    "assigned": len(owned),
                    "complete": complete,
                    "incomplete": assigned,
                    "recused": recused,
                    "overdue": overdue,
                    "last_reminded_at": (
                        membership.last_reminded_at.isoformat()
                        if membership and membership.last_reminded_at
                        else None
                    ),
                }
            )

        round_complete = sum(
            item.status == RoundReviewAssignment.COMPLETE for item in round_assignments
        )
        round_recused = sum(
            item.status == RoundReviewAssignment.RECUSED for item in round_assignments
        )
        round_incomplete = [
            item for item in round_assignments if item.status == RoundReviewAssignment.ASSIGNED
        ]
        total_complete += round_complete
        total_recused += round_recused
        incomplete.extend(
            _assignment_row(item, base_url, include_reviewer=True) for item in round_incomplete
        )
        denominator = len(round_assignments) - round_recused
        round_rows.append(
            {
                "round_pk": round_obj.pk,
                "name": round_obj.name,
                "position": round_obj.position,
                "opens_at": round_obj.opens_at.isoformat(),
                "closes_at": round_obj.closes_at.isoformat(),
                "active": round_obj.active,
                "blinded": round_obj.blinded,
                "pool": {
                    "reviewer_count": len(reviewer_rows),
                    "assignment_capacity": sum(
                        row["assignment_limit"] or 0 for row in reviewer_rows
                    ),
                    "reviewers": reviewer_rows,
                },
                "progress": {
                    "assigned": len(round_assignments),
                    "complete": round_complete,
                    "incomplete": len(round_incomplete),
                    "recused": round_recused,
                    "overdue": sum(item.round.closes_at < today for item in round_incomplete),
                    "completion_percent": (
                        round(100 * round_complete / denominator, 1) if denominator else 0.0
                    ),
                },
            }
        )

    incomplete.sort(
        key=lambda row: (
            not row["overdue"],
            row["round"]["closes_at"],
            row["round"]["position"],
            row["reviewer"]["name"].casefold(),
            row["submission"]["title"].casefold(),
            row["assignment_pk"],
        )
    )
    total = len(assignments)
    total_actionable = total - total_recused
    result = {
        "event": event.slug,
        "question": "Where is review stalled?",
        "as_of": today.isoformat(),
        "rounds": round_rows,
        "incomplete_assignments": incomplete,
        "rollup": {
            "rounds": len(round_rows),
            "assignments": total,
            "complete": total_complete,
            "incomplete": len(incomplete),
            "recused": total_recused,
            "overdue": sum(row["overdue"] for row in incomplete),
            "completion_percent": (
                round(100 * total_complete / total_actionable, 1) if total_actionable else 0.0
            ),
        },
        "links": {
            "organizer_progress": organizer_url,
            "reviewer_queue": reviewer_queue_url,
            "incomplete_assignments": [
                {"assignment_pk": row["assignment_pk"], "url": row["url"]} for row in incomplete
            ],
        },
        "sources": [
            _canonical_source(
                "abstract-console",
                organizer_url,
                "Organizer-only round, pool, assignment, and progress evidence.",
            ),
            _canonical_source(
                "review-queue",
                reviewer_queue_url,
                "Reviewer-safe self-scoped collection; no reviewer is impersonated.",
            ),
            *(
                _canonical_source(
                    "round-review-assignment",
                    row["url"],
                    f"Exact assignment {row['assignment_pk']}; authorization is rechecked on open.",
                )
                for row in incomplete
            ),
        ],
        "trace": [
            f"Resolved event `{event.slug}` from the system of record.",
            (
                "Read event-scoped evaluation rounds, reviewer memberships, assignments, "
                "criteria, and saved answers."
            ),
            (
                "Grouped assignments by round and named reviewer; recused work was "
                "excluded from completion denominators."
            ),
            (
                f"Classified {len(incomplete)} open assignments and "
                f"{sum(row['overdue'] for row in incomplete)} overdue assignments as of "
                f"{today.isoformat()}."
            ),
            (
                "Ranked overdue work first, then by round deadline, round position, "
                "reviewer, submission, and assignment id."
            ),
            (
                "Built organizer and reviewer-safe canonical links; each go/ target "
                "rechecks authorization."
            ),
            "Performed no assignment, reminder, review, answer, receipt, or other mutation.",
        ],
        "mutation_performed": False,
        "generated_at": timezone.now().isoformat(),
    }
    result["rendered_review_progress_message"] = render_review_progress(result)
    return result


def render_review_progress(result):
    lines = [f"# Review progress — {result['event']}", ""]
    rollup = result["rollup"]
    if rollup["incomplete"]:
        lines.append(
            f"**Stalled:** {rollup['incomplete']} incomplete assignment(s), "
            f"including {rollup['overdue']} overdue."
        )
    else:
        lines.append("**On track:** no incomplete review assignments.")
    lines.extend(["", "## Round progress", ""])
    if not result["rounds"]:
        lines.append("- No review rounds are configured.")
    for row in result["rounds"]:
        progress = row["progress"]
        lines.append(
            f"- **{row['name']}** — {progress['complete']}/{progress['assigned']} complete; "
            f"{progress['overdue']} overdue; {row['pool']['reviewer_count']} reviewer(s)."
        )
    lines.extend(["", "## Incomplete assignments", ""])
    if not result["incomplete_assignments"]:
        lines.append("- None.")
    for row in result["incomplete_assignments"]:
        overdue = "overdue" if row["overdue"] else "open"
        lines.append(
            f"- {row['reviewer']['name']} — [{row['submission']['title']}]({row['url']}) "
            f"— {row['round']['name']} — {overdue}; "
            f"{row['rubric']['required_answered']}/"
            f"{row['rubric']['required_total']} required saved."
        )
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            f"- [Organizer progress]({result['links']['organizer_progress']})",
            f"- [Reviewer self-scoped queue]({result['links']['reviewer_queue']})",
            "",
            "## Trace of inference",
            "",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    return "\n".join(lines)


def review_progress_message(event_slug, base_url=DEFAULT_BASE_URL):
    return review_progress(event_slug, base_url)["rendered_review_progress_message"]


def reviewer_next_assignment(event_slug, subject_email, base_url=DEFAULT_BASE_URL):
    """Answer "What is next?" for exactly one assigned event reviewer."""
    event = _event(event_slug)
    normalized_email = subject_email.strip().casefold()
    queue_url = _go(base_url, "review-queue", event.slug)

    with scope(event=event):
        reviewer = (
            User.objects.filter(email__iexact=normalized_email)
            .filter(
                Q(speakerops_round_memberships__event=event)
                | Q(speakerops_round_assignments__event=event)
            )
            .distinct()
            .first()
        )
        if reviewer is None:
            raise KeyError("reviewer is not assigned to this event")
        assignments = list(
            _assignment_queryset(event)
            .filter(reviewer=reviewer, status=RoundReviewAssignment.ASSIGNED)
            .order_by("round__closes_at", "round__position", "submission__title", "pk")
        )

    rows = [_assignment_row(item, base_url, include_reviewer=False) for item in assignments]
    next_row = rows[0] if rows else None
    result = {
        "event": event.slug,
        "question": "What is next?",
        "subject": {
            "name": reviewer.get_display_name(),
            "email": reviewer.email,
        },
        "next_assignment": next_row,
        "assignments": rows,
        "rollup": {
            "remaining": len(rows),
            "overdue": sum(row["overdue"] for row in rows),
        },
        "links": {
            "review_queue": queue_url,
            "assignments": [
                {"assignment_pk": row["assignment_pk"], "url": row["url"]} for row in rows
            ],
        },
        "sources": [
            _canonical_source(
                "review-queue",
                queue_url,
                "Self-scoped to the bound reviewer principal.",
            ),
            *(
                _canonical_source(
                    "round-review-assignment",
                    row["url"],
                    f"Exact assignment {row['assignment_pk']} owned by the bound reviewer.",
                )
                for row in rows
            ),
        ],
        "trace": [
            f"Resolved event `{event.slug}` from the system of record.",
            "Matched one event reviewer by exact case-insensitive email identity.",
            "Selected only open round assignments whose reviewer is that exact user.",
            "Loaded only each owned assignment's round, submission, rubric, and persisted answers.",
            (
                "Ranked owned work by round deadline, round position, submission title, "
                "and assignment id."
            ),
            (
                "Serialized no organizer-only progress, other reviewer identity, other "
                "reviewer assignment, presenter, or speaker data."
            ),
            (
                "Performed no review save, submit, recusal, assignment, reminder, "
                "receipt, or other mutation."
            ),
        ],
        "mutation_performed": False,
        "generated_at": timezone.now().isoformat(),
    }
    result["rendered_reviewer_next_assignment_message"] = render_reviewer_next_assignment(result)
    return result


def render_reviewer_next_assignment(result):
    lines = [f"# Your next review — {result['event']}", ""]
    row = result["next_assignment"]
    if row is None:
        lines.append("**All caught up:** you have no open round assignments.")
    else:
        lines.append(
            f"**Next:** [{row['submission']['title']}]({row['url']}) in "
            f"{row['round']['name']} (due {row['round']['closes_at']})."
        )
        lines.extend(
            [
                "",
                f"Saved rubric state: {row['rubric']['required_answered']}/"
                f"{row['rubric']['required_total']} required criteria.",
            ]
        )
    lines.extend(
        [
            "",
            f"Remaining assignments: {result['rollup']['remaining']}",
            f"Overdue assignments: {result['rollup']['overdue']}",
            "",
            f"[Open your self-scoped review queue]({result['links']['review_queue']})",
            "",
            "## Trace of inference",
            "",
        ]
    )
    lines.extend(f"{index}. {step}" for index, step in enumerate(result["trace"], 1))
    return "\n".join(lines)


def reviewer_next_assignment_message(event_slug, subject_email, base_url=DEFAULT_BASE_URL):
    return reviewer_next_assignment(event_slug, subject_email, base_url)[
        "rendered_reviewer_next_assignment_message"
    ]
