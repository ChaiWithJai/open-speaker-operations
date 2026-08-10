from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("speakerops", "0021_split_reused_pyladies_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="speakeroperationsprofile",
            name="social_url",
            field=models.URLField(blank=True, default=""),
        ),
    ]
