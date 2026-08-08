import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django_scopes import scope
from pretalx.submission.forms import QuestionsForm
from pretalx.submission.models import Answer, QuestionVariant, Submission, SubmissionStates


@pytest.mark.django_db(transaction=True)
def test_seeded_cfp_renders_accepts_all_p0_field_types_and_resumes_draft(event, users):
    with scope(event=event):
        questions = list(event.questions.order_by("position"))
        assert {question.variant for question in questions} >= {
            QuestionVariant.STRING,
            QuestionVariant.TEXT,
            QuestionVariant.URL,
            QuestionVariant.BOOLEAN,
            QuestionVariant.CHOICES,
            QuestionVariant.MULTIPLE,
            QuestionVariant.FILE,
        }
        assert all(question.submission_types.exists() for question in questions)
        assert any(question.required for question in questions)
        public_form = QuestionsForm(event=event, target="submission")
        rendered = str(public_form)
        assert "Session abstract" in rendered
        assert "Audience interests" in rendered

    with scope(event=event):
        submission_type = event.cfp.default_type
        draft = Submission.objects.create(
            event=event,
            title="AIE draft",
            submission_type=submission_type,
            state=SubmissionStates.DRAFT,
            abstract="Draft abstract",
            description="Draft description",
            content_locale=event.locale,
        )
        draft.speakers.add(users["speaker"])
        form = QuestionsForm(
            event=event,
            submission=draft,
            target="submission",
            data={
                f"question_{question.pk}": (
                    str(question.options.first().pk)
                    if question.variant == QuestionVariant.CHOICES
                    else (
                        [str(option.pk) for option in question.options.all()]
                        if question.variant == QuestionVariant.MULTIPLE
                        else (
                            "A sufficiently long AIE abstract for validation."
                            if question.variant == QuestionVariant.TEXT
                            else (
                                "https://example.org/ai"
                                if question.variant == QuestionVariant.URL
                                else (
                                    "Main stage"
                                    if question.variant == QuestionVariant.STRING
                                    else "on"
                                )
                            )
                        )
                    )
                )
                for question in questions
                if question.variant != QuestionVariant.FILE
            },
            files={
                f"question_{question.pk}": SimpleUploadedFile(
                    "headshot.txt", b"demo image placeholder", content_type="text/plain"
                )
                for question in questions
                if question.variant == QuestionVariant.FILE
            },
        )
        assert form.is_valid(), form.errors
        form.save()
        assert Answer.objects.filter(submission=draft).count() == 7
        resumed = QuestionsForm(event=event, submission=draft, target="submission")
        assert resumed.fields[f"question_{questions[2].pk}"].initial == (
            "A sufficiently long AIE abstract for validation."
        )
