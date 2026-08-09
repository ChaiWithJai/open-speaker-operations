from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0013_speakermemoryprofile")]

    operations = [
        migrations.AddField(
            model_name="historicaltalk",
            name="field_provenance",
            field=models.JSONField(default=dict),
        ),
    ]
