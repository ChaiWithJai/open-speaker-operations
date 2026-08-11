import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django_scopes import scope
from pretalx.person.models import User
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.integrations.buzz.review_reads import (
    review_progress,
    review_progress_message,
    reviewer_next_assignment,
    reviewer_next_assignment_message,
)
from pretalx_speakerops.models import (
    EvaluationAnswer,
    EvaluationCriterion,
    EvaluationRound,
    RoundReviewAssignment,
    RoundReviewer,
)


def _submission(event, title):
    prototype = event.submissions.order_by("pk").first()
    submission = event.submissions.create(
        title=title,
        abstract="Review-read fixture abstract.",
        description="Review-read fixture description.",
        submission_type=prototype.submission_type,
        track=prototype.track,
        content_locale=event.locale,
    )
    submission.state = SubmissionStates.SUBMITTED
    submission.save(update_fields=["state", "updated"])
    return submission


def _round(event, name, *, position, closes_delta):
    today = timezone.localdate()
    return EvaluationRound.objects.create(
        event=event,
        name=name,
        position=position,
        opens_at=today - timedelta(days=10),
        closes_at=today + timedelta(days=closes_delta),
    )


def _criterion(event, round_obj, name="Impact", *, position=0, required=True, field_type=None):
    field_type = field_type or EvaluationCriterion.NUMERIC
    return EvaluationCriterion.objects.create(
        event=event,
        round=round_obj,
        name=name,
        position=position,
        required=required,
        field_type=field_type,
        weight=Decimal("1.50"),
        minimum=Decimal("1") if field_type == EvaluationCriterion.NUMERIC else None,
        maximum=Decimal("5") if field_type == EvaluationCriterion.NUMERIC else None,
    )


def _reviewer(event, label):
    return User.objects.create_user(
        email=f"{label}@example.org",
        name=label.replace("-", " ").title(),
        password="test-password",
    )


@pytest.mark.django_db
def test_review_progress_empty_is_json_safe_and_read_only(event):
    with scope(event=event):
        EvaluationRound.objects.filter(event=event).delete()
        before = {
            "rounds": EvaluationRound.objects.filter(event=event).count(),
            "assignments": RoundReviewAssignment.objects.filter(event=event).count(),
            "answers": EvaluationAnswer.objects.filter(event=event).count(),
        }

    result = review_progress(event.slug, base_url="https://speakerops.example/")
    json.dumps(result)

    assert result["rounds"] == []
    assert result["incomplete_assignments"] == []
    assert result["rollup"] == {
        "rounds": 0,
        "assignments": 0,
        "complete": 0,
        "incomplete": 0,
        "recused": 0,
        "overdue": 0,
        "completion_percent": 0.0,
    }
    assert result["mutation_performed"] is False
    assert result["links"]["organizer_progress"].startswith(
        f"https://speakerops.example/go/abstract-console/{event.slug}/"
    )
    assert "no incomplete review assignments" in result["rendered_review_progress_message"]

    with scope(event=event):
        after = {
            "rounds": EvaluationRound.objects.filter(event=event).count(),
            "assignments": RoundReviewAssignment.objects.filter(event=event).count(),
            "answers": EvaluationAnswer.objects.filter(event=event).count(),
        }
    assert after == before


@pytest.mark.django_db
def test_review_progress_reports_round_pool_saved_state_overdue_and_order(event, users):
    second_reviewer = _reviewer(event, "second-reviewer")
    with scope(event=event):
        overdue_round = _round(event, "Initial", position=0, closes_delta=-2)
        future_round = _round(event, "Final", position=1, closes_delta=5)
        impact = _criterion(event, overdue_round)
        _criterion(
            event,
            overdue_round,
            "Comments",
            position=1,
            field_type=EvaluationCriterion.TEXT,
        )
        _criterion(event, future_round)
        RoundReviewer.objects.create(
            event=event,
            round=overdue_round,
            reviewer=users["reviewer"],
            assignment_limit=4,
        )
        RoundReviewer.objects.create(
            event=event,
            round=overdue_round,
            reviewer=second_reviewer,
            assignment_limit=2,
        )
        late_zulu = RoundReviewAssignment.objects.create(
            event=event,
            round=overdue_round,
            reviewer=users["reviewer"],
            submission=_submission(event, "Zulu stalled"),
        )
        late_alpha = RoundReviewAssignment.objects.create(
            event=event,
            round=overdue_round,
            reviewer=users["reviewer"],
            submission=_submission(event, "Alpha stalled"),
        )
        completed = RoundReviewAssignment.objects.create(
            event=event,
            round=overdue_round,
            reviewer=second_reviewer,
            submission=_submission(event, "Completed work"),
            status=RoundReviewAssignment.COMPLETE,
            submitted_at=timezone.now(),
        )
        later_assignment = RoundReviewAssignment.objects.create(
            event=event,
            round=future_round,
            reviewer=second_reviewer,
            submission=_submission(event, "Later work"),
        )
        RoundReviewAssignment.objects.create(
            event=event,
            round=future_round,
            reviewer=second_reviewer,
            submission=_submission(event, "Conflict work"),
            status=RoundReviewAssignment.RECUSED,
        )
        EvaluationAnswer.objects.create(
            event=event,
            assignment=late_alpha,
            criterion=impact,
            numeric_value=Decimal("4"),
        )

    result = review_progress(event.slug, base_url="https://speakerops.example")
    json.dumps(result)

    assert [row["name"] for row in result["rounds"]] == ["Initial", "Final"]
    assert result["rounds"][0]["pool"]["assignment_capacity"] == 6
    assert result["rounds"][0]["progress"] == {
        "assigned": 3,
        "complete": 1,
        "incomplete": 2,
        "recused": 0,
        "overdue": 2,
        "completion_percent": 33.3,
    }
    assert [row["assignment_pk"] for row in result["incomplete_assignments"]] == [
        late_alpha.pk,
        late_zulu.pk,
        later_assignment.pk,
    ]
    first = result["incomplete_assignments"][0]
    assert first["reviewer"] == {
        "name": users["reviewer"].get_display_name(),
        "email": users["reviewer"].email,
    }
    assert first["overdue"] is True
    assert first["rubric"]["required_answered"] == 1
    assert first["rubric"]["required_total"] == 2
    assert first["save_state"]["has_saved_answers"] is True
    assert first["url"] == (
        f"https://speakerops.example/go/round-review-assignment/{event.slug}~{late_alpha.pk}/"
    )
    assert result["rollup"]["complete"] == 1
    assert result["rollup"]["recused"] == 1
    assert result["rollup"]["incomplete"] == 3
    assert "abstract-console" in {row["resource"] for row in result["sources"]}
    assert "round-review-assignment" in {row["resource"] for row in result["sources"]}
    assert completed.submitted_at.isoformat() not in result["rendered_review_progress_message"]


@pytest.mark.django_db
def test_reviewer_next_assignment_empty_for_valid_member(event, users):
    with scope(event=event):
        round_obj = _round(event, "Empty round", position=0, closes_delta=4)
        RoundReviewer.objects.create(
            event=event,
            round=round_obj,
            reviewer=users["reviewer"],
        )

    result = reviewer_next_assignment(
        event.slug,
        users["reviewer"].email.upper(),
        base_url="https://speakerops.example/",
    )
    assert result["next_assignment"] is None
    assert result["assignments"] == []
    assert result["rollup"] == {"remaining": 0, "overdue": 0}
    assert "All caught up" in reviewer_next_assignment_message(event.slug, users["reviewer"].email)


@pytest.mark.django_db
def test_reviewer_next_assignment_is_strictly_self_scoped_and_ordered(event, users):
    other = _reviewer(event, "private-reviewer")
    with scope(event=event):
        earlier = _round(event, "Earlier deadline", position=2, closes_delta=-1)
        later = _round(event, "Later deadline", position=0, closes_delta=8)
        criterion = _criterion(event, earlier)
        _criterion(event, later)
        RoundReviewer.objects.create(event=event, round=earlier, reviewer=users["reviewer"])
        RoundReviewer.objects.create(event=event, round=earlier, reviewer=other)
        own_first = RoundReviewAssignment.objects.create(
            event=event,
            round=earlier,
            reviewer=users["reviewer"],
            submission=_submission(event, "Own urgent assignment"),
        )
        own_later = RoundReviewAssignment.objects.create(
            event=event,
            round=later,
            reviewer=users["reviewer"],
            submission=_submission(event, "Own later assignment"),
        )
        other_assignment = RoundReviewAssignment.objects.create(
            event=event,
            round=earlier,
            reviewer=other,
            submission=_submission(event, "TOP SECRET OTHER REVIEW"),
        )
        completed = RoundReviewAssignment.objects.create(
            event=event,
            round=earlier,
            reviewer=users["reviewer"],
            submission=_submission(event, "Already finished"),
            status=RoundReviewAssignment.COMPLETE,
        )
        EvaluationAnswer.objects.create(
            event=event,
            assignment=own_first,
            criterion=criterion,
            numeric_value=Decimal("3.50"),
        )
        before = {
            "assignments": list(
                RoundReviewAssignment.objects.filter(event=event)
                .order_by("pk")
                .values_list("pk", "status", "submitted_at", "updated")
            ),
            "answers": list(
                EvaluationAnswer.objects.filter(event=event)
                .order_by("pk")
                .values_list("pk", "numeric_value", "choice_value", "text_value", "updated")
            ),
        }

    result = reviewer_next_assignment(
        event.slug,
        f"  {users['reviewer'].email.upper()}  ",
        base_url="https://speakerops.example",
    )
    serialized = json.dumps(result)

    assert [row["assignment_pk"] for row in result["assignments"]] == [
        own_first.pk,
        own_later.pk,
    ]
    assert result["next_assignment"]["assignment_pk"] == own_first.pk
    assert result["next_assignment"]["overdue"] is True
    assert result["next_assignment"]["rubric"]["criteria"][0]["value"] == "3.50"
    assert result["next_assignment"]["save_state"] == {
        "has_saved_answers": True,
        "saved_criteria": 1,
        "required_criteria": 1,
        "required_answered": 1,
    }
    assert result["next_assignment"]["url"].endswith(
        f"/go/round-review-assignment/{event.slug}~{own_first.pk}/"
    )
    assert "organizer_progress" not in serialized
    assert other.email not in serialized
    assert other.get_display_name() not in serialized
    assert "TOP SECRET OTHER REVIEW" not in serialized
    assert str(other_assignment.pk) not in {
        str(row["assignment_pk"]) for row in result["assignments"]
    }
    assert str(completed.pk) not in {str(row["assignment_pk"]) for row in result["assignments"]}
    assert {row["resource"] for row in result["sources"]} == {
        "review-queue",
        "round-review-assignment",
    }
    assert result["mutation_performed"] is False
    assert "Own urgent assignment" in result["rendered_reviewer_next_assignment_message"]

    with scope(event=event):
        after = {
            "assignments": list(
                RoundReviewAssignment.objects.filter(event=event)
                .order_by("pk")
                .values_list("pk", "status", "submitted_at", "updated")
            ),
            "answers": list(
                EvaluationAnswer.objects.filter(event=event)
                .order_by("pk")
                .values_list("pk", "numeric_value", "choice_value", "text_value", "updated")
            ),
        }
    assert after == before


@pytest.mark.django_db
def test_reviewer_next_assignment_fails_closed_for_outsider(event):
    outsider = _reviewer(event, "unassigned-outsider")
    with pytest.raises(KeyError, match="reviewer is not assigned to this event") as error:
        reviewer_next_assignment(event.slug, outsider.email)
    assert outsider.email not in str(error.value)


@pytest.mark.django_db
def test_review_reads_reject_unknown_event_without_writes():
    with pytest.raises(KeyError, match="unknown event"):
        review_progress("missing-event")
    with pytest.raises(KeyError, match="unknown event"):
        reviewer_next_assignment("missing-event", "reviewer@example.org")


@pytest.mark.django_db
def test_message_variants_match_payload_rendering(event, users):
    with scope(event=event):
        round_obj = _round(event, "Message round", position=0, closes_delta=3)
        _criterion(event, round_obj)
        RoundReviewer.objects.create(event=event, round=round_obj, reviewer=users["reviewer"])
        RoundReviewAssignment.objects.create(
            event=event,
            round=round_obj,
            reviewer=users["reviewer"],
            submission=_submission(event, "Message assignment"),
        )

    progress = review_progress(event.slug)
    personal = reviewer_next_assignment(event.slug, users["reviewer"].email)
    assert review_progress_message(event.slug) == progress["rendered_review_progress_message"]
    assert (
        reviewer_next_assignment_message(event.slug, users["reviewer"].email)
        == personal["rendered_reviewer_next_assignment_message"]
    )
