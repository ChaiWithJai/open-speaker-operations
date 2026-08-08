import pytest
from django_scopes import scope
from pretalx.schedule.signals import schedule_release
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.models import OnboardingTask, PreviewRun, TaskDefinition


@pytest.mark.django_db(transaction=True)
def test_acceptance_creates_one_task_per_speaker(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.accept(person=users["chair"], force=True)
        expected = (
            submission.speakers.count()
            * TaskDefinition.objects.filter(event=event, active=True).count()
        )
        assert OnboardingTask.objects.filter(event=event, submission=submission).count() == expected
        submission.accept(person=users["chair"], force=True)
        assert OnboardingTask.objects.filter(event=event, submission=submission).count() == expected


@pytest.mark.django_db(transaction=True)
def test_golden_path_crosses_plugin_boundaries(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["state", "updated"])
        submission.accept(person=users["chair"], force=True)
        task = OnboardingTask.objects.get(
            submission=submission, speaker=users["speaker"], definition__slug="acknowledgement"
        )

        client.force_login(users["speaker"])
        response = client.get(f"/{event.slug}/speaker-operations/checklist/")
        assert response.status_code == 200
        response = client.post(f"/{event.slug}/speaker-operations/checklist/{task.pk}/complete/")
        assert response.status_code == 302
        task.refresh_from_db()
        assert task.status == OnboardingTask.COMPLETE

        client.force_login(users["chair"])
        schedule_release.send(sender=event, schedule=event.wip_schedule, user=users["chair"])
        assert PreviewRun.objects.filter(event=event, status="schedule-released").exists()
        assert client.get(f"/{event.slug}/schedule/").status_code == 200
        response = client.post(f"/orga/{event.slug}/speaker-operations/preview/")
        assert response.status_code == 200
        assert PreviewRun.objects.filter(event=event).exists()
