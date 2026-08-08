from django.utils import timezone
from django_scopes import scope
from pretalx.common.models import ActivityLog
from pretalx.submission.models import Review, ReviewPhase, ReviewScoreCategory

from ..models import TransitionLog


def configure_review_rounds(event, second_round=True):
    """Configure pretalx review phases and weighted criteria, idempotently."""
    with scope(event=event):
        phases = []
        for position, name in enumerate(("Round 1", "Round 2") if second_round else ("Round 1",)):
            phase, _ = ReviewPhase.objects.get_or_create(
                event=event,
                name=name,
                defaults={
                    "position": position,
                    "proposal_visibility": "assigned",
                    "can_review": True,
                    "can_change_submission_state": False,
                },
            )
            if phase.position != position:
                phase.position = position
                phase.save(update_fields=["position"])
            phases.append(phase)
        criteria = []
        for _position, (name, weight) in enumerate(
            (("Program fit", 2), ("Speaker value", 1), ("Practicality", 1))
        ):
            category = next(
                (item for item in event.score_categories.all() if str(item.name) == name),
                None,
            )
            if category is None:
                category = ReviewScoreCategory.objects.create(
                    event=event, name=name, weight=weight, required=True
                )
            criteria.append(category)
        return phases, criteria


def decision_history(submission):
    """Combine pretalx activity with plugin transitions into an audit timeline."""
    content_type = submission._meta.concrete_model
    logs = ActivityLog.objects.filter(
        content_type__model=content_type._meta.model_name,
        object_id=submission.pk,
    ).select_related("person")
    reviews = Review.objects.filter(submission=submission).select_related("user")
    transitions = TransitionLog.objects.filter(
        event=submission.event,
        aggregate_type="submission",
        aggregate_id=submission.pk,
    ).select_related("actor")
    result = [
        {
            "kind": "pretalx",
            "action": log.action_type,
            "actor": log.person,
            "timestamp": log.timestamp,
            "data": log.data or {},
        }
        for log in logs
    ]
    result.extend(
        {
            "kind": "review",
            "action": "review.submitted",
            "actor": review.user,
            "timestamp": review.updated,
            "data": {"score": review.score, "text": review.text},
        }
        for review in reviews
    )
    result.extend(
        {
            "kind": "speakerops",
            "action": transition.metadata.get("action", "transition"),
            "actor": transition.actor,
            "timestamp": transition.timestamp,
            "data": transition.metadata,
        }
        for transition in transitions
    )
    return sorted(result, key=lambda item: item["timestamp"] or timezone.now())
