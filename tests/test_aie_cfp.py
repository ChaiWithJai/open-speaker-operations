import pytest
from django_scopes import scope

from pretalx_speakerops.cfp import AIE_TRACKS, SESSION_FORMATS, configure_demo_cfp
from pretalx_speakerops.models import AcceptanceWave


@pytest.mark.django_db
def test_aie_cfp_configures_exact_formats_topics_policy_and_waves(event):
    with scope(event=event):
        questions = configure_demo_cfp(event)
        by_name = {str(question.question): question for question in questions}
        submission_types = {
            str(submission_type.name): submission_type.default_duration
            for submission_type in event.submission_types.filter(
                name__in=[name for name, _duration in SESSION_FORMATS]
            )
        }
        waves = list(
            AcceptanceWave.objects.filter(event=event)
            .order_by("position")
            .values_list("name", "decision_at")
        )
        track_names = {str(track.name) for track in event.tracks.all()}
        active_question_names = {
            str(question.question) for question in event.questions.filter(active=True)
        }
        audience_options = list(
            by_name["Audience level"].options.order_by("position").values_list("answer", flat=True)
        )
        prerequisite_types = {
            str(name)
            for name in by_name["Workshop prerequisites"].submission_types.values_list(
                "name", flat=True
            )
        }

    assert submission_types == dict(SESSION_FORMATS)
    assert str(event.cfp.default_type.name) == "Talk (30 min)"
    assert set(AIE_TRACKS) <= track_names
    assert set(by_name) >= {
        "Review category",
        "Audience level",
        "Key takeaway",
        "Workshop prerequisites",
        "Topics",
        "Commercial relationship",
        "Proposed session context",
    }
    assert "Session format" not in by_name
    assert "Session format" not in active_question_names
    assert {name for name, question in by_name.items() if question.required} == {
        "Key takeaway",
        "Review category",
        "Workshop prerequisites",
        "Topics",
        "Session abstract",
    }
    assert audience_options == ["Beginner", "Intermediate", "Advanced"]
    # The native form must retain the field across live format changes; the
    # browser rule and server validation still limit it to workshop formats.
    assert prerequisite_types == set(dict(SESSION_FORMATS))
    assert [name for name, _when in waves] == ["Wave 1", "Wave 2", "Wave 3"]
    assert [(when.month, when.day) for _name, when in waves] == [(8, 15), (9, 1), (9, 15)]
