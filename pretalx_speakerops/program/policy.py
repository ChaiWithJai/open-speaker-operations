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


def classify_warnings(schedule):
    warnings = schedule.get_all_talk_warnings()
    classified = []
    for talk, talk_warnings in warnings.items():
        for warning in talk_warnings:
            category = warning.get("type", "advisory")
            competitor, resource = _competing_assignment(schedule, talk, category)
            title = talk.submission.title if talk.submission else str(talk)
            message = warning.get("message", str(warning))
            if competitor:
                competing_title = (
                    competitor.submission.title if competitor.submission else str(competitor)
                )
                message = f"{title} conflicts with {competing_title} ({resource})."
            classified.append(
                {
                    "talk": talk,
                    "warning": warning,
                    "category": category,
                    "message": message,
                    "competitor": competitor,
                    "blocking": category in POLICY.blocking_categories
                    or category in {"room_overlap", "speaker_overlap"},
                }
            )
    return classified


def _competing_assignment(schedule, talk, category):
    """Return the competing slot and named resource for an overlap warning."""
    if not talk.start or not talk.end:
        return None, "schedule"
    candidates = (
        schedule.talks.filter(start__lt=talk.end, end__gt=talk.start)
        .exclude(pk=talk.pk)
        .select_related("room", "submission")
        .prefetch_related("submission__speakers")
    )
    talk_speakers = set()
    if talk.submission_id:
        talk_speakers = set(talk.submission.speakers.values_list("pk", flat=True))
    for candidate in candidates:
        same_room = talk.room_id and candidate.room_id == talk.room_id
        candidate_speakers = (
            set(candidate.submission.speakers.values_list("pk", flat=True))
            if candidate.submission_id
            else set()
        )
        shared_speakers = talk_speakers & candidate_speakers
        if "room" in category and same_room:
            return candidate, f"room {talk.room.name}"
        if "speaker" in category and shared_speakers:
            speaker = talk.submission.speakers.filter(pk__in=shared_speakers).first()
            return candidate, f"speaker {speaker.get_display_name}"
        if same_room:
            return candidate, f"room {talk.room.name}"
        if shared_speakers:
            speaker = talk.submission.speakers.filter(pk__in=shared_speakers).first()
            return candidate, f"speaker {speaker.get_display_name}"
    return None, "schedule"


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
