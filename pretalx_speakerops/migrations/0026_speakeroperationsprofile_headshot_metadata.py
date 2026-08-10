from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0025_mailtemplate_null_role_compatibility")]

    operations = [
        migrations.AddField(
            model_name="speakeroperationsprofile",
            name="headshot_original_filename",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="speakeroperationsprofile",
            name="headshot_uploaded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
