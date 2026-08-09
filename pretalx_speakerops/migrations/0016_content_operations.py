import django.db.models.deletion
import django.utils.timezone
import pretalx.common.models.mixins
import rules.contrib.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0015_abstract_management_rounds"),
        ("submission", "0087_question_limit_teams"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EvidenceComment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "author",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="speakerops_evidence_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
                (
                    "evidence",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to="speakerops.taskevidence",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "pk")},
            bases=(
                pretalx.common.models.mixins.LogMixin,
                pretalx.common.models.mixins.FileCleanupMixin,
                rules.contrib.models.RulesModelMixin,
                models.Model,
            ),
        ),
        migrations.CreateModel(
            name="SessionPublicationApproval",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending approval"),
                            ("approved", "Approved for publication"),
                            ("changes_requested", "Changes requested"),
                        ],
                        default="pending",
                        max_length=24,
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="speakerops_publication_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_publication_approval",
                        to="submission.submission",
                    ),
                ),
            ],
            bases=(
                pretalx.common.models.mixins.LogMixin,
                pretalx.common.models.mixins.FileCleanupMixin,
                rules.contrib.models.RulesModelMixin,
                models.Model,
            ),
        ),
        migrations.AddConstraint(
            model_name="sessionpublicationapproval",
            constraint=models.UniqueConstraint(
                fields=("event", "submission"),
                name="speakerops_publication_approval_event_submission",
            ),
        ),
    ]
