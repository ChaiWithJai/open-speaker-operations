import django.db.models.deletion
import django.utils.timezone
import pretalx.common.models.mixins
import rules.contrib.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0016_content_operations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentRevision",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "content_type",
                    models.CharField(
                        choices=[("session", "Session"), ("speaker", "Speaker")], max_length=16
                    ),
                ),
                ("object_id", models.PositiveBigIntegerField()),
                ("label", models.CharField(max_length=240)),
                ("snapshot", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="speakerops_content_revisions",
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
                    "restored_from",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="restore_events",
                        to="speakerops.contentrevision",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["event", "content_type", "object_id"],
                        name="speakerops__event_i_bdbf4f_idx",
                    )
                ],
            },
            bases=(
                pretalx.common.models.mixins.LogMixin,
                pretalx.common.models.mixins.FileCleanupMixin,
                rules.contrib.models.RulesModelMixin,
                models.Model,
            ),
        ),
    ]
