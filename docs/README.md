# Documentation index

Each active long-form document has one purpose. Superseded plans live in
`archive/`; investigation logs are evidence, not current instructions.

## Authoritative active documents

| Document | Declared purpose |
| --- | --- |
| `../README.md` | Product goal, supported quick start, and demo journey |
| `../CONTRIBUTING.md` | Contributor setup, validation, migrations, and PR contract |
| `architecture.md` | Current runtime boundaries and capability ownership |
| `repository-map.md` | Where code, tests, deployment files, tools, and artifacts belong |
| `context-graph.md` / `context-graph.json` | Requirement-to-code/test traceability and its machine-readable gate |
| `buzz-demo-map.md` | Per-judged-row Buzz demo contract: coordination in Buzz, authority and links in SpeakerOps |
| `opencode-harness.md` | Canonical Buzz agent runtime: OpenCode as the harness, uniform machine setup, and the adoption rationale |
| `buzz-workflows.md` | Verified workflow behavior, trigger filter syntax, and known upstream limitations |
| `product-standard-buzz-workflows.md` | Product standard: every workflow answers from the system of record with a link to the view |
| `cfp-guide.md` | Public/operator explanation of the configured CFP |
| `seed.md` | Deterministic demo data contract |
| `digitalocean.md` | Production deployment and host operations |
| `operator-handoff.md` | Backup, restore, rollback, and credential handoff |
| `presenter-runbook.md` | Local competition rehearsal procedure |
| `sbek-evaluator-runbook.md` | Authenticated external judge preflight and evidence gates |
| `local-worker-system.md` | Historical local worker design and implementation notes |
| `performance-audit.md` | Dated performance evidence and measurement method |
| `demo-hci-review.md` | Dated HCI audit evidence; not a product specification |
| `pr14-checklist-evaluation.md` | Dated PR #14 acceptance evaluation |

## Supporting collections

- `decisions/`: immutable architecture decision records. New decisions receive
  the next sequence number; existing decisions are not silently rewritten.
- `evidence/`: pinned external contract evidence with source context.
- `log/`: historical investigation/handoff logs; useful evidence, never the
  current operating procedure.
- `archive/`: superseded product/RFC/implementation plans retained only for
  provenance. Active work must not link to them as current authority.
- `issue-41-gap-closure.json`: machine-readable historical-backfill gap
  disposition evidence, interpreted through the conference-data contract.

Machine-generated audit output, traces, screenshots, profiles, database dumps,
and browser state do not belong in `docs/`; keep them in ignored local output
directories or the controlling task's external artifact directory.
