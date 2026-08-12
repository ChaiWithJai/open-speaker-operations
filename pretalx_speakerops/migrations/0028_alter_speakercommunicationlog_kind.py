from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0027_workflowactionreceipt")]

    operations = [
        migrations.AlterField(
            model_name="speakercommunicationlog",
            name="kind",
            field=models.CharField(
                choices=[
                    ("invitation", "Invitation / onboarding"),
                    ("bulk_email", "Selected-speaker email"),
                    ("automated_reminder", "Automated task reminder"),
                ],
                max_length=24,
            ),
        ),
    ]
