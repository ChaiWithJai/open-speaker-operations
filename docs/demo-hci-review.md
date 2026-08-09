# Demo HCI review and acceptance gate

This review combines seven expert lenses: interaction design, business-system design,
visual/emotional design, inclusive design, information architecture and content, competition-demo
storytelling, and systems/performance synthesis. Scores below are expert heuristics, not user-study
results.

## Product story

Speaker Operations turns the fragile weeks between acceptance and showtime into a controlled
readiness-to-publish system. Every human sees a next action, unsafe publication is prevented, and
downstream synchronization is previewable and recoverable.

## Baseline diagnosis

The original mechanics were credible, but the demo read as disconnected functional screens:

- generated titles, overnight sessions, and event dates that did not reconcile;
- equal-weight dashboard counts instead of a recommended next action;
- conflict, task, decision, and sync reports that did not lead to corrective work;
- a dashboard sync action that returned raw JSON;
- a reminder action whose implementation included every unresolved task despite saying “due”;
- generic evidence requirements and ambiguous repeated upload actions;
- duplicate `main` landmarks, unnamed organizer navigation, weak focus treatment, and static gallery
  cards in the keyboard tab order;
- non-serialized reviewer autosave requests;
- internal connector URLs and numeric record IDs on the judged surface.

Initial visual/emotional heuristic scores were: narrative credibility 3/10, decision clarity 4/10,
cross-role coherence 4/10, feedback/trust 5/10, responsive task fitness 4/10, emotional legibility
4/10, and demo-stage polish 3/10.

## Changes made

- Curated a deterministic 12-session, three-day program with plausible titles, speakers, daytime
  slots, and two named rooms.
- Reduced the command center to one recommended next action and linked each urgent state to the
  corresponding work surface.
- Routed synchronization through the human preview console and exposed planned changes by name.
- Limited reminders to overdue unresolved work, displayed the recipient count, required explicit
  confirmation, used a date-scoped dedupe key, and returned in-product feedback.
- Linked conflict messages to affected rows and the native scheduler; converted the agenda to
  labeled mobile cards with one time format.
- Replaced generic task evidence copy with visible file types, limits, unique labels, `accept`
  constraints, and task-specific actions.
- Serialized reviewer autosaves and added an explicit timestamped saved state.
- Removed nested main landmarks, restored accessible organizer navigation names on plugin pages,
  added high-contrast focus styles and primary buttons, named progress, removed inert gallery tab
  stops, and honored reduced motion.
- Made the seed a true reset: one baseline synchronization run, one recoverable failure, 12 visible
  published sessions, and consistent task definitions on every start.

## Measured verification

- Full test suite: 36 passed.
- Ruff format and lint: passed.
- Isolated Docker project `speakerops-hci`: web, worker, PostgreSQL, Redis, and mock connector
  running; web and dependencies healthy.
- Public schedule: 12 cards, two rooms, zero console errors/warnings, 76 ms response start on the
  measured local navigation.
- Chair dashboard: one `main`, all sidebar links named, no raw preview form, 170 ms response start
  on the measured authenticated local navigation.
- Mobile agenda at 390×844: 12 rows, two blockers, zero document or table overflow.
- Mobile gallery: 11 speaker cards, zero inert focusable cards, zero horizontal overflow.
- Reviewer: credible abstract, one `main`, timestamped save state, no console errors/warnings after
  scoring.
- Mobile speaker checklist: one `main`, zero horizontal overflow, explicit 5/20/10 MB evidence
  criteria and unique upload actions.

These timings are local navigation/resource timings. Chrome DevTools performance tracing was not
available in the environment, so this review does not claim LCP, INP, or CLS.

## Three-minute hero path

1. Open the command center: explain that two conflicts prevent an unsafe release, one speaker task
   is overdue, and one downstream record needs recovery.
2. Show Maya Chen’s checklist: exact evidence, one waived task, and one overdue biography.
3. Score the single assigned proposal: weighted rubric, recommendation, timestamped autosave.
4. Return to the command center and open the blocking conflicts.
5. Show the affected sessions and the disabled publish action; use “Open schedule editor.”
6. Show the released public schedule: only the coherent 12-session revision is visible.
7. Open synchronization: review named creates/updates/no-ops, then show retry-only-failed recovery.

Close with: “One accountable flow, three human roles, no unsafe release, no duplicate resend, and
infrastructure the organizer owns.”

## Demo acceptance measures

- A first-time viewer can name the user, problem, protected outcome, and one differentiator after
  30 seconds.
- The hero path completes in at most three minutes, 12 deliberate clicks, and one facilitator
  prompt.
- Every alert reaches either the corrective action or its owner within two clicks.
- Every consequential action states scope before execution and result afterward.
- Normal demo navigation shows meaningful content within 500 ms p95; autosave confirms within one
  second under the target deployment.
- Mobile at 375–390 px has no horizontal-table dependency and all primary targets are at least
  44 px.
- A reset command restores accounts, tasks, conflicts, published output, and one sync failure.

## Remaining release risks

- Pretalx’s login pages emit two upstream `onReady is not defined` console errors. Pre-authenticate
  the three role tabs for the competition demo and track the host asset issue separately.
- The native Pretalx mobile header still wraps “View event” and “Log out.” The custom task surfaces
  no longer overflow, but a host-theme override or upstream template fix is still warranted.
- The command center’s six metric cards are clearer but still consume more vertical space than the
  ideal workflow rail. A later iteration should group them into Review → Speakers → Schedule →
  Publish → Synchronize.
- Conflict resolution now reaches the scheduler, but a sub-60-second user test is still required;
  this audit did not simulate five real operators.
