# Architecture

This document is the authoritative map of the current Speaker Operations
implementation. Decision records in `docs/decisions/` explain individual
choices; they do not replace this map.

## Runtime boundary

Speaker Operations is an installed Pretalx plugin. Pretalx remains responsible
for users, events, submissions, reviews, schedules, and public talk pages. The
plugin adds the operational workflow around those records. PostgreSQL is the
authority for application state, Redis is cache and queue infrastructure, and
the Accelevents adapter is an explicitly bounded external integration.

The permitted dependency direction is:

```text
HTTP view / signal receiver
          |
          v
workflow service / domain command ---> integration adapter
          |
          v
model and local invariant ---> audit log / outbox
```

- Views own authentication, authorization, request parsing, and response
  rendering. They do not hide business state transitions in GET requests.
- Services and domain commands own workflows, transactions, idempotency, and
  state transitions.
- Models own persistence constraints and local invariants.
- Integrations own remote payloads, authentication contracts, retries, and
  external identities.
- Signal receivers observe Pretalx lifecycle events and defer side effects with
  `transaction.on_commit`.

## Capability map

| Capability | HTTP / entry surface | Workflow / policy | Persistence | Tests |
| --- | --- | --- | --- | --- |
| CFP and routing | `cfp.py`, `cfp_forms.py`, `urls.py` | CFP validation and routing rules | Pretalx questions/answers plus plugin routing models | `test_cfp*.py`, `test_aie_cfp.py` |
| Review and decisions | `views.py`, reviewer/program templates | `program/reviews.py`, `program/decisions.py` | review recommendations, decision audit, Pretalx review models | `test_program_decisions.py`, `test_screens.py` |
| Speaker onboarding | checklist views/templates | `onboarding/services.py`, `domain/` | onboarding tasks, evidence versions, transition logs | `test_onboarding_operations.py`, `test_uploads.py` |
| Agenda and release | agenda views/templates | `program/policy.py`, `program/auto_schedule.py`, `program/calendar.py` | Pretalx schedules/slots, release audit, ICS identity | `test_schedule_publication.py`, `test_conflict_resolution.py` |
| Conference memory | memory views/templates | `conference_memory.py`, `history_coverage.py` | historical talks/speakers/credits and AIE-owned CRM overlay | `test_conference_memory.py`, `test_history_coverage.py` |
| Synchronization | sync views/templates | `integrations/accelevents.py`, `integrations/sync.py` | connections, runs, items, attempts, external identities | `test_accelevents_sync.py` |
| Operations | status view and management commands | `deploy/`, `tools/` | audit/outbox plus backup artifacts outside Git | `test_operations_contract.py`, `test_performance.py` |

`views.py` and `models.py` remain compatibility aggregation points today. New
capabilities must be introduced in a named capability module and imported from
those files only where Pretalx or Django registration requires it. Their
eventual split is a structural migration, not permission to change behavior.

## Process and deployment boundaries

- `web` serves Pretalx and performs migrations/optional deterministic seeding.
- `worker` executes Celery work and never runs migrations or seeding.
- `postgres` is durable authority; `redis` is disposable infrastructure.
- `mock-accelevents` implements only the captured local connector contract.
- Root `docker-compose.yml` is the single canonical Compose entry point for
  local, CI, recovery, and production topology.
- `deploy/` contains production/recovery artifacts. `tools/` contains
  contributor validation and rehearsal tools and is never copied into the
  runtime image.

## Invariants for changes

1. Every event-owned query is explicitly scoped to its event.
2. Authorization is enforced on the server; hiding a control is not a policy.
3. State-changing POSTs are atomic and idempotent where retry is possible.
4. GET requests do not write configuration or workflow state.
5. External writes are previewed/audited and are safe to retry.
6. Source conference-history fields retain provenance; AIE-owned annotations
   never overwrite source evidence.
7. Migrations are additive and reversible when Django can express a safe
   reverse operation. Destructive data migrations require an ADR and recovery
   proof.

