import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0028_alter_speakercommunicationlog_kind")]

    operations = [
        migrations.CreateModel(
            name="ScheduledReminderRun",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
                ("schedule_date", models.DateField()),
                ("scheduled_for", models.DateTimeField()),
                ("celery_task_id", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("started", "Started"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("ambiguous", "Ambiguous"),
                        ],
                        default="started",
                        max_length=20,
                    ),
                ),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("eligible_count", models.PositiveIntegerField(default=0)),
                ("accepted_count", models.PositiveIntegerField(default=0)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="event.event"
                    ),
                ),
            ],
            options={
                "ordering": ("-started_at", "-pk"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "schedule_date", "celery_task_id"),
                        name="speakerops_scheduled_reminder_run",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="reminderreceipt",
            name="due_date_at_dispatch",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reminderreceipt",
            name="scheduled_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="receipts",
                to="speakerops.scheduledreminderrun",
            ),
        ),
    ]
