# Buzz demo map: one demo per judged row

**Status: design contract. Every flow below is `planned`; none is
implemented.** This document specifies demonstrations — it is not evidence of
AI capability, and nothing here may be presented to a buyer as a working
feature until the walking skeleton (relay + model + one typed read) exists.

This is the demo contract for issues #66/#67: every judged row of the
SessionBoard benchmark gets a Buzz demonstration proving the same shape — the
real work is isolated out of the web UI into a Slack-like room where humans and
agents coordinate, while SpeakerOps stays the system of record and every
message carries an addressable, permission-aware link that lets a human
confirm, drill deeper, or continue in the actual web UI.

`pretalx_speakerops/canonical_links.py` is the machine-checked
registry behind this map. It distinguishes shareable GET **links** from
POST-only **commands** (links navigate, commands mutate — a command route is
never handed out as a link), and grades every anchor's exactness:
exact-record, filtered-collection, aggregate-screen, or public-output.
`tests/test_buzz_resource_registry.py` fails when a named route or judged row
drifts, and exercises the seeded role matrix over HTTP for a defined subset:
organiser consoles (chair 200; reviewer and speaker 404; anonymous redirected
to login), reviewer and speaker surfaces, public surfaces, one valid
exact-record access per self-scoped and reviewer-scoped route, stale/deleted
IDs failing safely with 404, every command endpoint refusing GET, and the
`go/` resolver authorizing before it redirects (exactly one redirect, never
to a command route). Not yet tested — deferred until the resolver grows
record-level resources: cross-event identifier rejection, revoked users, and
destination-content-matches-record assertions.

Delivery order follows the walking skeleton, not this document's breadth:
first `release_readiness` end-to-end (row 5), then content readiness (row 6),
then the reminder preview/confirm/receipt write (row 8). The remaining rows
extend a proven grammar; they are not built first.

## The demo grammar

Every row's demo is the same five beats, so a buyer learns the pattern once:

1. **Signal.** A SpeakerOps outbox event or scheduled brief posts into the
   event channel; exceptions open a thread each.
2. **Evidence.** The agent answers with counts that reconcile to named
   records, using typed read tools — never database access.
3. **Link.** Every record named carries a canonical SpeakerOps link (the #67
   `go/{resource}/{opaque-id}` resolver, one redirect maximum, authorization
   decided server-side by `auth.py`).
4. **Act.** Rich or state-changing work happens in the web UI: the link lands
   on the exact object, the human decides there.
5. **Receipt.** The resulting `CommandReceipt`/`TransitionLog` is mirrored
   back into the originating thread with its correlation ID.

Links navigate; typed commands mutate; receipts cross the bridge; secrets
never do.

The bounded action routes make that separation concrete. The authenticated
GET routes `speakerops_speaker_nudge_preview` and
`speakerops_sync_recovery_preview` display the current targets for a unique
correlation without mutating them. Their forms POST only after explicit human
confirmation to `speakerops_speaker_nudge_confirm` and
`speakerops_sync_recovery_confirm`. Sanitized outcomes remain readable at
`speakerops_workflow_action_receipts` and the exact
`speakerops_workflow_action_receipt` record.

## Row demos

### 1. Custom submission forms (High)

- **Buyer moment:** "Is my CFP actually configured the way I think it is?"
- **Demo script:** Chair asks `@speakerops how is the CFP set up?` → agent
  summarizes fields, required/optional flags, submission limits, deadline,
  and the `ConditionalQuestionRule` routing table → links to the CFP routing
  console and the public CFP guide → chair adjusts a rule in the web UI →
  thread receives the change confirmation.
- **Reads:** CFP configuration, routing rules, deadline state.
- **Links:** `speakerops_cfp_routing` (orga console), `speakerops_cfp_guide`
  (public guide — what a submitter will actually see).
- **Writes via Buzz:** none in v1; form construction is explicitly web-UI
  work (#66 "all flows" interpretation).

### 2. Speaker self-service portal (High)

- **Buyer moment:** "Who owes what, and can the speaker fix it in one click?"
- **Demo script:** Morning brief posts deadline-ranked `OnboardingTask`
  exceptions, one thread per speaker → coordinator opens the speaker's
  profile/checklist from the thread; the speaker's own DM gets only their
  checklist link → speaker uploads the headshot in the portal → thread shows
  the task's transition receipt and the new `TaskEvidence` version.
- **Reads:** onboarding tasks by state/deadline, evidence versions, profile
  completeness (`SpeakerOperationsProfile`).
- **Links:** `speakerops_checklist`, `speakerops_speaker_profile`, and the
  speaker's own `speakerops_submission_presenters` (exact, self-scoped by
  code); task admin drilldown for organisers. **Gap:** no per-task detail
  GET — tasks resolve to checklist anchors today; the resolver needs an
  `onboarding-task` resource.
- **Writes via Buzz:** reminder send after preview (see row 7); task state
  changes stay on the existing `domain/commands.py` receipts.

### 3. Submission & abstract management (High)

- **Buyer moment:** "Show me the queue without making me live in a table."
- **Demo script:** `@speakerops what's undecided in track AI?` → agent
  returns the filtered set with per-submission links and anomaly notes
  (withdrawn-but-scheduled, missing presenters) → chair opens one submission,
  accepts it in the web UI → thread receives the decision receipt.
- **Reads:** submission funnel by state/track, presenter roles
  (`SubmissionPresenterRole`), anomalies.
- **Links:** `speakerops_abstract_management` (console) only. **Gap:** no
  organiser-facing exact submission GET exists anywhere in the plugin
  (`speakerops_submission_presenters` is self-scoped to the submission's own
  presenters and 404s for a chair) — the resolver owes a real `submission`
  resource before this row can claim a record-level link.
- **Writes via Buzz:** none; accept/decline is row 4/decision territory.

### 4. Evaluation & review workflows (High)

- **Buyer moment:** "Where is review stalled and who do I nudge?"
- **Demo script:** Agent posts round progress (`EvaluationRound`,
  `RoundReviewAssignment` by state) → reviewer lead opens the two stalled
  assignments directly from the thread — these links are already fully
  addressable — → nudges via row-7 reminder preview → decisions wave
  (`AcceptanceWave`, `ProgramDecision`) is previewed in-thread, confirmed in
  the web UI, and the receipt lands back in the thread.
- **Reads:** round/pool progress, overdue assignments, score distributions.
- **Links:** `speakerops_review` (per-assignment, pk),
  `speakerops_round_review` (per-round-assignment), the queues
  (`speakerops_review_queue`, `speakerops_round_review_queue`), and
  `speakerops_program_decisions` for the wave confirmation. This row is the
  reference demo: detail routes already exist.
- **Writes via Buzz:** decision wave preview → confirm → receipt (the
  existing `program/decisions.py` audit path).

### 5. Agenda & schedule building (High)

- **Buyer moment:** "What blocks release, exactly?"
- **Demo script:** `@speakerops can we release?` → agent lists named
  conflicts from the conflict detector and unapproved content, each with an
  owner and a link → chair opens the conflicts drilldown, fixes the slot in
  the visual agenda builder (explicitly web-UI work) → release is confirmed
  in the web UI → thread receives the release receipt and the public links.
- **Reads:** conflict list, release-blocker rollup, schedule version state.
- **Links:** `speakerops_agenda` (builder/release), `speakerops_drilldown`
  with `kind=conflicts` (also `tasks`, `content`, `undecided`,
  `missing-assets` for other briefs). **Gap:** per-conflict/slot resource for
  thread-per-exception linking.
- **Writes via Buzz:** release confirmation only via the authoritative web
  confirmation; never from a reaction.

### 6. Content & production (the benchmark's weakest category — first-class)

- **Buyer moment:** "Which latest decks are AV-ready, and who owns what's
  not?" (the PRD's content/production job; previously the weakest substantive
  benchmark category).
- **Demo script:** Daily content brief threads the not-AV-ready set: each
  session with its latest `TaskEvidence` version, stale-vs-approved state,
  requested-change owner, and a link into the content console
  (`speakerops_content_operations`) → organiser reviews the exact evidence
  file (`speakerops_evidence_download`, version-aware) → requested changes
  and AV approval execute as receipted commands
  (`speakerops_session_content_edit`, `speakerops_speaker_content_edit`,
  `speakerops_session_publication_approval` — POST-only; never links) →
  when the set is clean, the agent posts the production handoff: the
  approved latest-files ZIP (`speakerops_latest_evidence_zip`).
- **Reads:** latest/stale/missing versions, approval blockers,
  requested-change ownership, upload failures needing recovery.
- **Links:** content console, exact evidence-file download, AV bundle.
  **Gap:** per-session/speaker content GET detail is a console fragment —
  the resolver owes a `content-record` resource.
- **Writes via Buzz:** none in v1; uploads stay in the protected SpeakerOps
  path, edits/approvals confirm in the web UI with receipts to the thread.

### 7. Embeds & web publishing (High)

- **Buyer moment:** "What will the public actually see when I hit publish?"
- **Demo script:** Before release the agent posts the would-be-public set
  with preview links → after release it posts the live embed, gallery,
  per-speaker/per-session public pages, and ICS links into the channel —
  instantly shareable with marketing without anyone hunting navigation.
- **Reads:** publication warnings, published/withheld sets.
- **Links:** `speakerops_embed_builder` (orga), `speakerops_embed`,
  `speakerops_gallery`, `speakerops_public_widget`,
  `speakerops_public_speaker`/`speakerops_public_session` (per-record public
  pages by code), `speakerops_ics`/`speakerops_selected_ics`.
- **Writes via Buzz:** none; publication approval is row 5's receipt flow.

### 8. Automated communication (Medium)

- **Buyer moment:** "Nudge everyone who's late — but show me first."
- **Demo script:** `@speakerops draft reminders for overdue tasks` → agent
  posts the exact recipient list, template, and per-speaker task links as a
  preview bound to actor + expiry → coordinator confirms → send executes
  idempotently → thread receives per-recipient `ReminderReceipt` summary and
  the `SpeakerCommunicationLog` trail link.
- **Reads:** overdue sets, prior sends (noise budget: don't re-nudge).
- **Links:** the overdue-task drilldown (`speakerops_drilldown`,
  `kind=tasks`) is the shareable evidence surface; `speakerops_reminders` is
  the POST-only confirmed-send command and is never handed out as a link.
  **Gap:** receipt/log detail resource for "what did we send this speaker?"
  threads.
- **Writes via Buzz:** the flagship bounded write — preview → confirm →
  idempotent send → receipt. This is handoff step 5's designated candidate.

### 9. System performance & UX (Medium, differentiator)

- **Buyer moment:** "Is it fast, and is it up?" (the anti-SessionBoard row)
- **Demo script:** Scheduled brief posts `status.json` health plus the query
  budgets from `test_performance.py` CI evidence; the demo states the
  structural point out loud: coordination chatter lives in Buzz, so the web
  UI stays a fast, focused work surface — and the whole judged lifecycle
  keeps working with Buzz switched off (the isolation guard test proves the
  runtime has zero Buzz coupling).
- **Reads/links:** `speakerops_status` (machine-readable),
  `speakerops_dashboard`.
- **Writes via Buzz:** none.

### 10. Integrations & data handling (Low/Bonus — but buyers pay for it)

- **Buyer moment:** "Why is Accelevents out of sync, and is it safe to retry?"
- **Demo script:** Outbox event posts a failed-sync thread naming the
  `SyncItem`, last `SyncAttempt` error, and external identity → operator
  opens the exact run from the thread → agent posts a selective-retry
  preview (idempotent by design, ADR 011) → operator confirms → thread
  receives the reconciliation receipt. CSV lanes are linked the same way:
  import via `speakerops_speaker_import`, exports from the abstract/speaker/
  CRM consoles, so "get my data in/out" is one click from the room.
- **Reads:** run/item/attempt state, fingerprint diffs (preview).
- **Links:** `speakerops_sync_console`, `speakerops_speaker_import`.
  `speakerops_sync_run` (per-run, pk) and `speakerops_sync_preview` are
  POST-only commands — the idempotent retry, never a shareable link.
  **Gap:** sync-run/sync-item GET detail for thread-per-exception links.
- **Writes via Buzz:** selective retry via preview/confirm on the existing
  receipt pattern.

### 11. CRM / speaker relationships (beyond the matrix — buyers buy it)

- **Buyer moment:** "Who spoke for us before, who's in the pipeline for next
  year, and what did we last say to them?"
- **Demo script:** `@speakerops who covered LLM evals at past editions?` →
  agent answers from conference memory with citations — `HistoricalTalk`,
  `HistoricalSpeakerCredit`, `SpeakerMemoryProfile` — never vibes → each
  name links to the conference-speaker detail page → chair asks for pipeline
  state → agent reads `CRMPipelineCard`/`CRMOutreachLog` and links the CRM
  directory → outreach itself is logged through the CRM console.
- **Reads:** historical talks/credits, memory profiles, pipeline cards,
  outreach logs, segments.
- **Links:** `speakerops_conference_memory`,
  `speakerops_conference_speaker` (per-speaker, pk — already addressable),
  `speakerops_crm_org` (organiser-wide) / `speakerops_crm`. **Gap:**
  per-contact/per-card resource. Sponsor/exhibitor objects do not exist in
  SpeakerOps; a sponsor demo would be honest vaporware and stays out until a
  real model exists.
- **Writes via Buzz:** none in v1; outreach logging is a later bounded-write
  candidate.
- **Coverage rule:** CRM is beyond the judging matrix; it never counts toward
  core benchmark coverage and is built only after the core walking skeleton
  works.

## Resolver gaps this map creates

The rows above need these `go/` resources beyond routes that exist today:
`onboarding-task`, `submission`, `schedule-conflict`, `content-record`,
`communication-receipt`, `sync-item` (with a sync-run GET detail),
`crm-contact`. That list is the concrete input to the #67 "canonical resource
types" checklist item; the registry grades each affected anchor
`aggregate-screen` or `filtered-collection` until its record-level GET route
lands.

## What each demo must prove (acceptance)

- Zero writes from links; every mutation shows a receipt in-thread.
- Every count reconciles to named, linked records (#66 groundedness metric).
- Role isolation holds: the speaker DM never links organizer surfaces;
  reviewer links 404 safely for non-reviewers.
- The full judged lifecycle passes with the Buzz stack stopped.
