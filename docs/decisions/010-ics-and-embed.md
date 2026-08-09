# Decision: Versioned ICS and published embed

## Question

How can calendar clients retain identity across schedule updates and how can
an external embed show only released, accessible schedule data?

## Goal and architecture depth

The goal is publication that works outside the organiser UI: an updated talk
must update rather than duplicate in calendars, and a cross-origin embed must
be useful without exposing WIP data. This is a public-output adapter around
pretalx's agenda/widget infrastructure.

## Baseline and evidence

Pinned pretalx `2025.2.2` uses `pretalx/schedule/ical.py:get_slots_ical()` and
`TalkSlot.build_ical()` in `pretalx/schedule/models/slot.py`. The upstream
implementation emits a stable UID based on event/submission code, but does not
emit `SEQUENCE` or cancellation components. Pretalx's
`pretalx/agenda/views/widget.py:widget_data()` already permits CORS and chooses
`event.current_schedule`; WIP requires organiser permission.

## Options and rejected cheaper seams

Replacing pretalx's exporter would duplicate mature formatting and timezone
logic. Adding only a template cannot change ICS components. Serving the
widget's WIP-capable endpoint directly would create an accidental publication
leak if its authorization assumptions changed.

## How the choice was made

The installed source was read and a generated calendar inspected: UID existed,
`SEQUENCE` did not. The implementation reuses `get_slots_ical()` and adds a
plugin identity/fingerprint table, sequence increments, cancellation events,
and a released-only plugin endpoint. The embed uses a small accessible
plugin-owned view keyed by `current_schedule`, while the upstream widget
behavior remains the reference.

## Decision, costs, and abandoned attempts

Use `ScheduleIcsIdentity` for stable UID, fingerprint, sequence, and
cancellation state. Use the plugin embed endpoint for a narrow released-only
contract rather than modifying upstream widget templates. The cost is one
plugin-owned calendar identity table and a second public URL; it must be
reconciled if upstream later adds native sequence handling.

## Upgrade, rollback, and security impact

Re-audit `get_slots_ical()`, `TalkSlot.build_ical()`, and
`widget_data()` before upgrading. No WIP schedule is queried by the plugin
public endpoints; CORS is intentionally limited to the read-only output.

## Automated proof

`tests/test_schedule_publication.py::test_released_ics_has_stable_uid_and_incrementing_sequence`
and `test_published_embed_is_cross_origin_readable_and_released_only`.
