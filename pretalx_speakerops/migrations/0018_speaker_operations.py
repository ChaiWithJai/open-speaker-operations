import django.db.models.deletion
import pretalx.common.models.mixins
import rules.contrib.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0017_content_revisions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SpeakerOperationsProfile",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "workflow_status",
                    models.CharField(
                        choices=[
                            ("invited", "Invited"),
                            ("confirmed", "Confirmed"),
                            ("onboarding", "Onboarding"),
                            ("ready", "Ready"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="invited",
                        max_length=20,
                    ),
                ),
                ("travel_preferences", models.TextField(blank=True, default="")),
                ("dietary_requirements", models.TextField(blank=True, default="")),
                ("accessibility_requirements", models.TextField(blank=True, default="")),
                ("logistics_notes", models.TextField(blank=True, default="")),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
                (
                    "speaker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_event_profiles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("speaker__name", "speaker__email")},
            bases=(
                pretalx.common.models.mixins.LogMixin,
                pretalx.common.models.mixins.FileCleanupMixin,
                rules.contrib.models.RulesModelMixin,
                models.Model,
            ),
        ),
        migrations.AddConstraint(
            model_name="speakeroperationsprofile",
            constraint=models.UniqueConstraint(
                fields=("event", "speaker"), name="speakerops_event_speaker_operations_profile"
            ),
        ),
    ]
