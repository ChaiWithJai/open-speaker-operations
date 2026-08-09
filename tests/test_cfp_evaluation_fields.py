import pytest
from django import forms
from django.core.exceptions import ValidationError
from django_scopes import scope
from pretalx.submission.models import Answer, QuestionVariant, Submission, SubmissionStates

from pretalx_speakerops.cfp import (
    SpeakerOpsQuestionsForm,
    configure_demo_cfp,
    validate_persisted_conditional_answers,
)


def _required_answers(form):
    data = {}
    for name, field in form.fields.items():
        if not field.required:
            continue
        if isinstance(field, forms.ModelMultipleChoiceField):
            data[name] = [field.queryset.first().pk]
        elif isinstance(field, forms.ModelChoiceField):
            data[name] = field.queryset.first().pk
        elif isinstance(field, forms.BooleanField):
            data[name] = "on"
        else:
            data[name] = "A concrete takeaway or prerequisite for evaluation."
    return data


def _draft(event, users, submission_type):
    submission = Submission.objects.create(
        event=event,
        title="Evaluation CFP field proof",
        abstract="A complete abstract for the evaluation CFP field proof.",
        description="A complete description for the evaluation CFP field proof.",
        submission_type=submission_type,
        state=SubmissionStates.DRAFT,
        content_locale=event.locale,
    )
    submission.speakers.add(users["speaker"])
    return submission


@pytest.mark.django_db(transaction=True)
def test_cfp_has_exact_evaluation_fields_and_workshop_scope(event):
    with scope(event=event):
        questions = {str(question.question): question for question in configure_demo_cfp(event)}
        audience = questions["Audience level"]
        takeaway = questions["Key takeaway"]
        prerequisites = questions["Workshop prerequisites"]

        assert audience.variant == QuestionVariant.CHOICES
        assert audience.required
        assert list(audience.options.order_by("position").values_list("answer", flat=True)) == [
            "Beginner",
            "Intermediate",
            "Advanced",
        ]
        assert takeaway.variant == QuestionVariant.STRING
        assert takeaway.required
        assert prerequisites.variant == QuestionVariant.STRING
        assert prerequisites.required
        assert list(prerequisites.submission_types.values_list("name", flat=True)) == ["Workshop"]


@pytest.mark.django_db(transaction=True)
def test_workshop_prerequisites_render_only_for_workshops_and_are_required(event, users):
    with scope(event=event):
        stage_talk = event.submission_types.get(name="Stage Talk")
        workshop = event.submission_types.get(name="Workshop")
        stage_form = SpeakerOpsQuestionsForm(event=event, submission_type=stage_talk)
        workshop_form = SpeakerOpsQuestionsForm(event=event, submission_type=workshop)
        audience = event.questions.get(question="Audience level")
        prerequisites = event.questions.get(question="Workshop prerequisites")
        audience_name = f"question_{audience.pk}"
        field_name = f"question_{prerequisites.pk}"

        assert isinstance(stage_form.fields[audience_name].widget, forms.Select)
        assert not isinstance(stage_form.fields[audience_name].widget, forms.RadioSelect)
        assert field_name not in stage_form.fields
        assert field_name in workshop_form.fields
        assert workshop_form.fields[field_name].required

        missing_data = _required_answers(workshop_form)
        missing_data.pop(field_name)
        submission = _draft(event, users, workshop)
        missing_form = SpeakerOpsQuestionsForm(
            data=missing_data,
            event=event,
            submission=submission,
            submission_type=workshop,
            speaker=users["speaker"],
        )
        assert not missing_form.is_valid()
        assert "required" in str(missing_form.errors[field_name]).lower()


@pytest.mark.django_db(transaction=True)
def test_server_rejects_posted_or_persisted_workshop_prerequisites_for_stage_talks(event, users):
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        stage_talk = event.submission_types.get(name="Stage Talk")
        prerequisites = event.questions.get(question="Workshop prerequisites")
        field_name = f"question_{prerequisites.pk}"
        prototype = SpeakerOpsQuestionsForm(event=event, submission_type=stage_talk)
        tampered_data = _required_answers(prototype)
        tampered_data[field_name] = "Injected hidden prerequisites"
        submission = _draft(event, users, stage_talk)
        tampered_form = SpeakerOpsQuestionsForm(
            data=tampered_data,
            event=event,
            submission=submission,
            submission_type=stage_talk,
            speaker=users["speaker"],
        )

        assert not tampered_form.is_valid()
        assert "hidden unless Session type is Workshop" in str(tampered_form.non_field_errors())

        Answer.objects.create(
            question=prerequisites,
            submission=submission,
            answer="Persisted hidden prerequisites",
        )
        with pytest.raises(ValidationError, match="submitted while hidden"):
            validate_persisted_conditional_answers(submission)
