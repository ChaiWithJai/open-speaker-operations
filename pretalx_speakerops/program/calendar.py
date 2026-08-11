import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from django.http import Http404
from django_scopes import scope
from pretalx.schedule.ical import get_slots_ical

from ..models import ScheduleIcsIdentity, SessionPublicationApproval

UTC = ZoneInfo("UTC")


def _fingerprint(slot):
    values = (slot.start, slot.real_end, slot.room_id, slot.submission.title, slot.is_visible)
    return hashlib.sha256(repr(values).encode()).hexdigest()


def released_ical(event):
    with scope(event=event):
        schedule = event.current_schedule
        if not schedule:
            raise Http404
        slots = list(
            schedule.talks.filter(is_visible=True)
            .exclude(
                submission__speakerops_publication_approval__status__in=(
                    SessionPublicationApproval.PENDING,
                    SessionPublicationApproval.CHANGES_REQUESTED,
                )
            )
            .select_related("submission", "room")
        )
        seen = set()
        for slot in slots:
            identity, created = ScheduleIcsIdentity.objects.get_or_create(
                event=event,
                submission=slot.submission,
                defaults={
                    "uid": f"speakerops-{event.slug}-{slot.submission.code}@{event.slug}",
                    "fingerprint": _fingerprint(slot),
                },
            )
            seen.add(identity.submission_id)
            fingerprint = _fingerprint(slot)
            if not created and identity.fingerprint != fingerprint:
                identity.sequence += 1
                identity.fingerprint = fingerprint
                identity.canceled = False
                identity.save(update_fields=["sequence", "fingerprint", "canceled", "updated_at"])
        for identity in ScheduleIcsIdentity.objects.filter(event=event).exclude(
            submission_id__in=seen
        ):
            if not identity.canceled:
                identity.sequence += 1
                identity.canceled = True
                identity.save(update_fields=["sequence", "canceled", "updated_at"])
        calendar = get_slots_ical(event, slots, prodid_suffix="speakerops")
        for component, slot in zip(calendar.vevent_list, slots, strict=True):
            identity = ScheduleIcsIdentity.objects.get(event=event, submission=slot.submission)
            if identity:
                component.uid.value = identity.uid
                component.add("sequence").value = str(identity.sequence)
        for identity in ScheduleIcsIdentity.objects.filter(event=event, canceled=True):
            component = calendar.add("vevent")
            component.add("uid").value = identity.uid
            component.add("sequence").value = str(identity.sequence)
            component.add("status").value = "CANCELLED"
            now = datetime.now(UTC)
            component.add("dtstamp").value = now
            component.add("dtstart").value = now
            component.add("dtend").value = now
            component.add("summary").value = "Cancelled session"
        return calendar.serialize()
