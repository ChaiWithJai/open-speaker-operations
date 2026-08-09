from django.utils import timezone
from django_scopes import scope
from pretalx.common.models import ActivityLog
from pretalx.submission.models import Review, ReviewPhase, ReviewScore, ReviewScoreCategory

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
        configured = (("Program fit", 2), ("Speaker value", 1), ("Practicality", 1))
        configured_names = {name for name, _weight in configured}
        existing_categories = list(event.score_categories.prefetch_related("scores"))
        for existing in existing_categories:
            if str(existing.name) == "Score" and str(existing.name) not in configured_names:
                existing.delete()

        criteria = []
        categories_by_name = {
            str(category.name): category
            for category in existing_categories
            if str(category.name) in configured_names
        }
        score_labels = ("Not demonstrated", "Weak", "Adequate", "Strong", "Exceptional")
        for name, weight in configured:
            category = categories_by_name.get(name)
            if category is None:
                category = ReviewScoreCategory.objects.create(
                    event=event, name=name, weight=weight, required=True
                )
                existing_scores = {}
            else:
                changed = []
                for field, value in (("weight", weight), ("required", True), ("active", True)):
                    if getattr(category, field) != value:
                        setattr(category, field, value)
                        changed.append(field)
                if changed:
                    category.save(update_fields=[*changed, "updated"])
                existing_scores = {score.value: score for score in category.scores.all()}
            missing_scores = []
            for value, label in enumerate(score_labels, start=1):
                score = existing_scores.get(value)
                if score is None:
                    missing_scores.append(ReviewScore(category=category, value=value, label=label))
                elif str(score.label) != label:
                    score.label = label
                    score.save(update_fields=["label", "updated"])
            if missing_scores:
                ReviewScore.objects.bulk_create(missing_scores)
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
