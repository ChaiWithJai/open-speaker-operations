import json
from datetime import timedelta

import pytest
from django.utils import timezone
from django_scopes import scope
from pretalx.mail.models import QueuedMail

from pretalx_speakerops.integrations.buzz.buyer_workflows import BUYER_WORKFLOWS
from pretalx_speakerops.integrations.buzz.speaker_reads import (
    render_speaker_next_actions,
    render_speaker_nudges,
    speaker_next_actions,
    speaker_next_actions_message,
    speaker_nudges,
    speaker_nudges_message,
)
from pretalx_speakerops.models import (
    CommandReceipt,
    OnboardingTask,
    ReminderReceipt,
    TaskDefinition,
    TransitionLog,
)


def _definition(event, slug, name, position=0):
    return TaskDefinition.objects.create(
        event=event,
        slug=slug,
        name=name,
        position=position,
        instructions=f"Complete {name}.",
        completion_criteria=f"{name} is complete.",
    )


def _task(event, speaker, submission, definition, due_date, status=OnboardingTask.PENDING):
    return OnboardingTask.objects.create(
        event=event,
        speaker=speaker,
        submission=submission,
        definition=definition,
        due_date=due_date,
        status=status,
    )


def _mutation_snapshot(event):
    return {
        "tasks": list(
            OnboardingTask.objects.filter(event=event)
            .order_by("pk")
            .values_list("pk", "status", "version", "due_date", "evidence")
        ),
        "queued_mail": QueuedMail.objects.filter(event=event).count(),
        "reminder_receipts": ReminderReceipt.objects.filter(event=event).count(),
        "command_receipts": CommandReceipt.objects.filter(event=event).count(),
        "transitions": TransitionLog.objects.filter(event=event).count(),
    }


@pytest.mark.django_db(transaction=True)
def test_speaker_nudges_empty_is_json_safe_preview(event):
    with scope(event=event):
        before = _mutation_snapshot(event)
        result = speaker_nudges(event.slug, base_url="https://ops.example.test/")
        after = _mutation_snapshot(event)

    assert result["preview_only"] is True
    assert result["mutation_performed"] is False
    assert result["recipients"] == []
    assert result["overdue_tasks"] == []
    assert result["rollup"] == {"recipients": 0, "overdue_tasks": 0}
    assert result["links"]["filtered_overdue_tasks"] == (
        f"https://ops.example.test/go/overdue-tasks/{event.slug}~tasks/"
    )
    assert result["sources"][0]["exactness"] == "filtered-collection"
    assert before == after
    json.dumps(result)
    assert "No nudges due" in render_speaker_nudges(result)
    assert "No nudges due" in speaker_nudges_message(event.slug)


@pytest.mark.django_db(transaction=True)
def test_speaker_nudges_ranks_named_tasks_and_groups_recipients_without_mutation(event, users):
    today = timezone.localdate()
    with scope(event=event):
        submissions = list(event.submissions.order_by("pk")[:2])
        submissions[0].speakers.add(users["speaker"])
        submissions[1].speakers.add(users["reviewer"])
        oldest = _definition(event, "buzz-oldest", "Upload final deck", position=2)
        same_day_first = _definition(event, "buzz-bio", "Confirm biography", position=1)
        same_day_second = _definition(event, "buzz-rights", "Confirm media rights", position=3)
        future = _definition(event, "buzz-future", "Future request", position=4)
        completed = _definition(event, "buzz-done", "Already complete", position=5)
        oldest_task = _task(
            event,
            users["reviewer"],
            submissions[1],
            oldest,
            today - timedelta(days=8),
            status=OnboardingTask.REOPENED,
        )
        first_task = _task(
            event,
            users["speaker"],
            submissions[0],
            same_day_first,
            today - timedelta(days=3),
        )
        second_task = _task(
            event,
            users["speaker"],
            submissions[0],
            same_day_second,
            today - timedelta(days=3),
        )
        _task(event, users["speaker"], submissions[0], future, today + timedelta(days=1))
        _task(
            event,
            users["speaker"],
            submissions[0],
            completed,
            today - timedelta(days=20),
            status=OnboardingTask.COMPLETE,
        )
        before = _mutation_snapshot(event)
        result = speaker_nudges(event.slug, base_url="https://ops.example.test")
        after = _mutation_snapshot(event)

    assert [row["task_pk"] for row in result["overdue_tasks"]] == [
        oldest_task.pk,
        first_task.pk,
        second_task.pk,
    ]
    assert [row["speaker"]["email"] for row in result["recipients"]] == [
        users["reviewer"].email,
        users["speaker"].email,
    ]
    assert result["recipients"][1]["overdue_task_count"] == 2
    assert [row["name"] for row in result["recipients"][1]["tasks"]] == [
        "Confirm biography",
        "Confirm media rights",
    ]
    assert result["overdue_tasks"][0]["url"].endswith(f"/#task-{oldest_task.pk}")
    assert result["rollup"] == {"recipients": 2, "overdue_tasks": 3}
    assert before == after
    json.dumps(result)
    message = render_speaker_nudges(result)
    assert "Preview only" in message
    assert "Nothing has been sent" in message
    assert "Upload final deck" in message


@pytest.mark.django_db(transaction=True)
def test_speaker_next_actions_empty_is_scoped_and_json_safe(event, users):
    with scope(event=event):
        submission = event.submissions.first()
        submission.speakers.add(users["speaker"])
        before = _mutation_snapshot(event)
        result = speaker_next_actions(
            event.slug,
            f"  {users['speaker'].email.upper()}  ",
            base_url="https://ops.example.test/",
        )
        after = _mutation_snapshot(event)

    assert result["subject"] == {
        "name": users["speaker"].get_display_name(),
        "email": users["speaker"].email,
    }
    assert result["tasks"] == []
    assert result["rollup"]["open_tasks"] == 0
    assert result["sessions"] == [
        {
            "pk": submission.pk,
            "code": submission.code,
            "title": submission.title,
            "url": (
                "https://ops.example.test/go/own-submission-presenters/"
                f"{event.slug}~{submission.code}/"
            ),
        }
    ]
    assert result["links"] == {
        "checklist": f"https://ops.example.test/go/speaker-checklist/{event.slug}/",
        "profile": f"https://ops.example.test/go/speaker-profile/{event.slug}/",
    }
    assert before == after
    json.dumps(result)
    assert "You are all caught up" in render_speaker_next_actions(result)


@pytest.mark.django_db(transaction=True)
def test_speaker_next_actions_has_zero_other_speaker_leakage(event, users):
    today = timezone.localdate()
    with scope(event=event):
        submissions = list(event.submissions.order_by("pk")[:2])
        target_submission, outsider_submission = submissions
        target_submission.speakers.add(users["speaker"])
        outsider_submission.speakers.add(users["reviewer"])
        target_definition = _definition(event, "buzz-target", "Target-only headshot", position=2)
        outsider_definition = _definition(
            event, "buzz-outsider", "SECRET outsider deck", position=1
        )
        no_deadline_definition = _definition(
            event, "buzz-target-later", "Target no-deadline task", position=3
        )
        target_task = _task(
            event,
            users["speaker"],
            target_submission,
            target_definition,
            today - timedelta(days=2),
        )
        later_task = _task(
            event,
            users["speaker"],
            target_submission,
            no_deadline_definition,
            None,
        )
        _task(
            event,
            users["reviewer"],
            outsider_submission,
            outsider_definition,
            today - timedelta(days=30),
        )
        before = _mutation_snapshot(event)
        result = speaker_next_actions(
            event.slug,
            users["speaker"].email,
            base_url="https://ops.example.test",
        )
        after = _mutation_snapshot(event)

    assert [row["task_pk"] for row in result["tasks"]] == [target_task.pk, later_task.pk]
    assert [row["pk"] for row in result["sessions"]] == [target_submission.pk]
    assert result["tasks"][0]["overdue"] is True
    assert result["tasks"][0]["url"].endswith(f"/#task-{target_task.pk}-title")
    assert result["sources"][0]["audience"] == "speaker"
    assert result["sources"][1]["resource"] == "speaker-profile"
    assert result["sources"][2]["exactness"] == "exact-record"
    workflow = next(item for item in BUYER_WORKFLOWS if item.read_tool == "speaker_next_actions")
    assert {row["resource"] for row in result["sources"]} == set(workflow.link_resources)
    serialized = json.dumps(result)
    assert users["reviewer"].email not in serialized
    assert users["reviewer"].get_display_name() not in serialized
    assert "SECRET outsider deck" not in serialized
    assert outsider_submission.title not in serialized
    assert before == after
    message = speaker_next_actions_message(event.slug, users["speaker"].email)
    assert "Target-only headshot" in message
    assert "SECRET outsider deck" not in message


@pytest.mark.django_db(transaction=True)
def test_speaker_next_actions_rejects_non_event_subject(event, users):
    with pytest.raises(KeyError, match="speaker is not attached to event"):
        speaker_next_actions(event.slug, users["speaker"].email)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("read", [speaker_nudges, speaker_next_actions])
def test_speaker_reads_reject_unknown_event(read, users):
    args = ("missing-event",)
    if read is speaker_next_actions:
        args += (users["speaker"].email,)
    with pytest.raises(KeyError, match="unknown event"):
        read(*args)
