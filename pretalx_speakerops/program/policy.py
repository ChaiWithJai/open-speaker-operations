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
            classified.append(
                {
                    "talk": talk,
                    "warning": warning,
                    "category": category,
                    "blocking": category in POLICY.blocking_categories
                    or category in {"room_overlap", "speaker_overlap"},
                }
            )
    return classified


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
