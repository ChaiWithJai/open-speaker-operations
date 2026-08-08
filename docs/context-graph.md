# Context graph

## North star

Win with a fully working seeded judge journey. Anything not reachable in that
journey is not complete. The protected path is:

```text
CFP → review → acceptance → onboarding → conflict-aware release
→ public output → synchronization proof
```

`context-graph.json` is the machine-readable source. Each complete P0 row maps
competition requirement → PRD acceptance row → decision record → code path →
test → seeded demo step. The `gaps` section is intentionally explicit: it
shows what is not yet demoable and the shortest path to making it so.

## Current status

| Area | Status | Judge-visible proof |
|---|---|---|
| Roles and authorization | Complete | Chair/reviewer/speaker seeded accounts |
| Review rounds and decisions | Complete | Two phases and audit timeline |
| Acceptance and onboarding | Complete | Acceptance creates ordered tasks |
| Evidence and reminders | Complete | Speaker checklist and queue dedupe |
| Conflict-aware release | Complete | Seeded WIP conflicts block release |
| Public schedule/ICS/embed | Complete | Released-only outputs |
| CFP builder | Complete | Seeded AIE form covers all P0 field types and draft/resume |
| Accelevents synchronization | Complete | Mock contract, identities, retry and reconciliation proof |

## CI contract

`python scripts/check_context_graph.py` fails if any P0 entry in
`requirements` lacks a test or seeded demo step. Explicit future gaps remain in
the separate `gaps` list so they cannot be mistaken for completed coverage.
