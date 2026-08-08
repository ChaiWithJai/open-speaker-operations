# Role authorization

## Context

pretalx teams are the installed authorization boundary for organiser access.
The relevant upstream implementation is `pretalx/event/models/organiser.py`,
`Team.members`, `Team.limit_events`, and the `can_change_submissions`,
`can_change_event_settings`, and `is_reviewer` flags.

## Decision

SpeakerOps maps organiser and chair surfaces to pretalx event/submission
permissions, maps review drill-downs to `submission.orga_list_submission`, and
keeps speaker surfaces restricted to speakers attached to submissions in the
event. Seed data creates event-limited teams instead of granting administrator
status to demo staff.

## Consequences

The plugin reuses pretalx's event-scoped permission evaluation and does not
maintain a parallel role database.
