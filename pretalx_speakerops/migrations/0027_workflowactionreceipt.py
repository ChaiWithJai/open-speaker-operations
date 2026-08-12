import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def backfill_accepted_reminder_receipts(apps, schema_editor):
    ReminderReceipt = apps.get_model("speakerops", "ReminderReceipt")
    ReminderReceipt.objects.filter(queued_mail_id__isnull=False).update(
        delivery_status="accepted"
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("speakerops", "0026_speakeroperationsprofile_headshot_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowActionReceipt",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False),
                ),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "workflow",
                    models.CharField(
                        choices=[
                            ("speaker_nudges", "Speaker nudges"),
                            ("sync_recovery", "Synchronization recovery"),
                        ],
                        max_length=40,
                    ),
                ),
                ("action", models.CharField(max_length=80)),
                ("correlation_id", models.UUIDField()),
                ("requesting_principal", models.CharField(max_length=160)),
                ("claimed_channel_id", models.CharField(blank=True, default="", max_length=200)),
                (
                    "claimed_trigger_event_id",
                    models.CharField(blank=True, default="", max_length=200),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("succeeded", "Succeeded"),
                            ("partial", "Partial"),
                            ("failed", "Failed"),
                            ("ambiguous", "Ambiguous; inspect before retrying"),
                            ("noop", "No action needed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("confirmed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("target_count", models.PositiveIntegerField(default=0)),
                ("result", models.JSONField(default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="speakerops_workflow_action_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="event.event",
                    ),
                ),
            ],
            options={"ordering": ("-confirmed_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="workflowactionreceipt",
            constraint=models.UniqueConstraint(
                fields=("event", "correlation_id"),
                name="speakerops_workflow_receipt_event_correlation",
            ),
        ),
        migrations.AddField(
            model_name="reminderreceipt",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending broker handoff"),
                    ("accepted", "Broker accepted"),
                    ("ambiguous", "Broker outcome ambiguous"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.RunPython(
            backfill_accepted_reminder_receipts,
            migrations.RunPython.noop,
        ),
        migrations.CreateModel(
            name="SyncWriteClaim",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated", models.DateTimeField(auto_now=True, null=True)),
                ("local_type", models.CharField(max_length=40)),
                ("local_id", models.PositiveBigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("in_progress", "In progress"), ("ambiguous", "Ambiguous")],
                        default="in_progress",
                        max_length=20,
                    ),
                ),
                ("active", models.BooleanField(default=True)),
                ("claimed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution", models.CharField(blank=True, default="", max_length=80)),
                ("resolution_note", models.CharField(blank=True, default="", max_length=500)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
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
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="write_claims",
                        to="speakerops.syncitem",
                    ),
                ),
                (
                    "receipt",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sync_write_claims",
                        to="speakerops.workflowactionreceipt",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_speakerops_sync_claims",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="syncwriteclaim",
            constraint=models.UniqueConstraint(
                condition=models.Q(("active", True)),
                fields=("event", "local_type", "local_id"),
                name="speakerops_active_sync_logical_claim",
            ),
        ),
    ]
