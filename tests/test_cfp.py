from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_scopes import scope
from pretalx.submission.forms import QuestionsForm
from pretalx.submission.models import Answer, QuestionVariant, Submission, SubmissionStates


@pytest.mark.django_db(transaction=True)
def test_seeded_cfp_renders_accepts_all_p0_field_types_and_resumes_draft(event, users):
    with scope(event=event):
        questions = list(event.questions.order_by("position"))
        assert event.cfp.fields["abstract"]["visibility"] == "optional"
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
        assert next(
            question for question in questions if str(question.question) == "Session abstract"
        ).required
        public_form = QuestionsForm(event=event, target="submission")
        rendered = str(public_form)
        assert "Session abstract" in rendered
        assert "Audience interests" in rendered

    with scope(event=event):
        submission_type = event.cfp.default_type
        questions = list(
            event.questions.filter(submission_types=submission_type).order_by("position")
        )
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
        assert Answer.objects.filter(submission=draft).count() == len(questions)
        resumed = QuestionsForm(event=event, submission=draft, target="submission")
        abstract_question = next(
            question for question in questions if str(question.question) == "Session abstract"
        )
        assert resumed.fields[f"question_{abstract_question.pk}"].initial == (
            "A sufficiently long AIE abstract for validation."
        )


@pytest.mark.django_db
def test_changing_shared_cfp_deadline_keeps_submission_formats_open(event):
    """The public form must not lose every format after an operator extends the CFP."""
    with scope(event=event):
        event.enable_plugin("pretalx_speakerops")
        event.save(update_fields=["plugins"])
        original_deadline = event.cfp.deadline
        event.submission_types.update(deadline=original_deadline)

        extended_deadline = original_deadline + timedelta(days=30)
        event.cfp.deadline = extended_deadline
        event.cfp.save(update_fields=["deadline", "updated"])

        assert set(event.submission_types.values_list("deadline", flat=True)) == {
            extended_deadline
        }

        workshop = event.submission_types.get(name="Workshop")
        workshop_deadline = extended_deadline + timedelta(days=7)
        workshop.deadline = workshop_deadline
        workshop.save(update_fields=["deadline", "updated"])

        second_extension = extended_deadline + timedelta(days=60)
        event.cfp.deadline = second_extension
        event.cfp.save(update_fields=["deadline", "updated"])

        workshop.refresh_from_db()
        assert workshop.deadline == workshop_deadline
        assert set(
            event.submission_types.exclude(pk=workshop.pk).values_list("deadline", flat=True)
        ) == {second_extension}


@pytest.mark.django_db(transaction=True)
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
def test_cfp_close_date_blocks_new_submission_and_existing_edit(event, users, client):
    original_title = "Existing submitted proposal"
    original_abstract = "The abstract stored before the CFP closed."
    with scope(event=event):
        submission = Submission.objects.create(
            event=event,
            title=original_title,
            submission_type=event.cfp.default_type,
            state=SubmissionStates.SUBMITTED,
            abstract=original_abstract,
            description="Stored description",
            content_locale=event.locale,
        )
        submission.speakers.add(users["speaker"])

        past_deadline = timezone.now() - timedelta(days=1)
        event.cfp.deadline = past_deadline
        event.cfp.save(update_fields=["deadline", "updated"])
        event.submission_types.update(deadline=past_deadline)

    client.force_login(users["speaker"])
    request_host = settings.SITE_NETLOC

    submit_url = reverse("cfp:event.submit", kwargs={"event": event.slug})
    new_submission = client.get(submit_url, HTTP_HOST=request_host)
    assert new_submission.status_code == 302

    blocked_submission = client.get(new_submission.url, HTTP_HOST=request_host)
    assert blocked_submission.status_code == 302
    assert blocked_submission.url == reverse("cfp:event.start", kwargs={"event": event.slug})
    assert "Proposals are closed" in {
        str(message) for message in get_messages(blocked_submission.wsgi_request)
    }

    edit_url = reverse(
        "cfp:event.user.submission.edit",
        kwargs={"event": event.slug, "code": submission.code},
    )
    edit = client.get(edit_url, HTTP_HOST=request_host)
    assert edit.status_code == 200
    assert edit.context["can_edit"] is False
    assert b'name="action" value="submit"' not in edit.content

    denied_edit = client.post(
        edit_url,
        {
            "title": "Title that must not be stored",
            "abstract": "Abstract that must not be stored",
            "action": "submit",
        },
        HTTP_HOST=request_host,
    )
    assert denied_edit.status_code == 200
    assert denied_edit.context["can_edit"] is False
    assert b'name="action" value="submit"' not in denied_edit.content

    submission.refresh_from_db()
    assert submission.title == original_title
    assert submission.abstract == original_abstract
