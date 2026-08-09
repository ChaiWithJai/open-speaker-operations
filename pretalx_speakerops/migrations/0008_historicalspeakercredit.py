import django.db.models.deletion
import pretalx.common.models.mixins
import rules.contrib.models
from django.db import migrations, models


PRETALX_BASES = (
    pretalx.common.models.mixins.LogMixin,
    pretalx.common.models.mixins.FileCleanupMixin,
    rules.contrib.models.RulesModelMixin,
    models.Model,
)


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0007_conference_memory_and_acceptance_waves")]

    operations = [
        migrations.CreateModel(
            name="HistoricalSpeakerCredit",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("name_at_source", models.CharField(max_length=200)),
                ("position", models.PositiveIntegerField(default=0)),
                ("source_url", models.URLField()),
                ("source_updated_at", models.DateTimeField()),
                (
                    "speaker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credits",
                        to="speakerops.historicalspeaker",
                    ),
                ),
                (
                    "talk",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credits",
                        to="speakerops.historicaltalk",
                    ),
                ),
            ],
            options={
                "ordering": ("position", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("talk", "speaker"), name="speakerops_credit_talk_speaker"
                    )
                ],
            },
            bases=PRETALX_BASES,
        )
    ]
