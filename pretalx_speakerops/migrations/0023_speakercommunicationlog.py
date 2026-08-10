import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("event", "0040_alter_event_settingsstore_unique_together"),
        ("speakerops", "0022_speakeroperationsprofile_social_url"),
    ]

    operations = [
        migrations.CreateModel(
            name="SpeakerCommunicationLog",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("invitation", "Invitation / onboarding"),
                            ("bulk_email", "Selected-speaker email"),
                        ],
                        max_length=24,
                    ),
                ),
                ("subject", models.CharField(max_length=200)),
                ("rendered_body", models.TextField()),
                (
                    "outcome",
                    models.CharField(
                        choices=[("sent", "Sent"), ("failed", "Failed")], max_length=16
                    ),
                ),
                ("outcome_detail", models.TextField(blank=True, default="")),
                ("queued_mail_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("attempted_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="speakerops_communications_sent",
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
                    "speaker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="speakerops_communications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-attempted_at", "-pk"),
                "indexes": [
                    models.Index(
                        fields=["event", "speaker", "kind"],
                        name="speakerops_comm_event_speaker",
                    )
                ],
            },
        )
    ]
