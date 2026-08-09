# Decision: Plugin domain executor

## Question

How can plugin-owned lifecycle mutations share locking, authorization,
idempotency, transition validation, and post-commit effects?

## Goal and architecture depth

The goal is one reliable lifecycle path for every plugin-owned mutation, so a
judge sees the same behavior whether a speaker form, organiser action, seed
command, or future job performs it. This is the plugin's internal domain spine,
below the fork/plugin architecture but above individual controllers.

## Baseline and evidence

Pinned pretalx owns submission transitions through
`pretalx/submission/models/submission.py:Submission.accept/reject` and schedule
publication through `pretalx/schedule/services.py`, which emits
`pretalx/schedule/signals.py:schedule_release`. Those APIs are not a generic
executor for plugin-owned aggregates.

## Cheaper seams rejected

Direct model writes in views or jobs bypass version checks, transition logs,
receipts, and outbox effects. A signal-only design cannot provide one atomic
authorization/lock boundary for synchronous commands. Patching pretalx core
would still not govern plugin-owned rows and would create an unnecessary fork.

The abandoned first implementation mutated task status directly in
`CompleteTaskView`. It passed the visible checklist test but skipped receipts,
transition logs, and outbox events; the review fix moved it onto `execute()`.
The heuristic is “all plugin-owned state changes go through the same command,”
even when a direct save appears shorter.

## How the choice was made

The executor was tested first against replay and optimistic-version cases, then
the completion view was inspected for direct writes. The review failure was
reproduced by the missing receipt/log path and fixed by routing completion
through the same command.

## Decision and invariants

Use plugin-owned `domain.commands.execute()` with `transaction.atomic`,
`select_for_update`, event ownership, version checks, table-driven transitions,
`CommandReceipt`, `TransitionLog`, `OutboxEvent`, and `transaction.on_commit`.
Controllers and seed actions call this executor for plugin state changes.

## Upgrade, rollback, and security impact

An upgrade could change Django transaction behavior or pretalx model ownership
assumptions, but the executor's aggregate models are plugin-owned. Re-audit
pretalx submission/schedule ownership before routing any upstream state through
it. Rollback requires plugin migrations only; receipt and log data are
append-only audit records.

The cost is ceremony and a plugin-owned state machine that must be kept in sync
with the product; it does not magically govern pretalx's own submission or
schedule state. Those remain upstream domain calls.

## Automated proof

`tests/test_domain.py::test_executor_is_idempotent` and
`tests/test_onboarding_operations.py::test_completion_uses_executor_and_evidence` prove replay,
locking/version behavior, transition logs, and plugin task mutation routing.
