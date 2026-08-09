from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0009_programdecision_applied_audit")]

    operations = [
        migrations.AddField(
            model_name="reviewrecommendation",
            name="client_revision",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="reviewrecommendation",
            name="save_session",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="reviewrecommendation",
            name="save_version",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
