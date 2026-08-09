# Decision: Review rounds and decision audit

## Question

How should the product configure weighted review rounds while preserving
pretalx's review records and giving the chair an auditable final decision?

## Goal and architecture depth

The goal is a credible proposal-to-decision journey: criteria and scores must
be real pretalx data, a second round must not erase the first, and a reviewer
or chair must be able to reconstruct who decided what. This is a program-domain
policy layered over pretalx review configuration, not a replacement review
engine.

## Baseline and evidence

Pinned pretalx `2025.2.2` provides `ReviewPhase`, `ReviewScoreCategory`, and
`Review` in `pretalx/submission/models/review.py`. `ReviewPhase.activate()`
controls the active phase; `Review` stores `submission`, `user`, `score`,
`text`, and per-category scores. `Submission.accept()` and its
`LogMixin.log_action()` path write pretalx `ActivityLog` records.

## Options and rejected cheaper seams

Configuration through pretalx phases and score categories preserves its review
UI and permissions. A plugin review table would duplicate assignments,
weights, and score semantics. A second-round overwrite would lose first-round
evidence. A plugin-only decision log would omit pretalx's actual acceptance and
review records.

## How the choice was made

The installed models and review forms were inspected, then
`configure_review_rounds()` was made idempotent around those models. The
acceptance test creates both phases and reconstructs a combined timeline from
pretalx `ActivityLog`/`Review` plus plugin transitions. The heuristic is
“store only the delta; reconstruct the decision from the systems that own each
fact.”

## Decision, costs, and abandoned attempts

Use pretalx phases/categories/reviews and combine their records with
`decision_history()`. The cost is that pretalx `Review` has no explicit phase
foreign key, so round association remains a configured phase convention rather
than a new plugin relation. If upstream adds or changes that relation, the
helper must be revisited.

## Upgrade, rollback, and security impact

Re-audit `ReviewPhase`, `ReviewScoreCategory`, `Review`, `Submission.accept()`,
and `ActivityLog` before upgrading. Rollback removes only plugin helpers; the
pretalx review records remain authoritative.

## Automated proof

`tests/test_schedule_publication.py::test_review_configuration_has_two_rounds_and_auditable_history`.
