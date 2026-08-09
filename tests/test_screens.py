from datetime import timedelta

import pytest
from django.utils import timezone
from django_scopes import scope
from pretalx.person.models import SpeakerProfile
from pretalx.submission.models import Review, SubmissionStates

from pretalx_speakerops.cfp import configure_demo_cfp
from pretalx_speakerops.models import (
    OnboardingTask,
    ReviewRecommendation,
    SyncItem,
    SyncPreview,
    SyncRun,
)
from pretalx_speakerops.program.reviews import configure_review_rounds


@pytest.mark.django_db(transaction=True)
def test_dashboard_has_all_six_prd_counts_and_exact_drilldowns(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        upload_task = OnboardingTask.objects.filter(
            event=event, definition__completion_evaluator="upload"
        ).first()
        preview = SyncPreview.objects.create(event=event, fingerprint="x", payload={"items": []})
        run = SyncRun.objects.create(event=event, preview=preview)
        SyncItem.objects.create(
            event=event,
            run=run,
            action="create",
            local_type="speaker",
            local_id=999,
            payload={},
            request_fingerprint="x",
            status=SyncItem.FAILED,
            error="fixture failure",
        )
    assert upload_task
    client.force_login(users["chair"])
    dashboard = client.get(f"/orga/{event.slug}/speaker-operations/")
    assert dashboard.status_code == 200
    assert {
        "tasks",
        "missing_assets",
        "reviewed",
        "undecided",
        "conflicts",
        "sync",
    }.issubset(dashboard.context["counts"])
    expected = {
        "tasks": "tasks",
        "missing_assets": "missing-assets",
        "reviewed": "review",
        "undecided": "undecided",
        "conflicts": "conflicts",
        "sync": "sync",
    }
    for count, kind in expected.items():
        drilldown = client.get(f"/orga/{event.slug}/speaker-operations/{kind}/")
        assert dashboard.context["counts"][count] == len(drilldown.context["rows"])


@pytest.mark.django_db(transaction=True)
def test_reviewer_screen_saves_scores_comments_and_recommendation(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
        submission.assigned_reviewers.add(users["reviewer"])
        _, criteria = configure_review_rounds(event)
        payload = {
            f"score_{criterion.pk}": criterion.scores.order_by("value").last().pk
            for criterion in criteria
        }
        payload.update(comments="Useful and concrete.", recommendation="strong_accept")
    client.force_login(users["reviewer"])
    url = f"/orga/{event.slug}/speaker-operations/reviewer/{submission.pk}/"
    assert client.get(url).status_code == 200
    response = client.post(url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == 200
    with scope(event=event):
        review = Review.objects.get(submission=submission, user=users["reviewer"])
        assert review.scores.count() == 3
        assert review.text == "Useful and concrete."
        assert (
            ReviewRecommendation.objects.get(
                submission=submission, reviewer=users["reviewer"]
            ).recommendation
            == ReviewRecommendation.STRONG_ACCEPT
        )


@pytest.mark.django_db(transaction=True)
def test_agenda_names_competing_sessions_and_blocks_release(event, users, client):
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
    url = f"/orga/{event.slug}/speaker-operations/agenda/"
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert talks[0].submission.title in body
    assert talks[1].submission.title in body
    assert response.context["blocking"]
    assert "bound method" not in body
    assert users["speaker"].get_display_name() in body
    blocking = response.context["blocking"]
    assert len({item["message"] for item in blocking}) == len(blocking)
    assert sum(item["category"] == "room" for item in blocking) == 1
    assert sum(users["speaker"].get_display_name() in item["message"] for item in blocking) == 1
    assert client.post(url, {"confirm_release": "yes", "name": "blocked"}).status_code == 302


@pytest.mark.django_db(transaction=True)
def test_biography_task_is_completed_from_checklist(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.get(
            event=event,
            speaker=users["speaker"],
            definition__completion_evaluator="profile_field",
        )
    client.force_login(users["speaker"])
    response = client.post(
        f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/",
        {"response": "I build humane systems for speakers and program teams."},
    )
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.status == OnboardingTask.COMPLETE
    with scope(event=event):
        assert (
            "humane systems"
            in SpeakerProfile.objects.get(event=event, user=users["speaker"]).biography
        )


@pytest.mark.django_db(transaction=True)
def test_sync_console_and_public_gallery_render_required_states(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        preview = SyncPreview.objects.create(
            event=event,
            fingerprint="preview",
            payload={"items": [{"action": "create"}]},
        )
        run = SyncRun.objects.create(event=event, preview=preview, status=SyncRun.PARTIAL)
        SyncItem.objects.create(
            event=event,
            run=run,
            action="create",
            local_type="speaker",
            local_id=123,
            payload={},
            request_fingerprint="item",
            status=SyncItem.FAILED,
            error="network failed",
        )
        released = bool(event.current_schedule)
    client.force_login(users["chair"])
    console = client.get(f"/orga/{event.slug}/speaker-operations/sync-console/")
    assert console.status_code == 200
    assert b"network failed" in console.content
    client.logout()
    gallery = client.get(f"/{event.slug}/speaker-operations/gallery/")
    assert gallery.status_code == (200 if released else 404)


@pytest.mark.django_db(transaction=True)
def test_cfp_format_and_interest_options_are_distinct(event):
    with scope(event=event):
        questions = configure_demo_cfp(event)
        values = {
            str(question.question): {
                str(answer) for answer in question.options.values_list("answer", flat=True)
            }
            for question in questions
        }
    assert values["Session format"] == {"Main stage", "Workshop", "Roundtable"}
    assert "AI engineering" in values["Audience interests"]
    assert values["Session format"].isdisjoint(values["Audience interests"])
