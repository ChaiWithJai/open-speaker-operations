from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django_scopes import scope
from pretalx.schedule.models import Schedule
from pretalx.schedule.services import freeze_schedule


@dataclass(frozen=True)
class WarningPolicy:
    blocking_categories: frozenset[str] = frozenset({"room", "speaker"})


POLICY = WarningPolicy()


def schedule_slots(schedule):
    """Load the schedule data needed for overlap checks in bounded queries."""
    return list(
        schedule.talks.filter(
            submission__isnull=False,
            start__isnull=False,
            end__isnull=False,
        )
        .select_related("room", "submission")
        .prefetch_related("submission__speakers")
        .order_by("start", "pk")
    )


def classify_warnings(schedule, *, slots=None):
    """Return canonical room/speaker overlap rows using one prefetched slot set."""
    slots = schedule_slots(schedule) if slots is None else slots
    speakers_by_slot = {
        slot.pk: {speaker.pk: speaker for speaker in slot.submission.speakers.all()}
        for slot in slots
    }
    classified = []
    for index, talk in enumerate(slots):
        for competitor in slots[index + 1 :]:
            if competitor.start >= talk.end:
                break
            if talk.start >= competitor.end:
                continue
            title = talk.submission.title
            competing_title = competitor.submission.title
            if talk.room_id and talk.room_id == competitor.room_id:
                resource = f"room {talk.room.name}"
                classified.append(
                    _warning_row(talk, competitor, "room", title, competing_title, resource)
                )
            shared = set(speakers_by_slot[talk.pk]) & set(speakers_by_slot[competitor.pk])
            for speaker_id in sorted(shared):
                speaker = speakers_by_slot[talk.pk][speaker_id]
                resource = f"speaker {speaker.get_display_name()}"
                classified.append(
                    _warning_row(talk, competitor, "speaker", title, competing_title, resource)
                )
    return classified


def _warning_row(talk, competitor, category, title, competing_title, resource):
    message = f"{title} conflicts with {competing_title} ({resource})."
    return {
        "talk": talk,
        "warning": {"type": category, "message": message},
        "category": category,
        "message": message,
        "competitor": competitor,
        "blocking": category in POLICY.blocking_categories,
    }


def blocking_warnings(schedule):
    return [item for item in classify_warnings(schedule) if item["blocking"]]


def assert_release_allowed(schedule):
    blocked = blocking_warnings(schedule)
    if blocked:
        raise ValidationError("Schedule release blocked by unresolved conflicts.")


def release_schedule(schedule, name, user=None, **kwargs):
    """The plugin's release entry point, preserving pretalx's freeze service."""
    with scope(event=schedule.event):
        assert_release_allowed(schedule)
        return freeze_schedule(schedule, name=name, user=user, **kwargs)


@receiver(pre_save, sender=Schedule)
def enforce_schedule_release_policy(sender, instance, **kwargs):
    if not instance.version or not instance.event_id:
        return
    event = instance.event
    if "pretalx_speakerops" not in event.plugin_list:
        return
    if sender.objects.filter(pk=instance.pk, version__isnull=True).exists():
        with scope(event=event):
            assert_release_allowed(instance)
