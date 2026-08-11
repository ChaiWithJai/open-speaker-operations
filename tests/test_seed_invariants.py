from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django_scopes import scope
from pretalx.common.models import ActivityLog
from pretalx.event.models import Event, Team
from pretalx.person.models import SpeakerProfile, User
from pretalx.submission.models import Answer

from pretalx_speakerops.cfp import AIE_TRACKS
from pretalx_speakerops.demo_assets import DEMO_HEADSHOT_BY_EMAIL
from pretalx_speakerops.management.commands.speakerops_seed import (
    CFP_DEADLINE,
    CFP_OPENING,
    CONFLICT_FIXTURE_TITLES,
    CRM_DUPLICATE_EMAIL,
    CRM_FIXTURE_NOTES,
    CURATED_PROGRAM,
    CURATED_RELIABLE_TRACK_INDICES,
    CURATED_SPEAKER_ROLES,
    DEMO_END,
    DEMO_START,
    DEMO_WALKTHROUGH_AT,
    DEVFLOW_END,
    DEVFLOW_SLUG,
    DEVFLOW_START,
    DEVFLOW_TIMEZONE,
    EVALUATOR_SIGNUP_EMAIL,
)
from pretalx_speakerops.models import (
    CRMContact,
    CRMPipelineCard,
    ExternalIdentity,
    OnboardingTask,
    SubmissionPresenterRole,
    SyncAttempt,
    SyncItem,
    SyncPreview,
    SyncRun,
)
from pretalx_speakerops.program.policy import classify_warnings


def _released_program(event):
    schedule = event.schedules.get(version="m3-demo")
    return tuple(
        (
            slot.submission.title,
            slot.start.isoformat(),
            slot.end.isoformat(),
            str(slot.room.name),
            tuple(
                sorted(
                    (speaker.email, speaker.get_display_name())
                    for speaker in slot.submission.speakers.all()
                )
            ),
        )
        for slot in schedule.talks.filter(
            submission__isnull=False,
            is_visible=True,
        )
        .select_related("submission", "room")
        .prefetch_related("submission__speakers")
        .order_by("start", "room__position", "pk")
    )


def _baseline(event):
    released_submission_ids = (
        event.schedules.get(version="m3-demo")
        .talks.filter(
            submission__isnull=False,
            is_visible=True,
        )
        .values("submission_id")
    )
    return {
        "event": (
            event.date_from,
            event.date_to,
            event.timezone,
            event.cfp.opening,
            event.cfp.deadline,
        ),
        "released_program": _released_program(event),
        "tracks": tuple(
            str(name)
            for name in event.tracks.order_by("position", "pk").values_list("name", flat=True)
        ),
        "avatars": tuple(
            (speaker.name, bool(speaker.avatar))
            for speaker in User.objects.filter(submissions__in=released_submission_ids)
            .distinct()
            .order_by("name")
        ),
        "tasks": tuple(
            OnboardingTask.objects.filter(event=event)
            .values_list(
                "definition__slug",
                "status",
                "due_date",
                "waiver_reason",
                "speaker__email",
                "submission__title",
            )
            .order_by("definition__position", "pk")
        ),
        "presenter_roles": tuple(
            SubmissionPresenterRole.objects.filter(event=event)
            .values_list("submission__title", "speaker__email", "role")
            .order_by("submission__title", "speaker__email")
        ),
        "crm_fixtures": tuple(
            CRMContact.objects.filter(
                organiser=event.organiser,
                internal_notes__in=CRM_FIXTURE_NOTES,
            )
            .values_list("name", "email", "company", "job_title", "internal_notes")
            .order_by("internal_notes")
        ),
        "sync": {
            "previews": tuple(
                SyncPreview.objects.filter(event=event)
                .values_list("fingerprint", "status", "payload")
                .order_by("fingerprint")
            ),
            "runs": tuple(
                SyncRun.objects.filter(event=event)
                .values_list("status", "preview__fingerprint")
                .order_by("preview__fingerprint")
            ),
            "items": tuple(
                SyncItem.objects.filter(event=event)
                .values_list(
                    "local_type",
                    "local_id",
                    "action",
                    "status",
                    "attempts",
                    "external_id",
                    "request_fingerprint",
                    "error",
                    "payload",
                )
                .order_by("local_type", "local_id")
            ),
            "attempts": tuple(
                SyncAttempt.objects.filter(event=event)
                .values_list("item__local_type", "item__local_id", "number", "status", "error")
                .order_by("item__local_type", "item__local_id", "number")
            ),
            "identities": tuple(
                ExternalIdentity.objects.filter(event=event)
                .values_list(
                    "local_type",
                    "local_id",
                    "external_id",
                    "request_fingerprint",
                )
                .order_by("local_type", "local_id")
            ),
        },
    }


@pytest.mark.django_db(transaction=True)
def test_seed_is_deterministic_and_keeps_conflicts_out_of_released_program(monkeypatch, client):
    monkeypatch.setenv("SPEAKEROPS_DEMO_PASSWORD", "test-demo-password")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "seed-admin@example.org")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "test-password")
    monkeypatch.setenv("PRETALX_INIT_ORGANISER_NAME", "Seed Test Organiser")
    monkeypatch.setenv("PRETALX_INIT_ORGANISER_SLUG", "seed-test-organiser")
    call_command("init", interactive=False, verbosity=0)

    User.objects.create_user(
        email=EVALUATOR_SIGNUP_EMAIL,
        name="Priya Raman",
        password="throwaway-password",
    )
    call_command("speakerops_seed", verbosity=0)
    assert not User.objects.filter(email=EVALUATOR_SIGNUP_EMAIL).exists()
    event = Event.objects.get(slug="speakerops-demo")
    with scope(event=event):
        first = _baseline(event)

        assert first["event"] == (
            DEMO_START,
            DEMO_END,
            "America/New_York",
            CFP_OPENING,
            CFP_DEADLINE,
        )
        assert CFP_DEADLINE < DEMO_WALKTHROUGH_AT
        assert DEMO_WALKTHROUGH_AT.date() < DEMO_START
        assert event.get_feature_flag("use_tracks") is True
        assert first["tracks"] == (
            "Human-Centered Operations",
            "Reliable AI Systems",
            *AIE_TRACKS,
        )
        assert len(first["tracks"]) == len(set(first["tracks"]))
        released = event.schedules.get(version="m3-demo")
        released_tracks = list(
            released.talks.filter(is_visible=True, submission__isnull=False)
            .values_list("submission__track__name", flat=True)
            .order_by("start", "room__position", "pk")
        )
        assert released_tracks.count("Reliable AI Systems") == len(CURATED_RELIABLE_TRACK_INDICES)
        assert released_tracks.count("Human-Centered Operations") == len(CURATED_PROGRAM) - len(
            CURATED_RELIABLE_TRACK_INDICES
        )
        assert "Browse the released schedule" in str(event.landing_page_text)
        assert "/speakerops-demo/speaker-operations/embed/" in str(event.landing_page_text)
        primary_speaker = User.objects.get(email="speaker@example.org")
        second_speaker = User.objects.get(email="speaker2@example.org")
        assert primary_speaker.pk != second_speaker.pk
        assert primary_speaker.name == "Priya Raman"
        assert second_speaker.name == "Marcus Okafor"
        assert not SpeakerProfile.objects.filter(
            event=event, biography__contains="SBEK-PORTAL-BIO-01"
        ).exists()
        assert primary_speaker.check_password("test-demo-password")
        assert second_speaker.check_password("test-demo-password")
        devflow = Event.objects.get(slug=DEVFLOW_SLUG)
        assert str(devflow.name) == "DevFlow Conf 2027"
        assert devflow.organiser == event.organiser
        assert devflow.date_from == DEVFLOW_START
        assert devflow.date_to == DEVFLOW_END
        assert devflow.timezone == DEVFLOW_TIMEZONE
        chair = User.objects.get(email="chair@example.org")
        chair_team = chair.teams.get(
            organiser=event.organiser,
            name="SpeakerOps program chair",
        )
        assert chair_team.can_change_submissions is True
        assert chair_team.can_change_event_settings is True
        assert chair_team.can_change_teams is True
        assert chair.has_perm("event.update_event", event)
        assert chair.has_perm("event.update_event", devflow)
        assert set(chair_team.limit_events.values_list("slug", flat=True)) == {
            event.slug,
            DEVFLOW_SLUG,
        }

        client.force_login(chair)
        assert (
            client.get(reverse("orga:cfp.text.view", kwargs={"event": event.slug})).status_code
            == 200
        )
        reviewer_team = Team.objects.get(
            organiser=event.organiser,
            name="SpeakerOps reviewers",
        )
        assert reviewer_team.is_reviewer is False
        assert (
            client.get(
                reverse(
                    "orga:organiser.teams.update",
                    kwargs={"organiser": event.organiser.slug, "pk": reviewer_team.pk},
                )
            ).status_code
            == 200
        )
        client.logout()
        released = first["released_program"]
        assert len(released) == len(CURATED_PROGRAM) == 12
        assert {row[3] for row in released} == {"Main Stage", "Studio"}
        assert {row[0] for row in released} == {program[1] for program in CURATED_PROGRAM}
        assert all(row[1].startswith(DEMO_START.isoformat()) for row in released[:4])
        assert all(row[1].startswith(DEMO_END.isoformat()) for row in released[-4:])
        assert {row[1][:10] for row in released} == {
            DEMO_START.isoformat(),
            (DEMO_START + timedelta(days=1)).isoformat(),
            DEMO_END.isoformat(),
        }

        released_by_title = {row[0]: row for row in released}
        for speaker_name, title, _abstract in CURATED_PROGRAM:
            speakers = released_by_title[title][4]
            assert len(speakers) == 1
            assert speakers[0][1] == speaker_name
        demo_speaker_sessions = [
            row[0]
            for row in released
            if "speaker@example.org" in {email for email, _name in row[4]}
        ]
        assert demo_speaker_sessions == [CURATED_PROGRAM[2][1]]
        maya_speakers = released_by_title[CURATED_PROGRAM[0][1]][4]
        assert maya_speakers == (("curated-speaker-1@democon.test", "Maya Chen"),)
        accepted = event.submissions.get(title="Accepted: Operations That Scale")
        assert str(accepted.track.name) == "Platform & Infra"
        assert str(accepted.submission_type.name) == "Talk (30 min)"
        assert set(accepted.speakers.values_list("email", flat=True)) == {
            "speaker@example.org",
            "speaker2@example.org",
        }
        assert set(
            SubmissionPresenterRole.objects.filter(event=event, submission=accepted).values_list(
                "speaker__email", "role"
            )
        ) == {
            ("speaker@example.org", SubmissionPresenterRole.PRIMARY_AUTHOR),
            ("speaker2@example.org", SubmissionPresenterRole.CO_AUTHOR),
        }
        crm_pair = CRMContact.objects.filter(
            organiser=event.organiser,
            email=CRM_DUPLICATE_EMAIL,
            internal_notes__in=CRM_FIXTURE_NOTES,
            merged_into__isnull=True,
        )
        assert crm_pair.count() == 2
        assert crm_pair.values("email").distinct().count() == 1
        assert (
            CRMPipelineCard.objects.filter(organiser=event.organiser, contact__in=crm_pair).count()
            == 2
        )
        public_identity_answers = Answer.objects.filter(
            question__event=event,
            question__question__in=("Job title", "Company"),
            question__is_public=True,
            person__submissions__in=event.schedules.get(version="m3-demo").talks.values(
                "submission_id"
            ),
        ).distinct()
        assert public_identity_answers.count() == len(CURATED_PROGRAM) * 2
        assert set(public_identity_answers.values_list("answer", flat=True)) == {
            value for role in CURATED_SPEAKER_ROLES for value in role
        }
        avatar_by_name = dict(first["avatars"])
        assert len(avatar_by_name) == len(CURATED_PROGRAM)
        assert not any(avatar_by_name.values())
        assert len(DEMO_HEADSHOT_BY_EMAIL) == len(CURATED_PROGRAM) - 1
        assert "curated-speaker-12@democon.test" not in DEMO_HEADSHOT_BY_EMAIL

        wip_warnings = classify_warnings(event.wip_schedule)
        assert {warning["category"] for warning in wip_warnings} == {"room", "speaker"}
        wip_slots = list(
            event.wip_schedule.talks.filter(submission__isnull=False).values_list(
                "submission__title", flat=True
            )
        )
        assert len(wip_slots) == len(CURATED_PROGRAM) + len(CONFLICT_FIXTURE_TITLES)
        assert set(wip_slots) == {
            *(program[1] for program in CURATED_PROGRAM),
            *CONFLICT_FIXTURE_TITLES,
        }
        warning_titles = {
            warning["category"]: {
                warning["talk"].submission.title,
                warning["competitor"].submission.title,
            }
            for warning in wip_warnings
        }
        assert warning_titles["room"] == set(CONFLICT_FIXTURE_TITLES)
        assert warning_titles["speaker"] == {
            CURATED_PROGRAM[0][1],
            CONFLICT_FIXTURE_TITLES[1],
        }

    evaluator = User.objects.create_user(
        email=EVALUATOR_SIGNUP_EMAIL,
        name="Priya Raman",
        password="throwaway-password",
    )
    with scope(event=event):
        ActivityLog.objects.create(
            event=event,
            person=evaluator,
            content_object=event,
            action_type="speakerops.browser_evaluator_fixture",
        )

    call_command("speakerops_seed", verbosity=0)
    assert not User.objects.filter(email=EVALUATOR_SIGNUP_EMAIL).exists()
    event.refresh_from_db()
    with scope(event=event):
        assert _baseline(event) == first
