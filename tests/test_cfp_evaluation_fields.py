import pytest
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_scopes import scope
from pretalx.submission.models import (
    Answer,
    Question,
    QuestionVariant,
    Submission,
    SubmissionStates,
)

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
        assert not audience.required
        assert list(audience.options.order_by("position").values_list("answer", flat=True)) == [
            "Beginner",
            "Intermediate",
            "Advanced",
        ]
        assert takeaway.variant == QuestionVariant.STRING
        assert takeaway.required
        assert prerequisites.variant == QuestionVariant.STRING
        assert prerequisites.required
        assert list(prerequisites.submission_types.values_list("name", flat=True)) == [
            "Workshop",
            "Workshop (120 min)",
        ]


@pytest.mark.django_db(transaction=True)
def test_organizer_builder_fields_render_and_validate_on_public_form(event, users, client):
    """CFP-01: prove the organizer builder-to-public-form contract over HTTP."""
    with scope(event=event):
        Question.all_objects.filter(
            event=event,
            question__in=("Key takeaway", "Audience level"),
        ).update(active=False)
        submission_type = event.cfp.default_type
        submission_type_ids = [str(item.pk) for item in event.submission_types.all()]

    client.force_login(users["chair"])
    create_url = reverse("orga:cfp.questions.create", kwargs={"event": event.slug})
    builder = client.get(create_url)

    assert builder.status_code == 200
    assert b"Text (one-line)" in builder.content
    assert b"Multi-line text" in builder.content
    assert b"Choose one from a list" in builder.content

    common = {
        "target": "submission",
        "question_required": "required",
        "icon": "-",
        "submission_types": submission_type_ids,
    }
    takeaway_response = client.post(
        create_url,
        {**common, "variant": "string", "question_0": "Key takeaway"},
    )
    bio_response = client.post(
        create_url,
        {
            **common,
            "variant": "text",
            "question_0": "Speaker bio proof",
            "question_required": "optional",
        },
    )
    audience_response = client.post(
        create_url,
        {
            **common,
            "variant": "choices",
            "question_0": "Audience level",
            "options": SimpleUploadedFile(
                "audience-levels.txt",
                b"Beginner\nIntermediate\nAdvanced\n",
                content_type="text/plain",
            ),
        },
    )

    assert takeaway_response.status_code == 302, takeaway_response.context["form"].errors
    assert bio_response.status_code == 302, bio_response.context["form"].errors
    assert audience_response.status_code == 302, audience_response.context["form"].errors

    with scope(event=event):
        built_questions = {str(question.question): question for question in event.questions.all()}
        takeaway = built_questions["Key takeaway"]
        bio = built_questions["Speaker bio proof"]
        audience = built_questions["Audience level"]
        public_form = SpeakerOpsQuestionsForm(
            event=event,
            submission_type=submission_type,
        )
        takeaway_name = f"question_{takeaway.pk}"
        bio_name = f"question_{bio.pk}"
        audience_name = f"question_{audience.pk}"

        assert isinstance(public_form.fields[takeaway_name].widget, forms.TextInput)
        assert public_form.fields[takeaway_name].required
        assert isinstance(public_form.fields[bio_name].widget, forms.Textarea)
        assert not public_form.fields[bio_name].required
        assert isinstance(public_form.fields[audience_name].widget, forms.Select)
        assert list(audience.options.order_by("position").values_list("answer", flat=True)) == [
            "Beginner",
            "Intermediate",
            "Advanced",
        ]

        submission = _draft(event, users, submission_type)
        missing_takeaway = _required_answers(public_form)
        missing_takeaway.pop(takeaway_name)
        invalid_form = SpeakerOpsQuestionsForm(
            data=missing_takeaway,
            event=event,
            submission=submission,
            submission_type=submission_type,
            speaker=users["speaker"],
        )

        assert not invalid_form.is_valid()
        assert "required" in str(invalid_form.errors[takeaway_name]).lower()


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
