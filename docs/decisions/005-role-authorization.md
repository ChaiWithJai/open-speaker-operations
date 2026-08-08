# Decision: Role authorization

## Question

Can organiser, chair, reviewer, and speaker access use pretalx's existing
event-scoped authorization without a parallel role system?

## Baseline and evidence

Pinned pretalx `2025.2.2` implements `pretalx.event.models.organiser.Team` with
`members`, `limit_events`, `can_change_submissions`,
`can_change_event_settings`, and `is_reviewer`. Pretalx permission rules expose
event-scoped checks such as `submission.orga_list_submission` and
`submission.orga_update_submission`.

## Cheaper seams rejected

Configuration cannot create event-limited membership. A plugin role table would
duplicate team membership, event limits, and permission evaluation and could
drift from pretalx's review rules. URL-only checks would be bypassable by direct
requests.

## Decision and invariants

Seed real pretalx teams and memberships. SpeakerOps checks pretalx permissions
for organiser/reviewer routes and independently checks speaker membership for
speaker routes. Reviewers are filtered to proposals assigned through their
pretalx `Review.user` rows.

## Upgrade, rollback, and security impact

An upgrade could rename team flags or permission codenames. Re-audit `Team`,
the submission rules, and the named codenames before upgrading. No parallel
role migration is needed; removing the plugin leaves team data usable by
pretalx.

## Automated proof

`tests/test_m2.py::test_roles_are_scoped_to_surfaces` proves allowed and denied
organiser, reviewer, preview, reminder, and speaker access.
