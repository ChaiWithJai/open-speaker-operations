# Decision: Acceptance onboarding side effect

## Question

Where can acceptance create onboarding work without surviving a rolled-back
acceptance or duplicating work on a retried acceptance?

## Baseline and evidence

In pinned pretalx `2025.2.2`, `pretalx/submission/models/submission.py:
Submission.accept()` calls `_set_state()`. `_set_state()` saves the new state and
synchronously emits `pretalx/submission/signals.py:submission_state_change`
inside the caller's transaction. `pretalx/common/signals.py:EventPluginSignal`
gates the receiver on event plugin activation.

The trap is that a naive receiver creates tasks before the acceptance
transaction commits. If acceptance rolls back, those tasks remain unless the
receiver joins the transaction; if acceptance is retried, the receiver runs
again.

## Cheaper seams rejected

A `Submission.save()` override is later than the domain method and would miss
the semantic distinction between acceptance and unrelated saves. A core patch
or new post-commit upstream signal is unnecessary because the existing signal
is sufficient when paired with Django `transaction.on_commit`. Direct polling
or a job also weakens the commit boundary and adds eventual-consistency delay.

## Decision and invariants

Use the event-plugin-gated `submission_state_change` receiver, register
`ensure_acceptance_plan()` with `transaction.on_commit`, and enforce
`(submission, speaker, definition)` uniqueness on `OnboardingTask`. Pretalx
continues to own submission state; the plugin only creates its own rows after
commit.

## Upgrade, rollback, and security impact

An upgrade could move acceptance away from `Submission.accept()`, change
`_set_state()` transaction timing, rename the signal, or alter
`EventPluginSignal` activation. Re-audit all four symbols and the signal test
before upgrading. Rolling back the plugin leaves upstream submissions intact;
plugin task rows can be migrated independently.

## Automated proof

`tests/test_m1.py::test_acceptance_creates_one_task_per_speaker` verifies
repeated acceptance creates no duplicate plan. `ensure_acceptance_plan()` also
instantiates later-added definitions idempotently.
