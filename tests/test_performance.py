from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django_scopes import scope
from pretalx.submission.models import ReviewScore, ReviewScoreCategory, SubmissionStates

from pretalx_speakerops.program.reviews import configure_review_rounds
from pretalx_speakerops.views import DashboardView


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("path", "budget"),
    (
        ("/orga/{event}/speaker-operations/", 40),
        ("/orga/{event}/speaker-operations/tasks/", 40),
        ("/orga/{event}/speaker-operations/agenda/", 40),
    ),
)
def test_chair_views_stay_within_query_budget(
    event, users, client, django_assert_max_num_queries, path, budget
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        talks = list(event.wip_schedule.talks.filter(submission__isnull=False)[:2])
        start = timezone.now()
        for talk in talks:
            talk.room = event.rooms.first()
            talk.start = start
            talk.end = start + timedelta(minutes=30)
            talk.submission.speakers.add(users["speaker"])
            talk.save(update_fields=["room", "start", "end", "updated"])
    client.force_login(users["chair"])
    url = path.format(event=event.slug)
    client.get(url)
    if path.endswith("speaker-operations/"):
        cache.delete(f"speakerops:dashboard:{event.pk}")
    with django_assert_max_num_queries(budget):
        assert client.get(url).status_code == 200


@pytest.mark.django_db(transaction=True)
@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_dashboard_reuses_only_the_event_snapshot(
    event, users, client, django_assert_max_num_queries
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
    client.force_login(users["chair"])
    url = f"/orga/{event.slug}/speaker-operations/"
    cache.delete(f"speakerops:dashboard:{event.pk}")
    first = client.get(url)
    assert first.status_code == 200
    with (
        patch.object(DashboardView, "_snapshot", side_effect=AssertionError("cache miss")),
        django_assert_max_num_queries(30),
    ):
        second = client.get(url)
    assert second.status_code == 200
    assert second.context["counts"] == first.context["counts"]


@pytest.mark.django_db(transaction=True)
def test_reviewer_query_count_is_bounded_as_criteria_grow(
    event, users, client, django_assert_max_num_queries
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
        submission.assigned_reviewers.add(users["reviewer"])
        configure_review_rounds(event)
        for position in range(8):
            category = ReviewScoreCategory.objects.create(
                event=event,
                name=f"Scale criterion {position}",
                weight=1,
                required=True,
            )
            ReviewScore.objects.bulk_create(
                [
                    ReviewScore(category=category, value=value, label=f"Option {value}")
                    for value in range(1, 6)
                ]
            )
    client.force_login(users["reviewer"])
    url = f"/orga/{event.slug}/speaker-operations/reviewer/{submission.pk}/"
    client.get(url)
    with django_assert_max_num_queries(30):
        response = client.get(url)
    assert response.status_code == 200
    assert len(response.context["criteria"]) == 11
