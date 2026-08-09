# Decision: Role authorization

## Question

Can organiser, chair, reviewer, and speaker access use pretalx's existing
event-scoped authorization without a parallel role system?

## Goal and architecture depth

The goal is a judgeable role journey with server-side denial, not merely role
labels in seed data. This is an application-boundary decision: it maps product
roles onto pretalx's existing permission model without changing upstream auth.

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

The initial seed created chair and reviewer users without team membership; only
the administrator could actually reach organiser pages. That failed the role
journey and was corrected by event-limited teams and explicit surface checks.
The heuristic is to test each role's allowed and denied URLs, not infer access
from account names.

## How the choice was made

Installed `Team` fields and permission checks were inspected, then the seed was
rerun with chair/reviewer memberships and a client matrix asserted both 200 and
404 outcomes. Reviewer assignment was verified through pretalx `Review.user`.

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

The cost is dependence on pretalx permission codenames and team semantics; a
permission rename requires a coordinated plugin update.

## Automated proof

`tests/test_onboarding_operations.py::test_roles_are_scoped_to_surfaces` proves allowed and denied
organiser, reviewer, preview, reminder, and speaker access.
