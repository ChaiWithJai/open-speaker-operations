from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import pretalx.common.models.mixins
import rules.contrib.models


PRETALX_BASES = (
    pretalx.common.models.mixins.LogMixin,
    pretalx.common.models.mixins.FileCleanupMixin,
    rules.contrib.models.RulesModelMixin,
    models.Model,
)


class Migration(migrations.Migration):
    dependencies = [
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0010_reviewrecommendation_save_revision"),
        ("submission", "0087_question_limit_teams"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConditionalQuestionRule",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("name", models.CharField(max_length=160)),
                ("target_required_on_match", models.BooleanField(default=True)),
                ("active", models.BooleanField(default=True)),
                (
                    "controller_question",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="speakerops_controlled_rules",
                        to="submission.question",
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
                    "target_question",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="speakerops_visibility_rules",
                        to="submission.question",
                    ),
                ),
                (
                    "trigger_option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="speakerops_triggered_rules",
                        to="submission.answeroption",
                    ),
                ),
            ],
            options={"ordering": ("name",)},
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="ReviewerPool",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("slug", models.SlugField(max_length=80)),
                ("name", models.CharField(max_length=160)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="event.event",
                    ),
                ),
                (
                    "reviewers",
                    models.ManyToManyField(
                        related_name="speakerops_reviewer_pools",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("name",)},
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="ReviewerPoolTrack",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="event.event",
                    ),
                ),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="track_mappings",
                        to="speakerops.reviewerpool",
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_pool_mappings",
                        to="submission.track",
                    ),
                ),
            ],
            options={"ordering": ("track__position", "track__name")},
            bases=PRETALX_BASES,
        ),
        migrations.AddConstraint(
            model_name="conditionalquestionrule",
            constraint=models.UniqueConstraint(
                fields=("event", "name"), name="speakerops_conditional_rule_event_name"
            ),
        ),
        migrations.AddConstraint(
            model_name="reviewerpool",
            constraint=models.UniqueConstraint(
                fields=("event", "slug"), name="speakerops_reviewer_pool_event_slug"
            ),
        ),
        migrations.AddConstraint(
            model_name="reviewerpooltrack",
            constraint=models.UniqueConstraint(
                fields=("event", "track"), name="speakerops_reviewer_pool_event_track"
            ),
        ),
        migrations.AddConstraint(
            model_name="reviewerpooltrack",
            constraint=models.UniqueConstraint(
                fields=("pool", "track"), name="speakerops_reviewer_pool_track"
            ),
        ),
    ]
