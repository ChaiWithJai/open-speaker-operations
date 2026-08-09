import django.db.models.deletion
import django.utils.timezone
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
    dependencies = [
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0006_reviewrecommendation"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConferenceSeries",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("website", models.URLField()),
                ("source_policy", models.JSONField(default=dict)),
            ],
            options={"ordering": ("name",)},
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="HistoricalSpeaker",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("canonical_key", models.CharField(max_length=200, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("biography", models.TextField(blank=True)),
                ("source_url", models.URLField()),
                ("source_updated_at", models.DateTimeField()),
            ],
            options={"ordering": ("name",)},
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="AcceptanceWave",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("name", models.CharField(max_length=120)),
                ("decision_at", models.DateTimeField()),
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
            ],
            options={
                "ordering": ("position", "decision_at"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "name"), name="speakerops_wave_event_name"
                    )
                ],
            },
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="ConferenceEdition",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("external_key", models.CharField(max_length=160)),
                ("name", models.CharField(max_length=240)),
                ("date_from", models.DateField(blank=True, null=True)),
                ("date_to", models.DateField(blank=True, null=True)),
                ("location", models.CharField(blank=True, max_length=240)),
                ("source_url", models.URLField()),
                ("source_updated_at", models.DateTimeField()),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="editions",
                        to="speakerops.conferenceseries",
                    ),
                ),
            ],
            options={
                "ordering": ("series__name", "date_from", "name"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("series", "external_key"),
                        name="speakerops_edition_series_external_key",
                    )
                ],
            },
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="ProgramDecision",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("accept", "Accept"),
                            ("waitlist", "Waitlist"),
                            ("reject", "Reject"),
                        ],
                        max_length=20,
                    ),
                ),
                ("rationale", models.TextField(blank=True)),
                ("decided_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="person.user",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
                (
                    "submission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="speakerops_program_decision",
                        to="submission.submission",
                    ),
                ),
                (
                    "wave",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="decisions",
                        to="speakerops.acceptancewave",
                    ),
                ),
            ],
            options={
                "ordering": ("-decided_at",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "submission"),
                        name="speakerops_decision_event_submission",
                    )
                ],
            },
            bases=PRETALX_BASES,
        ),
        migrations.CreateModel(
            name="HistoricalTalk",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("external_key", models.CharField(max_length=200)),
                ("title", models.CharField(max_length=300)),
                ("abstract", models.TextField(blank=True)),
                ("session_format", models.CharField(blank=True, max_length=100)),
                ("track", models.CharField(blank=True, max_length=160)),
                ("level", models.CharField(blank=True, max_length=80)),
                ("topics", models.JSONField(default=list)),
                ("recording_url", models.URLField(blank=True)),
                ("source_url", models.URLField()),
                ("source_updated_at", models.DateTimeField()),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="talks",
                        to="speakerops.conferenceedition",
                    ),
                ),
                (
                    "speakers",
                    models.ManyToManyField(
                        related_name="historical_talks", to="speakerops.historicalspeaker"
                    ),
                ),
            ],
            options={
                "ordering": ("edition__date_from", "title"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("edition", "external_key"),
                        name="speakerops_talk_edition_external_key",
                    )
                ],
            },
            bases=PRETALX_BASES,
        ),
    ]
