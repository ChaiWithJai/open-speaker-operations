# Authenticated external evaluator runbook

This runbook governs the SessionBoard Eval Kit (`sbek`) acceptance run tracked by
issue #49. Local tests, browser rehearsals, and the capability matrix are product
evidence; they do not substitute for an authenticated external judge verdict.

## Safety and identity contract

- Keep the evaluator checkout, configuration, browser auth state, run artifacts, and
  credentials outside this repository.
- Never print, commit, copy into an issue, or guess credential values. Load them only
  through the evaluator's supported environment or authenticated profile mechanism.
- Target `https://loop.dharmicdata.org/speakerops-demo/` for the acceptance run.
- Configure four distinct persona identities: organizer, reviewer, speaker, and second
  speaker. The deterministic seed provides `admin@example.org`,
  `reviewer@example.org`, `speaker@example.org`, and `speaker2@example.org`.
- Do not reuse the primary speaker for the second-speaker persona. Separate identities
  are required to prove co-author persistence and cross-speaker scoping.
- Record the deployed commit and immutable image digest before the first browser action.

## Preflight gates

Do not start the full ordered run until all of these are true:

1. Production CI, deployment, protected smoke, and the public CFP route are green.
2. `npm run typecheck`, `npm run list`, the offline browser smoke, and a production-URL
   dry run succeed in the evaluator checkout.
3. The agent and judge each complete an authenticated API call with the configured
   model identifier.
4. All four personas have either valid seeded credentials or saved browser sessions.
5. Fixture uploads are readable and the run artifact directory is private and writable.
6. One production scenario completes and receives a real evidence-cited verdict. An
   `agent_error`, authentication error, or `cannot_judge` result is not a passing preflight.

The dry run is safe to execute before authentication because it validates configuration
and rubric structure without opening a browser or making API calls:

```bash
npm run eval -- \
  --config /absolute/private/evalconfig.production.json \
  --url https://loop.dharmicdata.org/speakerops-demo/ \
  --dry-run
```

Use a single critical scenario for the authenticated pilot, then inspect its transcript,
screenshots, and judge citations before continuing. Prefer `CFP-S1`, because it exposes
navigation, organizer authentication, event selection, and form configuration failures
early. Resume the same run only when its stored state is coherent.

## Ordered acceptance run

Run the required areas in their declared order so that proposals, reviews, decisions,
sessions, and public outputs cross module boundaries without manual re-entry. Prioritize
early diagnosis in this order:

1. CFP creation and publication (`CFP-S1`).
2. Decision, notification, and accepted-talk handoff (`CFP-S4`).
3. Review rounds, pools, assignments, and reminders (`ABS-S2`).
4. Conflict-aware agenda generation and adjustment (`AIA-S1`).
5. Public widgets, itinerary, calendar, and cross-origin embed scenarios.
6. Remaining required scenarios.
7. Optional Speaker CRM scenarios backed by issue #41's conference memory.

After the browser run, complete the generated manual checklist with direct evidence.
Email delivery, calendar import, cross-origin embedding, long-lived itinerary persistence,
and live widget propagation require real external verification; product-unit tests alone
do not prove them. Finalize the run only after those results are recorded.

## Acceptance and restoration

Issue #49 remains open unless the finalized report proves every issue-level gate:

- overall score at least 70 percent and coverage at least 80 percent;
- every required `rule`, `handoff`, and `scoping` item passes;
- no required item receives `not_found`;
- all manual checks pass;
- agenda, responsive public widgets, and issue #41 conference memory are evidenced.

Archive the private report, machine-readable result, manual evidence, exact commit, image
digest, start/end time, and operator identity. Because evaluator scenarios mutate state,
restore the deterministic production seed through the approved deployment procedure and
rerun protected smoke before declaring the public demo ready.
