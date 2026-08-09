import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def number_existing_versions(apps, schema_editor):
    evidence_model = apps.get_model("speakerops", "TaskEvidence")
    task_ids = evidence_model.objects.values_list("task_id", flat=True).distinct()
    for task_id in task_ids.iterator():
        rows = evidence_model.objects.filter(task_id=task_id).order_by("created_at", "pk")
        for version, evidence in enumerate(rows.iterator(), start=1):
            evidence_model.objects.filter(pk=evidence.pk).update(version=version)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("speakerops", "0011_cfp_conditional_routing"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskevidence",
            name="review_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="taskevidence",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("pending", "Awaiting review"),
                    ("approved", "Approved"),
                    ("changes_requested", "Changes requested"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="taskevidence",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskevidence",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="speakerops_reviewed_evidence",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taskevidence",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(number_existing_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="taskevidence",
            constraint=models.UniqueConstraint(
                fields=("task", "version"), name="speakerops_task_evidence_version"
            ),
        ),
        migrations.AlterModelOptions(
            name="taskevidence",
            options={"ordering": ("-version", "-created_at")},
        ),
    ]
