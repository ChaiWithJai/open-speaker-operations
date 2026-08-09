from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django_scopes import scope


@dataclass(frozen=True)
class ProposedPlacement:
    slot: object
    room: object
    start: datetime
    end: datetime

    @property
    def changed(self):
        return (
            self.slot.room_id != self.room.pk
            or self.slot.start != self.start
            or self.slot.end != self.end
        )


def _overlaps(start, end, other_start, other_end):
    return start < other_end and other_start < end


def build_schedule_proposal(schedule, *, day_start=time(9), day_end=time(18), step_minutes=15):
    """Build a deterministic, conflict-free proposal without mutating the schedule.

    The solver intentionally optimizes for a trustworthy operator workflow rather
    than claiming subjective programme intelligence. It respects room capacity,
    talk duration, event dates and speaker double-booking; the chair still decides
    whether to apply the result.
    """
    event = schedule.event
    rooms = list(event.rooms.order_by("position", "pk"))
    if not rooms:
        raise ValidationError("Add at least one room before generating an agenda proposal.")

    slots = list(
        schedule.talks.filter(submission__isnull=False, is_visible=True)
        .select_related("submission", "room")
        .prefetch_related("submission__speakers")
        .order_by("start", "pk")
    )
    if not slots:
        raise ValidationError("Add at least one session before generating an agenda proposal.")

    candidates = []
    current_day = event.date_from
    while current_day <= event.date_to:
        cursor = datetime.combine(current_day, day_start, tzinfo=event.tz)
        limit = datetime.combine(current_day, day_end, tzinfo=event.tz)
        while cursor < limit:
            candidates.append(cursor)
            cursor += timedelta(minutes=step_minutes)
        current_day += timedelta(days=1)

    occupied = []
    placements = []
    for slot in slots:
        duration = timedelta(minutes=max(slot.duration or step_minutes, step_minutes))
        speaker_ids = frozenset(slot.submission.speakers.values_list("pk", flat=True))
        chosen = None
        for start in candidates:
            end = start + duration
            day_limit = datetime.combine(start.date(), day_end, tzinfo=event.tz)
            if end > day_limit:
                continue
            for room in rooms:
                collision = any(
                    _overlaps(start, end, item["start"], item["end"])
                    and (item["room_id"] == room.pk or speaker_ids & item["speaker_ids"])
                    for item in occupied
                )
                if not collision:
                    chosen = ProposedPlacement(slot=slot, room=room, start=start, end=end)
                    break
            if chosen:
                break
        if not chosen:
            raise ValidationError(
                f"No conflict-free placement is available for “{slot.submission.title}”. "
                "Add room capacity or extend the event hours."
            )
        placements.append(chosen)
        occupied.append(
            {
                "room_id": chosen.room.pk,
                "start": chosen.start,
                "end": chosen.end,
                "speaker_ids": speaker_ids,
            }
        )
    return placements


@transaction.atomic
def apply_schedule_proposal(schedule):
    """Recalculate and atomically apply the operator-approved proposal."""
    with scope(event=schedule.event):
        placements = build_schedule_proposal(schedule)
        changed = 0
        for placement in placements:
            if not placement.changed:
                continue
            placement.slot.room = placement.room
            placement.slot.start = placement.start
            placement.slot.end = placement.end
            placement.slot.save(update_fields=["room", "start", "end", "updated"])
            changed += 1
    return placements, changed
