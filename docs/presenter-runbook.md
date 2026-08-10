# Competition presenter runbook

## Outcome and boundary

Open Speaker Operations is AIE's owned conference memory and speaker-program control plane. It replaces the Sessionboard subset used for proposals, human curation, speaker readiness, release safety, public outputs, and Accelevents synchronization. It does not replace registration, ticketing, exhibitors, attendee engagement, or onsite delivery.

The buyer story is: **AIE keeps its programming taste, operational history, and exception-handling loop in a system it owns.** Conference memory informs people; it never makes acceptance decisions. Every consequential transition remains explicit, attributable, and recoverable.

## Accounts and environment

- Local web: `http://127.0.0.1:38001`
- Local mock connector: `http://127.0.0.1:39001`
- Event: `speakerops-demo`
- Password for every account: `speakerops-demo`
- Speaker: `speaker@example.org`
- Second speaker: `speaker2@example.org`
- Reviewer: `reviewer@example.org`
- Chair: `chair@example.org`
- Administrator: `admin@example.org`

Never operate another Compose project for this rehearsal. All lifecycle commands use project `speakerops-hci` and explicit bindings.

## Preflight and automated proof

Run the exact real-browser rehearsal three times at desktop and mobile widths:

```sh
SPEAKEROPS_REHEARSAL_ARTIFACTS=/absolute/private/evidence/directory \
  tools/rehearse-judge-journey.sh --runs 3
```

The command refuses a non-local URL, operates only `speakerops-hci`, restarts only its mock connector, reruns the deterministic seed before every viewport, and writes screenshots, Playwright traces, per-run JSON, console/network findings, structural accessibility checks, and axe results outside the repository. Success requires every `report.json` and `summary.json` to contain `"ok": true`.

For a quick presenter preflight:

```sh
tools/rehearse-judge-journey.sh --runs 1 --desktop-only
```

Do not use the quick preflight as the three-run acceptance artifact.

## Seven-stage narration (8–10 minutes)

1. **Public entry — 45 seconds.** Start at the event root. Open the named **Released schedule** link, switch List/Day/Week, filter by track and room, and open one session's native detail page. Then open the CFP and linked writing guide. Say: “The released program is easy to discover and explore, while the form encodes AIE's formats, tracks, level, topics, and commercial-context policy. Previous talks become practical speaker education instead of a forgotten spreadsheet.”
2. **Speaker — 75 seconds.** Log in as the speaker. Show role landing, the prioritized checklist, completed/waived evidence, the draft/in-review/accepted proposal states, and the historical CFP date boundary. Say: “A speaker always knows the next action and can return without organizer coaching.”
3. **Reviewer — 75 seconds.** Log in as the reviewer, score the assigned proposal, add a recommendation, and wait for Saved feedback. Show related conference-memory sessions. Say: “The complete historical backfill gives reviewers precedent and continuity, but history is evidence, not a score; reviewers retain judgment.”
4. **Chair — 75 seconds.** Log in as chair. Show the recommended next action, reconciled counts, conference memory, and explicit acceptance waves. State the history coverage: 13 event series, 199 editions, 18,432 talks, 20,238 speaker credits, 20,174 edition-scoped source identities, and 13,376 provisional person clusters, with source gaps recorded explicitly. Say: “Only the chair applies acceptance or rejection; the audit records who and when. AIE's programming memory survives staff turnover without automating taste.”
5. **Agenda/release — 75 seconds.** Show the two deliberately unpublished WIP conflicts, their named resources, direct Resolve links, and the disabled release action. Open one native schedule editor. Say: “Publication is server-authoritative; the public schedule never inherits conflict fixtures.”
6. **Synchronization — 75 seconds.** Show create/update/no-op/failure evidence and retry only the failed record. Say: “Every downstream effect is previewed and retried without duplicating successful work.”
7. **Released outputs — 60 seconds.** Return to the named **Released schedule** link on the event root. Show List/Day/Week, track and room filtering, native session-detail continuity, gallery, embed, and ICS. Say: “These outputs reconcile to the released revision; mutable WIP stays private, and attendees can move from discovery to full session detail without a dead end.”

Close with: “The output of this event becomes evidence for the next one. That compounding, human-owned loop is what AIE is buying.”

## Expected outcomes

- Speaker lands on Speaker tasks; reviewer lands on Review queue; chair lands on Operations.
- Reviewer autosave reaches “All changes saved”.
- Agenda shows blocking room/speaker conflicts, direct Resolve actions, and a disabled release button.
- Sync history visibly contains create, update, no-op, failed, and recovered states.
- Public schedule contains the curated 12-session program; gallery, embed, and ICS are available.
- Conference memory reports the full known backfill with 13 catalogs, 199 editions, 18,432 talks, 20,238 speaker credits, 20,174 source identities, 13,376 provisional person clusters, and explicit source-gap records rather than invented sessions.
- Browser console errors, request failures, first-party HTTP errors, unnamed controls, horizontal overflow, duplicate/missing `main`, and critical axe violations are zero.

## Fallback package

If the local browser fails, do not improvise database changes.

1. Open the most recent private `summary.json` and confirm which stage failed.
2. Use the matching stage screenshot and Playwright trace from that run.
3. Show production `https://loop.dharmicdata.org` only for deployed-main continuity; say clearly that `demo-hci` changes are local.
4. Use the benchmark report and its private screenshots as supporting evidence, never as a substitute for a failed required gate.
5. If the mock connector alone failed, restart only `speakerops-hci`'s `mock-accelevents`, reseed, and rerun the full harness.

Abort rather than claim success when `summary.json` is absent, any run has `ok: false`, the seed command fails, a role cannot land correctly, or accessibility/network/console assertions fail.

## After the presentation

- Keep screenshots and traces private unless the owner approves attachment to GitHub.
- Rerun `speakerops_seed` to restore the deterministic demo baseline if manual exploration changed state.
- Record the exact commit, image, artifact path, start/end time, and presenter in the approved issue comment.
