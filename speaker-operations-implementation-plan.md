# Speaker Operations Implementation Plan

| Field | Value |
|---|---|
| Status | Final execution baseline |
| Owner | Jai Bhagat |
| Last updated | 2026-08-08 |
| Deadline | 2026-08-12 22:00 PT |
| Product decision | pretalx-first; Rails 8 only if derivatives are prohibited |
| Architecture | Modular monolith on DigitalOcean, PostgreSQL/Celery/R2, Cloudflare edge |

## 1. Outcome

Deliver an open-source, deployed speaker-operations system that lets an evaluator submit a proposal, review and accept it, complete speaker onboarding, place the resulting session without hidden conflicts, publish it, and preview or execute a one-way Accelevents synchronization.

The plan optimizes for a complete, credible journey. Infrastructure bonuses and optional AI work cannot displace a broken primary workflow.

## 2. Authority and evidence

Use evidence in this order:

1. The [canonical competition brief](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/edit) is requirement truth.
2. The PRD is scope and acceptance truth.
3. The architecture RFC is technical decision truth.
4. [pretalx on DeepWiki](https://deepwiki.com/pretalx/pretalx) is the primary architecture map.
5. The pinned pretalx commit, tests, official documentation, and current license are implementation truth.
6. Local decision-evidence records explain every meaningful extension or tradeoff.

DeepWiki finds the right subsystem before code reading. Its index may lag upstream, so no method name, hook, field, dependency version, or license conclusion is accepted from DeepWiki alone.

## 3. Repository start protocol

### Gate 0 — eligibility, maximum one hour

Ask in Discord whether a disclosed, AGPL-compliant pretalx derivative satisfies “an open source clone that YOU make.” Save the answer in `docs/evidence/eligibility.md` with timestamp and permalink or screenshot.

- **Allowed or no contrary ruling within the time box:** fork pretalx and continue.
- **Explicitly prohibited:** activate the Rails 8 fallback immediately.
- **Ambiguous:** disclose the foundation prominently and continue pretalx-first unless directed otherwise. Do not build two applications.

### Fork and provenance

1. Fork `pretalx/pretalx` into the submission organization.
2. Preserve the `upstream` remote and record the full starting SHA in `UPSTREAM.md`.
3. Protect `main`; use a short-lived branch per vertical slice.
4. Preserve license/copyright/attribution notices and identify modifications as required.
5. Record the DeepWiki pages and indexed revision in `docs/evidence/deepwiki-index.md`.
6. Boot the pinned revision and run baseline tests before modification.
7. Build and deploy the unchanged image to the Droplet. Feature work begins after local and remote health checks pass.

The fallback starts from stock Rails 8 only after the gate fails and keeps the same OCI, PostgreSQL, R2, job, and integration contracts.

## 4. Extension decision procedure

For every gap, create `docs/decisions/NNN-short-name.md`:

```markdown
# Decision: <capability>
- Requirement and acceptance ID:
- Baseline behavior:
- DeepWiki pages consulted:
- Pinned source files and tests verified:
- Missing behavior:
- Alternatives considered:
- Chosen seam: configuration | plugin | signal | UI override | core patch
- Invariants affected:
- Migration and rollback:
- Security/license impact:
- Automated acceptance proof:
```

Choose the smallest correct seam: configuration first; then plugin-owned models/views/jobs/templates; then documented signals/domain hooks; core patches only when atomic enforcement or the required journey is otherwise impossible. Never infer absence from UI inspection alone—check DeepWiki, source search, models, domain services, routes, hooks, and tests.

## 5. Baseline-to-extension map

| Capability | Baseline to inspect | Likely approach | Completion proof |
|---|---|---|---|
| CFP questions/routing | Question models, form views, event/track scoping | Reuse questions; plugin-owned condition/routing AST | Seeded conditional submission routes deterministically |
| Speaker portal/assets | Person/submission models, questions, storage | Task-oriented projection over existing profile/files | Speaker completes bio, headshot, slides, and documents |
| Review rounds/scoring | Review models, phases, assignments | Configure phases; advisory AI record/job only | Two rounds preserve scores; chair decides |
| Acceptance side effects | Submission domain transition | Post-commit idempotent onboarding-plan creation | Replayed acceptance creates no duplicate tasks |
| Schedule/conflicts | [Schedule editor map](https://deepwiki.com/pretalx/pretalx/5.2-schedule-editor-interface), domain/tests | Preserve editor/warnings; add only missing views/policy | Seeded speaker, room, and availability conflicts appear |
| Mail/reminders/ICS | Mail queue/templates, schedule notifications | Snapshot audience/template; planner; stable ICS identity | Retry is safe; update does not duplicate event |
| Outstanding dashboard | New task state plus existing review state | Event-scoped aggregates with drill-down | Counts exactly match filtered rows |
| Resources/wiki | Plugin pages/templates | Versioned sanitized content and iframe allowlist | Unsafe markup rejected; published resource visible |
| Public gallery/schedule | Agenda/public APIs/widgets | Responsive embed keyed to published revision | Cross-origin fixture loads only released data |
| Accelevents | API/plugin/task patterns | Preview, adapter, item jobs, external identities | Retry does not replay successes |

## 6. Domain implementation rules

All lifecycle mutations use one domain command, transaction, lock/version check, authorization, invariant validation, state write, transition log, and outbox event. Controllers, jobs, admin actions, and APIs call the same command.

```python
@transaction.atomic
def execute(command, actor, key, expected_version=None):
    if receipt := CommandReceipt.find(command.event, key):
        return receipt.result
    aggregate = command.model.objects.select_for_update().get(pk=command.id)
    authorize(actor, command.action, aggregate)
    require_version(aggregate, expected_version)
    validate_transition(aggregate.state, command.action)
    before = aggregate.state
    command.apply(aggregate)
    aggregate.version += 1
    aggregate.save()
    TransitionLog.record(aggregate, before, aggregate.state, actor)
    OutboxEvent.record(command.event_kind, aggregate, command.payload())
    return CommandReceipt.record(command.event, key, aggregate)
```

Side effects run only after commit. Consumer receipts make mail, AI, cache invalidation, and Accelevents writes independently idempotent.

- pretalx remains owner of proposal/submission and schedule-release states.
- The extension owns onboarding task, reminder plan, AI suggestion, resource, and integration-run states.
- Existing transitions call pretalx domain services, never direct field assignment.
- New transitions are table-driven and exhaustively tested for states, actors, guards, effects, and terminal behavior.
- PostgreSQL is authoritative; R2 stores bytes; JSONB is limited to versioned rule ASTs and immutable provider snapshots; Airtable is optional and rebuildable.

## 7. Milestones and gates

### M0 — foundation proven

Deliver eligibility evidence, fork/provenance/license records, pinned build, baseline tests, seed data, an immutable image deployed through Cloudflare, health/error monitoring, backup, and rollback smoke test.

Exit: clean checkout boots, CI passes, and the unchanged upstream app is reachable over HTTPS.

### M1 — golden skeleton

Connect proposal, review, acceptance, one onboarding task, schedule placement, release, public page, and recorded Accelevents preview stub in one seeded journey.

Exit: one automated browser/API scenario crosses every boundary without console or database intervention.

### M2 — onboarding victory

Implement task templates/definitions/instances, completion evaluators, organizer dashboard, drill-downs, bulk reminders, and versioned resources.

Exit: acceptance creates one correct task plan; evidence updates task state; totals reconcile; the next speaker action is obvious; reminder replay is safe.

### M3 — program and publication victory

Complete review configuration, optional second round, warning policy, required schedule views, mobile embeds, publication boundary, and versioned ICS.

Exit: decisions are auditable; server detects seeded conflicts; only a release is public/exportable; ICS retains UID and increments sequence; embeds are responsive and accessible.

### M4 — integration victory

Implement connection, mappings, external identities, preview, run/item state machines, retries, and observability.

Exit: preview shows create/update/no-op; stale previews cannot execute; successes are not repeated; external/request IDs persist; a sandbox sync or fixture-backed contract proof passes.

### M5 — differentiation

Only after M0–M4: conditional forms/routing, AI rubric suggestions, richer views, Airtable mirror, or Cloudflare Containers proof.

AI exit: structured per-criterion output, source references, model/prompt/cost audit, stale-input invalidation, and explicit human final authority.

### M6 — submission freeze

Stop features; rehearse deployment/rollback and restore; run security, accessibility, performance, and acceptance checks; load judge data; verify credentials; record the demo; submit early. No unsafe migration enters after freeze.

## 8. CI/CD

Pull requests run formatting, static analysis, unit/domain tests, migration and permission tests, plugin compatibility tests, JavaScript tests, and the golden-path browser suite. `main` builds one `linux/amd64` image tagged by full SHA, scans it, and pushes it to the registry.

Promotion resolves the existing digest, verifies backup/database access, runs backward-compatible migrations as a release task, deploys web/worker roles, and runs smoke tests through Cloudflare. Failure rolls application code back to the prior image and data forward with a corrective migration. Cloudflare Containers may consume the same image, but its failure never removes the judge endpoint.

## 9. Test strategy

Every state machine gets transition-table, actor/event permission, guard, terminal-state, idempotency, concurrency, transition-log, outbox, retry, and replay tests. Contract tests fix redacted Accelevents fixtures. Property tests cover schedule overlaps, timezones, ICS identity, and conditional rules. Query-count budgets protect dashboards and schedules. End-to-end tests assert visible evaluator outcomes.

## 10. Dependencies and cut lines

| Dependency | Default | Cut if blocked |
|---|---|---|
| Derivative ruling | One-hour gate, then one track | Rails P0-only skeleton |
| Accelevents sandbox/schema | Request immediately; build contract concurrently | Tested preview plus credential-blocked execution |
| Email provider | Configure during M0 | Queue/log with safe test inbox |
| R2/CORS | Provision during M0 | Temporary S3-compatible store, same adapter |
| Cloudflare DNS | Configure after first deploy | Direct HTTPS origin temporarily |
| AI provider | Optional/advisory | Omit; human review remains complete |
| Airtable | Bonus projection | Omit entirely |

The protected cut line is CFP → review → acceptance → onboarding → conflict-aware release → public output → synchronization proof. Bonuses are dropped before reliability, documentation, or deployment quality.

## 11. Definition of done

A capability is done only when its acceptance row is identified; DeepWiki and pinned-source evidence is recorded; seam/tradeoff documented; authorization, event scoping, audit, error, retry, and accessibility behavior implemented; migrations/rollback are safe; CI proof passes; seed data exposes it; docs are updated; and production is verified through Cloudflare.

Submission is ready only when every P0 row is green, no critical path needs manual database changes, the judge account works, clean installation succeeds, rollback has been rehearsed, and the acceptance matrix links each requirement to live proof.

## 12. Reference index

- [Canonical competition brief](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/edit)
- [pretalx DeepWiki overview](https://deepwiki.com/pretalx/pretalx)
- [pretalx schedule editor DeepWiki](https://deepwiki.com/pretalx/pretalx/5.2-schedule-editor-interface)
- [eventyay-talk DeepWiki architecture](https://deepwiki.com/fossasia/eventyay-talk/2-core-architecture)
- [pretalx repository](https://github.com/pretalx/pretalx)
- [pretalx license](https://github.com/pretalx/pretalx/blob/main/LICENSE)
- [pretalx submission domain](https://github.com/pretalx/pretalx/blob/main/src/pretalx/submission/domain/submission.py)
- [pretalx review models](https://github.com/pretalx/pretalx/blob/main/src/pretalx/submission/models/review.py)
- [pretalx schedule release](https://github.com/pretalx/pretalx/blob/main/src/pretalx/schedule/domain/release.py)
- [frab repository](https://github.com/frab/frab)
