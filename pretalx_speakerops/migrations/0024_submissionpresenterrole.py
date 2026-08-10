import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_presenter_roles(apps, schema_editor):
    Submission = apps.get_model("submission", "Submission")
    SubmissionPresenterRole = apps.get_model("speakerops", "SubmissionPresenterRole")
    roles = []
    for submission in Submission.objects.all().iterator():
        for position, speaker_id in enumerate(
            submission.speakers.order_by("pk").values_list("pk", flat=True)
        ):
            roles.append(
                SubmissionPresenterRole(
                    event_id=submission.event_id,
                    submission_id=submission.pk,
                    speaker_id=speaker_id,
                    role="primary_author" if position == 0 else "co_presenter",
                )
            )
    SubmissionPresenterRole.objects.bulk_create(roles, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0023_speakercommunicationlog"),
        ("submission", "0087_question_limit_teams"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubmissionPresenterRole",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("primary_author", "Primary author"),
                            ("co_author", "Co-author"),
                            ("co_presenter", "Co-presenter"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="event.event",
                    ),
                ),
                (
                    "speaker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_submission_roles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_presenter_roles",
                        to="submission.submission",
                    ),
                ),
            ],
            options={"ordering": ("role", "speaker__name", "speaker__email")},
        ),
        migrations.RunPython(backfill_presenter_roles, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="submissionpresenterrole",
            constraint=models.UniqueConstraint(
                fields=("event", "submission", "speaker"),
                name="speakerops_presenter_role_event_submission_speaker",
            ),
        ),
        migrations.AddConstraint(
            model_name="submissionpresenterrole",
            constraint=models.UniqueConstraint(
                condition=models.Q(("role", "primary_author")),
                fields=("submission",),
                name="speakerops_presenter_role_one_primary",
            ),
        ),
    ]
