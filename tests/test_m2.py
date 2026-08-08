from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django_scopes import scope

from pretalx_speakerops.models import (
    OnboardingTask,
    ReminderReceipt,
    Resource,
    ResourceVersion,
    TransitionLog,
)
from pretalx_speakerops.onboarding.reminders import queue_reminders
from pretalx_speakerops.onboarding.services import record_evidence
from pretalx_speakerops.resources import sanitize_resource_html


@pytest.mark.django_db(transaction=True)
def test_roles_are_scoped_to_surfaces(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)

    client.force_login(users["chair"])
    assert client.get(f"/orga/{event.slug}/speaker-operations/").status_code == 200
    client.force_login(users["reviewer"])
    assert client.get(f"/orga/{event.slug}/speaker-operations/").status_code == 404
    assert client.get(f"/orga/{event.slug}/speaker-operations/review/").status_code == 200
    client.force_login(users["speaker"])
    assert client.get(f"/{event.slug}/speaker-operations/checklist/").status_code == 200
    assert client.get(f"/orga/{event.slug}/speaker-operations/review/").status_code == 404
    assert client.post(f"/orga/{event.slug}/speaker-operations/preview/").status_code == 404
    assert client.post(f"/orga/{event.slug}/speaker-operations/reminders/").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_dashboard_conflict_count_reconciles_to_rows(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        talks = list(event.wip_schedule.talks.filter(submission__isnull=False)[:2])
        talks[1].submission.speakers.add(users["speaker"])
        start = timezone.now()
        for talk in talks:
            talk.room = event.rooms.first()
            talk.start = start
            talk.end = start + timedelta(minutes=30)
            talk.save(update_fields=["room", "start", "end", "updated"])
    client.force_login(users["chair"])
    dashboard = client.get(f"/orga/{event.slug}/speaker-operations/")
    conflicts = client.get(f"/orga/{event.slug}/speaker-operations/conflicts/")
    assert dashboard.context["counts"]["conflicts"] == len(conflicts.context["rows"])
    assert dashboard.context["counts"]["conflicts"] > 0


@pytest.mark.django_db(transaction=True)
def test_dashboard_cards_reconcile_to_each_drilldown(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
    client.force_login(users["chair"])
    dashboard = client.get(f"/orga/{event.slug}/speaker-operations/")
    expected = {
        "tasks": "tasks",
        "undecided": "undecided",
        "reviewed": "review",
        "conflicts": "conflicts",
        "sync": "sync",
    }
    for card, kind in expected.items():
        rows = client.get(f"/orga/{event.slug}/speaker-operations/{kind}/").context["rows"]
        assert dashboard.context["counts"][card] == len(rows)


@pytest.mark.django_db(transaction=True)
def test_completion_uses_executor_and_evidence(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.get(
            submission=submission, speaker=users["speaker"], definition__slug="acknowledgement"
        )
        record_evidence(task, users["speaker"], "acknowledgement")
        from pretalx_speakerops.domain.commands import Command, execute
        from pretalx_speakerops.views import TASK_MACHINE

        execute(
            Command(
                event=event,
                aggregate_model=OnboardingTask,
                aggregate_id=task.pk,
                action="onboarding.complete",
                target_state=OnboardingTask.COMPLETE,
                state_machine=TASK_MACHINE,
                actor_role="speaker",
            ),
            users["speaker"],
            key=f"test-complete-{task.pk}",
            expected_version=task.version,
        )
        assert task.__class__.objects.get(pk=task.pk).status == OnboardingTask.COMPLETE
        assert TransitionLog.objects.filter(
            aggregate_id=task.pk, to_state=OnboardingTask.COMPLETE
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_organiser_can_reopen_and_waive_with_reason(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            submission=submission, speaker=users["speaker"]
        ).first()
        task.status = OnboardingTask.COMPLETE
        task.save(update_fields=["status", "updated"])
    client.force_login(users["chair"])
    assert (
        client.post(f"/orga/{event.slug}/speaker-operations/tasks/{task.pk}/reopen/").status_code
        == 302
    )
    task.refresh_from_db()
    assert task.status == OnboardingTask.REOPENED
    assert (
        client.post(
            f"/orga/{event.slug}/speaker-operations/tasks/{task.pk}/waive/",
            {"reason": "Not applicable"},
        ).status_code
        == 302
    )
    task.refresh_from_db()
    assert task.status == OnboardingTask.WAIVED
    assert task.waiver_reason == "Not applicable"


@pytest.mark.django_db(transaction=True)
def test_reminder_replay_is_deduplicated(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.filter(
            submission=submission, speaker=users["speaker"], status=OnboardingTask.PENDING
        ).first()
        before = len(mail.outbox)
        assert queue_reminders(event, [task], "due-1") == 1
        assert queue_reminders(event, [task], "due-1") == 0
        assert ReminderReceipt.objects.filter(task=task, reminder_key="due-1").count() == 1
        assert len(mail.outbox) == before


@pytest.mark.django_db(transaction=True)
def test_resources_sanitize_and_only_publish_visible(event, users, client):
    with scope(event=event):
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        with pytest.raises(ValueError):
            sanitize_resource_html('<iframe src="https://evil.example/embed"></iframe>')
        resource = Resource.objects.create(event=event, slug="speaker-guide", title="Speaker guide")
        ResourceVersion.objects.create(
            event=event, resource=resource, version=1, body_html="<p>Draft</p>"
        )
        ResourceVersion.objects.create(
            event=event,
            resource=resource,
            version=2,
            body_html="<p>Published</p>",
            published_at=timezone.now(),
        )
    client.force_login(users["speaker"])
    response = client.get(f"/{event.slug}/speaker-operations/resources/speaker-guide/")
    assert response.status_code == 200
    assert b"Published" in response.content
    assert b"Draft" not in response.content


@pytest.mark.django_db(transaction=True)
def test_upload_evaluator_rejects_unsafe_type(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.get(
            submission=submission, speaker=users["speaker"], definition__slug="headshot"
        )
        with pytest.raises(ValueError):
            record_evidence(
                task,
                users["speaker"],
                "upload",
                upload=SimpleUploadedFile(
                    "malware.exe", b"x", content_type="application/octet-stream"
                ),
            )
