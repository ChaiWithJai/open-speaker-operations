# Decision: Publication warning policy

## Question

How can SpeakerOps block unsafe publication without reimplementing pretalx's
schedule conflict engine?

## Goal and architecture depth

The goal is that a judge can deliberately create a room or speaker conflict,
see it in the organiser UI, and cannot expose it publicly until resolved. This
is a publication-boundary policy above pretalx's schedule editor and warning
domain.

## Baseline and evidence

Pinned pretalx `2025.2.2` implements
`Schedule.get_talk_warnings()` and `get_all_talk_warnings()` in
`pretalx/schedule/models/schedule.py`; warnings carry types such as
`room_overlap` and `speaker_overlap`. `pretalx/schedule/services.py:freeze_schedule`
creates the released version and `schedule_release` fires after the freeze.

## Options and rejected cheaper seams

A second conflict engine would drift from pretalx's editor and availability
semantics. A browser-only warning could be bypassed with a POST or direct
service call. A post-release signal cannot prevent publication because it fires
after `freeze_schedule()` commits the version.

## How the choice was made

The installed warning implementation was executed against deliberately
colliding `TalkSlot` rows. A `pre_save` guard on `Schedule` was then verified to
run during pretalx's freeze transaction before the versioned schedule is saved.
The heuristic is “reuse detection, enforce policy at the earliest server-side
write boundary.”

## Decision, costs, and abandoned attempts

Classify upstream warnings into blocking room/speaker categories and advisory
categories, and reject versioning in the plugin-enabled event's schedule
`pre_save`. Keep `release_schedule()` as the explicit plugin service wrapper
around pretalx `freeze_schedule()`. The cost is a signal-level coupling to
pretalx's save order; if freeze stops saving `Schedule.version` before the
database save, the guard must move.

## Upgrade, rollback, and security impact

Re-audit warning dictionaries, `freeze_schedule()` transaction order, and
`schedule_release` before upgrading. Public agenda/widget/export views use
pretalx's released `current_schedule`; WIP remains organiser-only.

## Automated proof

`tests/test_m3.py::test_blocking_schedule_warning_prevents_release` and
`tests/test_m2.py::test_dashboard_conflict_count_reconciles_to_rows`.
