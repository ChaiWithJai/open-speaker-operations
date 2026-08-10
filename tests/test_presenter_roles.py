from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django_scopes import scope
from pretalx.person.models import User
from pretalx.submission.models import SubmissionStates

from pretalx_speakerops.models import (
    EvaluationAnswer,
    EvaluationCriterion,
    EvaluationRound,
    RoundReviewAssignment,
    SubmissionPresenterRole,
)


@pytest.mark.django_db(transaction=True)
def test_closed_cfp_makes_presenter_roles_read_only_and_rejects_post(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        submission = event.submissions.first()
        submission.speakers.set([users["speaker"]])
        past = timezone.now() - timedelta(days=1)
        event.cfp.deadline = past
        event.cfp.save(update_fields=["deadline", "updated"])
        event.submission_types.update(deadline=past)
    url = reverse(
        "plugins:speakerops:speakerops_submission_presenters",
        kwargs={"event": event.slug, "code": submission.code},
    )
    client.force_login(users["speaker"])

    rendered = client.get(url)
    denied = client.post(url, {f"role_{users['speaker'].pk}": "primary_author"})

    assert rendered.status_code == 200
    assert b"Proposal locked" in rendered.content
    assert b"Save presenter roles" not in rendered.content
    assert b"Invite another presenter" not in rendered.content
    assert denied.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_presenter_roles_survive_reload_and_render_for_speaker_and_organizer(event, users, client):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        open_deadline = timezone.now() + timedelta(days=7)
        event.cfp.deadline = open_deadline
        event.cfp.save(update_fields=["deadline", "updated"])
        event.submission_types.update(deadline=open_deadline)
        priya = users["speaker"]
        priya.name = "Priya Raman"
        priya.save(update_fields=["name"])
        marcus = User.objects.create_user(
            email="marcus.speaker@example.org",
            name="Marcus Okafor",
            password="test-password",
        )
        outsider = User.objects.create_user(
            email="other.speaker@example.org",
            name="Other Speaker",
            password="test-password",
        )
        submission = event.submissions.first()
        submission.title = "Taming 40-Minute CI: Incremental Builds at Monorepo Scale"
        submission.state = SubmissionStates.SUBMITTED
        submission.save(update_fields=["title", "state", "updated"])
        submission.speakers.clear()
        submission.speakers.add(priya, marcus)
        other_submission = event.submissions.exclude(pk=submission.pk).first()
        other_submission.speakers.add(outsider)

        with pytest.raises(ValidationError, match="attached submission presenter"):
            SubmissionPresenterRole.objects.create(
                event=event,
                submission=submission,
                speaker=outsider,
                role=SubmissionPresenterRole.CO_AUTHOR,
            )
        with pytest.raises(ValidationError, match="submission from this event"):
            SubmissionPresenterRole.objects.create(
                event_id=event.pk + 1_000_000,
                submission=submission,
                speaker=priya,
                role=SubmissionPresenterRole.CO_AUTHOR,
            )

    presenter_url = reverse(
        "plugins:speakerops:speakerops_submission_presenters",
        kwargs={"event": event.slug, "code": submission.code},
    )
    client.force_login(priya)
    initial = client.get(presenter_url)
    saved = client.post(
        presenter_url,
        {
            f"role_{priya.pk}": SubmissionPresenterRole.PRIMARY_AUTHOR,
            f"role_{marcus.pk}": SubmissionPresenterRole.CO_AUTHOR,
        },
        follow=True,
    )
    reloaded = client.get(presenter_url)

    assert initial.status_code == 200
    assert b"Invite another presenter" in initial.content
    assert saved.status_code == 200
    assert b"Presenter role labels saved." in saved.content
    assert reloaded.status_code == 200
    for expected in (b"Priya Raman", b"Primary author", b"Marcus Okafor", b"Co-author"):
        assert expected in reloaded.content

    dashboard = client.get(event.urls.user_submissions)
    assert dashboard.status_code == 200
    assert presenter_url.encode() in dashboard.content

    client.force_login(outsider)
    assert client.get(presenter_url).status_code == 404
    assert (
        client.post(
            presenter_url,
            {
                f"role_{priya.pk}": SubmissionPresenterRole.CO_AUTHOR,
                f"role_{marcus.pk}": SubmissionPresenterRole.PRIMARY_AUTHOR,
            },
        ).status_code
        == 404
    )

    with scope(event=event):
        roles = {
            role.speaker.get_display_name(): role.get_role_display()
            for role in SubmissionPresenterRole.objects.filter(
                event=event, submission=submission
            ).select_related("speaker")
        }
        assert roles == {"Priya Raman": "Primary author", "Marcus Okafor": "Co-author"}
        round_obj = EvaluationRound.objects.create(
            event=event,
            name="Role label results proof",
            opens_at="2026-08-01",
            closes_at="2026-10-15",
        )
        criterion = EvaluationCriterion.objects.create(
            event=event,
            round=round_obj,
            name="Originality",
            field_type=EvaluationCriterion.NUMERIC,
            weight=1,
            minimum=1,
            maximum=5,
        )
        assignment = RoundReviewAssignment.objects.create(
            event=event,
            round=round_obj,
            reviewer=users["reviewer"],
            submission=submission,
            status=RoundReviewAssignment.COMPLETE,
        )
        EvaluationAnswer.objects.create(
            event=event,
            assignment=assignment,
            criterion=criterion,
            numeric_value=Decimal("4"),
        )

    client.force_login(users["chair"])
    organizer_review = client.get(
        reverse(
            "plugins:speakerops:speakerops_review",
            kwargs={"event": event.slug, "pk": submission.pk},
        )
    )
    organizer_results = client.get(
        reverse(
            "plugins:speakerops:speakerops_abstract_management",
            kwargs={"event": event.slug},
        )
    )

    assert organizer_review.status_code == 200
    assert organizer_results.status_code == 200
    for response in (organizer_review, organizer_results):
        for expected in (b"Priya Raman", b"Primary author", b"Marcus Okafor", b"Co-author"):
            assert expected in response.content
