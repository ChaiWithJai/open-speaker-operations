from datetime import timedelta

import pytest
from django.utils import timezone
from django_scopes import scope
from pretalx.person.models import SpeakerProfile
from pretalx.submission.models import Review, SubmissionStates

from pretalx_speakerops.cfp import SESSION_FORMATS, configure_demo_cfp
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
    body = dashboard.content.decode()
    assert "Review sync plan" in body
    assert 'action="/orga/' + event.slug + '/speaker-operations/preview/"' not in body
    assert "Only speakers with an overdue, unresolved task" in body
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
def test_dashboard_lifecycle_reconciles_every_stage_and_names_exception_owners(
    event, users, client
):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
        submission.assigned_reviewers.add(users["reviewer"])
        Review.objects.update_or_create(
            submission=submission,
            user=users["reviewer"],
            defaults={"text": "Reviewed but deliberately left for a chair decision."},
        )
    client.force_login(users["chair"])
    dashboard = client.get(f"/orga/{event.slug}/speaker-operations/")
    assert dashboard.status_code == 200
    stages = dashboard.context["lifecycle"]
    assert [stage["key"] for stage in stages] == [
        "submitted",
        "reviewed",
        "decided",
        "onboarded",
        "scheduled",
        "published",
        "synchronized",
    ]
    assert all(stage["denominator"] == stages[0]["count"] for stage in stages)
    for stage in stages:
        drilldown = client.get(stage["url"])
        assert drilldown.status_code == 200
        assert stage["count"] == len(drilldown.context["rows"])
        assert stage["explanation"]
    body = dashboard.content.decode()
    assert "without a recorded decision" in body
    assert "Owner: Program chair" in body
    assert "What changed and recovered" in body


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
def test_reviewer_rejects_stale_revision_and_exposes_keyboard_continuity(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submissions = list(event.submissions.all()[:2])
        if len(submissions) == 1:
            submissions.append(
                event.submissions.create(
                    title="Second assigned proposal",
                    abstract="Enough detail for the reviewer continuity test.",
                    description="A second proposal makes Save and next meaningful.",
                    submission_type=submissions[0].submission_type,
                    track=submissions[0].track,
                )
            )
        for submission in submissions:
            submission.state = SubmissionStates.SUBMITTED
            submission.save(update_fields=["state", "updated"])
            submission.assigned_reviewers.add(users["reviewer"])
        _, criteria = configure_review_rounds(event)
        payload = {
            f"score_{criterion.pk}": criterion.scores.order_by("value").last().pk
            for criterion in criteria
        }
    client.force_login(users["reviewer"])
    url = f"/orga/{event.slug}/speaker-operations/reviewer/{submissions[0].pk}/"
    screen = client.get(url)
    assert len(screen.context["queue"]) == 2
    assert screen.context["next_submission"] is not None
    assert b"Save" in screen.content and b"next" in screen.content
    assert b"Alt+S" in screen.content
    assert b"Retry save" in screen.content

    newest = {
        **payload,
        "comments": "Newest authoritative review",
        "recommendation": "strong_accept",
        "save_session": "browser-session",
        "client_revision": "2",
    }
    assert client.post(url, newest, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code == 200
    stale = {
        **payload,
        "comments": "Stale response must not win",
        "recommendation": "reject",
        "save_session": "browser-session",
        "client_revision": "1",
    }
    response = client.post(url, stale, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == 200
    assert response.json()["stale"] is True
    with scope(event=event):
        review = Review.objects.get(submission=submissions[0], user=users["reviewer"])
        recommendation = ReviewRecommendation.objects.get(
            submission=submissions[0], reviewer=users["reviewer"]
        )
    assert review.text == "Newest authoritative review"
    assert recommendation.recommendation == ReviewRecommendation.STRONG_ACCEPT
    assert recommendation.client_revision == 2

    cross_tab = {
        **payload,
        "comments": "A different tab must not overwrite the saved review",
        "recommendation": "reject",
        "save_session": "other-browser-session",
        "client_revision": "1",
        "save_version": "0",
    }
    response = client.post(url, cross_tab, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == 409
    assert response.json()["conflict"] is True
    with scope(event=event):
        review.refresh_from_db()
        recommendation.refresh_from_db()
    assert review.text == "Newest authoritative review"
    assert recommendation.recommendation == ReviewRecommendation.STRONG_ACCEPT


@pytest.mark.django_db(transaction=True)
def test_agenda_names_competing_sessions_and_blocks_release(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        all_talks = list(event.wip_schedule.talks.filter(submission__isnull=False))
        talks = all_talks[:2]
        start = timezone.now()
        for talk in talks:
            talk.room = event.rooms.first()
            talk.start = start
            talk.end = start + timedelta(minutes=30)
            talk.submission.speakers.add(users["speaker"])
            talk.save(update_fields=["room", "start", "end", "updated"])
        for offset, talk in enumerate(all_talks[2:], start=1):
            talk.start = start + timedelta(days=offset)
            talk.end = talk.start + timedelta(minutes=30)
            talk.save(update_fields=["start", "end", "updated"])
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
        formats = {
            str(submission_type.name)
            for submission_type in event.submission_types.filter(
                name__in=[name for name, _duration in SESSION_FORMATS]
            )
        }
    assert formats == {name for name, _duration in SESSION_FORMATS}
    assert "AI engineering" in values["Audience interests"]
    assert formats.isdisjoint(values["Audience interests"])
