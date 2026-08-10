from django.db import migrations, transaction
from django.db.models import Count


def consolidate_roleless_templates(apps, schema_editor):
    mail_template = apps.get_model("mail", "MailTemplate")
    # PostgreSQL cannot create the partial index below while deletes in the same
    # transaction still have pending FK trigger events. Keep consolidation atomic,
    # but commit it before the index DDL runs.
    with transaction.atomic():
        duplicates = (
            mail_template.objects.filter(role__isnull=True)
            .values("event_id")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
        )
        for row in duplicates.iterator():
            template_ids = list(
                mail_template.objects.filter(
                    event_id=row["event_id"], role__isnull=True
                )
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            mail_template.objects.filter(pk__in=template_ids[1:]).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("speakerops", "0024_submissionpresenterrole"),
        ("mail", "0013_mailtemplate_role"),
    ]

    operations = [
        migrations.RunPython(consolidate_roleless_templates, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "speakerops_mailtemplate_one_null_role_per_event "
                "ON mail_mailtemplate (event_id) WHERE role IS NULL"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS speakerops_mailtemplate_one_null_role_per_event"
            ),
        ),
    ]
