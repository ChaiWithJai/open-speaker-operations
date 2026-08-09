from decimal import Decimal

import pytest
from django.urls import reverse
from django_scopes import scope
from pretalx.person.models import User
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.models import (
    EvaluationAnswer,
    EvaluationCriterion,
    EvaluationRound,
    OutboxEvent,
    RoundReviewAssignment,
    RoundReviewer,
)


def _submitted(event, count=3):
    submissions = list(event.submissions.order_by("pk")[:count])
    while len(submissions) < count:
        prototype = submissions[0]
        submissions.append(
            event.submissions.create(
                title=f"Evaluator proposal {len(submissions) + 1}",
                abstract="An exact reviewer-scoping fixture.",
                description="The unassigned proposal must remain invisible.",
                submission_type=prototype.submission_type,
                track=prototype.track,
                content_locale=event.locale,
            )
        )
    for submission in submissions:
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
    return submissions


@pytest.mark.django_db(transaction=True)
def test_rounds_persist_distinct_dates_scorecards_and_pools(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
    client.force_login(users["chair"])
    url = reverse("plugins:speakerops:speakerops_abstract_management", kwargs={"event": event.slug})
    assert (
        client.post(
            url,
            {
                "action": "create_round",
                "name": "Initial Review",
                "opens_at": "2026-08-01",
                "closes_at": "2026-10-15",
                "scorecard_preset": "initial",
                "blinded": "yes",
            },
        ).status_code
        == 302
    )
    assert (
        client.post(
            url,
            {
                "action": "create_round",
                "name": "Final Review",
                "opens_at": "2026-10-16",
                "closes_at": "2026-11-30",
                "scorecard_preset": "final",
            },
        ).status_code
        == 302
    )

    with scope(event=event):
        initial, final = list(EvaluationRound.objects.filter(event=event))
        assert initial.blinded is True
        assert [criterion.name for criterion in initial.criteria.all()] == [
            "Originality",
            "Relevance",
            "Recommendation",
            "Comments",
        ]
        assert list(initial.criteria.values_list("field_type", flat=True)) == [
            "numeric",
            "numeric",
            "dropdown",
            "text",
        ]
        assert initial.criteria.get(name="Originality").weight == 2
        assert [criterion.name for criterion in final.criteria.all()] == [
            "Final Score",
            "Comments",
        ]
        RoundReviewer.objects.create(
            event=event, round=initial, reviewer=users["reviewer"], assignment_limit=5
        )
        assert initial.reviewer_memberships.count() == 1
        assert final.reviewer_memberships.count() == 0

    page = client.get(url)
    assert page.status_code == 200
    body = page.content.decode()
    assert "Initial Review" in body and "Final Review" in body
    assert "Originality 1–5 ×2" in body
    assert "Separate pool currently empty" in body


@pytest.mark.django_db(transaction=True)
def test_exact_assignments_cap_progress_reminder_and_reviewer_isolation(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submissions = _submitted(event)
        users["speaker"].name = "Secret Priya Raman"
        users["speaker"].save(update_fields=["name"])
        submissions[0].speakers.add(users["speaker"])
        round_obj = EvaluationRound.objects.create(
            event=event,
            name="Initial Review",
            opens_at="2026-08-01",
            closes_at="2026-10-15",
            blinded=True,
        )
        EvaluationCriterion.objects.create(
            event=event,
            round=round_obj,
            name="Originality",
            field_type=EvaluationCriterion.NUMERIC,
            weight=2,
            minimum=1,
            maximum=5,
        )
        RoundReviewAssignment.objects.create(
            event=event,
            round=round_obj,
            reviewer=users["reviewer"],
            submission=submissions[2],
        )
    client.force_login(users["chair"])
    manage_url = reverse(
        "plugins:speakerops:speakerops_abstract_management", kwargs={"event": event.slug}
    )
    response = client.post(
        manage_url,
        {
            "action": "assign_exact",
            "round_id": round_obj.pk,
            "reviewer_id": users["reviewer"].pk,
            "assignment_limit": 2,
            "submissions": [submissions[0].pk, submissions[1].pk],
        },
    )
    assert response.status_code == 302
    with scope(event=event):
        assignments = list(
            RoundReviewAssignment.objects.filter(round=round_obj).order_by("submission_id")
        )
        membership = RoundReviewer.objects.get(round=round_obj, reviewer=users["reviewer"])
        assert membership.assignment_limit == 2
        assert {item.submission_id for item in assignments} == {
            submissions[0].pk,
            submissions[1].pk,
        }
        assert submissions[2].pk not in {item.submission_id for item in assignments}

    client.force_login(users["reviewer"])
    queue_url = reverse(
        "plugins:speakerops:speakerops_round_review_queue", kwargs={"event": event.slug}
    )
    page = client.get(queue_url)
    assert page.status_code == 200
    body = page.content.decode()
    assert submissions[0].title in body and submissions[1].title in body
    assert submissions[2].title not in body
    assert "Secret Priya Raman" not in body
    assert "Author identity hidden" in body

    with scope(event=event):
        other_reviewer = User.objects.create_user(
            email="unassigned-reviewer@example.org",
            name="Unassigned reviewer",
            password="test-password",
        )
        users["reviewer"].teams.filter(is_reviewer=True).first().members.add(other_reviewer)
    client.force_login(other_reviewer)
    assert client.get(queue_url).status_code == 200
    assert submissions[0].title.encode() not in client.get(queue_url).content
    assert (
        client.get(
            reverse(
                "plugins:speakerops:speakerops_round_review",
                kwargs={"event": event.slug, "assignment": assignments[0].pk},
            )
        ).status_code
        == 404
    )

    client.force_login(users["chair"])
    progress = client.get(manage_url)
    assert "0 of 2" in progress.content.decode()
    reminder = client.post(manage_url, {"action": "send_reminders", "memberships": [membership.pk]})
    assert reminder.status_code == 302
    with scope(event=event):
        assert OutboxEvent.objects.filter(kind="review.reminder").count() == 1
        membership.refresh_from_db()
        assert membership.last_reminded_at is not None


@pytest.mark.django_db(transaction=True)
def test_mixed_scorecard_roundtrip_weighted_aggregate_sort_and_csv(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submissions = _submitted(event, 2)
        users["speaker"].name = "Organizer-visible Priya"
        users["speaker"].save(update_fields=["name"])
        submissions[0].speakers.add(users["speaker"])
        round_obj = EvaluationRound.objects.create(
            event=event,
            name="Initial Review",
            opens_at="2026-08-01",
            closes_at="2026-10-15",
            blinded=True,
        )
        criteria = [
            EvaluationCriterion.objects.create(
                event=event,
                round=round_obj,
                position=0,
                name="Originality",
                field_type="numeric",
                weight=2,
                minimum=1,
                maximum=5,
            ),
            EvaluationCriterion.objects.create(
                event=event,
                round=round_obj,
                position=1,
                name="Relevance",
                field_type="numeric",
                weight=1,
                minimum=1,
                maximum=5,
            ),
            EvaluationCriterion.objects.create(
                event=event,
                round=round_obj,
                position=2,
                name="Recommendation",
                field_type="dropdown",
                weight=0,
                options=["Accept", "Maybe", "Reject"],
            ),
            EvaluationCriterion.objects.create(
                event=event,
                round=round_obj,
                position=3,
                name="Comments",
                field_type="text",
                weight=0,
            ),
        ]
        assignments = [
            RoundReviewAssignment.objects.create(
                event=event,
                round=round_obj,
                reviewer=users["reviewer"],
                submission=submission,
            )
            for submission in submissions
        ]
        RoundReviewer.objects.create(
            event=event, round=round_obj, reviewer=users["reviewer"], assignment_limit=2
        )
    client.force_login(users["reviewer"])
    first_url = reverse(
        "plugins:speakerops:speakerops_round_review",
        kwargs={"event": event.slug, "assignment": assignments[0].pk},
    )
    response = client.post(
        first_url,
        {
            f"criterion_{criteria[0].pk}": "4",
            f"criterion_{criteria[1].pk}": "2",
            f"criterion_{criteria[2].pk}": "Accept",
            f"criterion_{criteria[3].pk}": "Strong fit with concrete evidence.",
        },
    )
    assert response.status_code == 302
    second_url = reverse(
        "plugins:speakerops:speakerops_round_review",
        kwargs={"event": event.slug, "assignment": assignments[1].pk},
    )
    assert (
        client.post(
            second_url,
            {
                f"criterion_{criteria[0].pk}": "5",
                f"criterion_{criteria[1].pk}": "5",
                f"criterion_{criteria[2].pk}": "Accept",
                f"criterion_{criteria[3].pk}": "Excellent fit.",
            },
        ).status_code
        == 302
    )
    stored = client.get(first_url)
    assert b"Strong fit with concrete evidence." in stored.content
    assert b"Organizer-visible Priya" not in stored.content
    with scope(event=event):
        assert (
            EvaluationAnswer.objects.get(
                assignment=assignments[0], criterion=criteria[2]
            ).choice_value
            == "Accept"
        )
        assignments[0].refresh_from_db()
        assert assignments[0].status == RoundReviewAssignment.COMPLETE

    client.force_login(users["chair"])
    manage_url = reverse(
        "plugins:speakerops:speakerops_abstract_management", kwargs={"event": event.slug}
    )
    descending = client.get(f"{manage_url}?sort=desc")
    assert descending.status_code == 200
    rows = descending.context["round_results"][0][1]
    assert rows[0]["aggregate"] == Decimal("5")
    assert rows[1]["aggregate"].quantize(Decimal("0.01")) == Decimal("3.33")
    assert b"Organizer-visible Priya" in descending.content
    assert b"Presenter" in descending.content
    assert [row["submission"].pk for row in rows] == [
        submissions[1].pk,
        submissions[0].pk,
    ]
    ascending = client.get(f"{manage_url}?sort=asc")
    assert ascending.context["round_results"][0][1][0]["aggregate"].quantize(
        Decimal("0.01")
    ) == Decimal("3.33")
    exported = client.get(f"{manage_url}?export=csv")
    assert exported.status_code == 200
    assert exported["Content-Type"] == "text/csv"
    assert b"Initial Review" in exported.content and b"3.333" in exported.content


@pytest.mark.django_db(transaction=True)
def test_recusal_is_scoped_and_auditable(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        submission = _submitted(event, 1)[0]
        round_obj = EvaluationRound.objects.create(
            event=event,
            name="Conflict review",
            opens_at="2026-08-01",
            closes_at="2026-10-15",
        )
        assignment = RoundReviewAssignment.objects.create(
            event=event,
            round=round_obj,
            reviewer=users["reviewer"],
            submission=submission,
        )
    client.force_login(users["reviewer"])
    url = reverse(
        "plugins:speakerops:speakerops_round_review",
        kwargs={"event": event.slug, "assignment": assignment.pk},
    )
    page = client.get(url)
    assert b"Declare conflict and recuse" in page.content
    response = client.post(url, {"action": "recuse", "recusal_reason": "Prior collaboration"})
    assert response.status_code == 302
    with scope(event=event):
        assignment.refresh_from_db()
        assert assignment.status == RoundReviewAssignment.RECUSED
        assert assignment.recusal_reason == "Prior collaboration"
    queue = client.get(
        reverse(
            "plugins:speakerops:speakerops_round_review_queue",
            kwargs={"event": event.slug},
        )
    )
    assert submission.title.encode() not in queue.content
