from django.db import migrations


def split_reused_pyladies_identity(apps, schema_editor):
    HistoricalSpeaker = apps.get_model("speakerops", "HistoricalSpeaker")
    HistoricalSpeakerCredit = apps.get_model("speakerops", "HistoricalSpeakerCredit")
    collided = HistoricalSpeaker.objects.filter(canonical_key="R8PQYJ").first()
    if not collided:
        return
    sarah_credit = HistoricalSpeakerCredit.objects.filter(
        speaker=collided,
        name_at_source="Sarah Adigwe",
    ).first()
    marie_credits = HistoricalSpeakerCredit.objects.filter(
        speaker=collided,
        name_at_source="Marie-Louise Annan",
    )
    if not sarah_credit or not marie_credits.exists():
        return
    marie_credit = marie_credits.first()
    marie, _created = HistoricalSpeaker.objects.update_or_create(
        canonical_key="pyladies-marie-louise-annan",
        defaults={
            "name": "Marie-Louise Annan",
            "biography": "",
            "source_url": marie_credit.source_url,
            "source_updated_at": marie_credit.source_updated_at,
        },
    )
    talk_ids = list(marie_credits.values_list("talk_id", flat=True))
    marie_credits.update(speaker=marie)
    collided.name = "Sarah Adigwe"
    collided.source_url = sarah_credit.source_url
    collided.source_updated_at = sarah_credit.source_updated_at
    collided.save(update_fields=["name", "source_url", "source_updated_at", "updated"])
    HistoricalTalk = apps.get_model("speakerops", "HistoricalTalk")
    for talk in HistoricalTalk.objects.filter(pk__in=talk_ids):
        talk.speakers.set(talk.credits.values_list("speaker_id", flat=True).distinct())


class Migration(migrations.Migration):
    dependencies = [("speakerops", "0020_historicalsourceidentity_historicalidentitydecision_and_more")]

    operations = [
        migrations.RunPython(split_reused_pyladies_identity, migrations.RunPython.noop),
    ]
