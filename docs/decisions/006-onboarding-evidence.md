# Decision: Onboarding evidence evaluators

## Question

How can task completion represent verifiable evidence while reusing pretalx
profile, answer, and storage models?

## Goal and architecture depth

The goal is onboarding completion that means something to a speaker and an
organiser. This is a task-domain decision, not a replacement profile system:
the plugin projects evidence from pretalx and owns only task state.

## Baseline and evidence

Pinned pretalx stores speaker biography in
`pretalx/person/models/profile.py:SpeakerProfile`, answers and uploads in
`pretalx/submission/models/question.py:Answer`, and file bytes through Django
`FileField` storage. Those are real upstream evidence sources, not a new
parallel profile system.

## Cheaper seams rejected

A boolean completion flag cannot prove a profile, answer, or upload exists.
Hand-written per-type model fields would make every new task type a migration.
Public file URLs would bypass pretalx's configured storage and authorization.

The first M1 button marked an acknowledgement complete without evidence. That
was intentionally replaced after review. The heuristic is “completion must be
derivable from a source of truth,” with evaluator keys keeping new task types
cheap.

## How the choice was made

The installed profile, answer, and storage models were inspected before adding
the evaluator registry. Tests deliberately supplied missing evidence and an
unsafe extension; both failed completion, while valid acknowledgement/upload
evidence passed.

## Decision and invariants

Task definitions declare an evaluator key and JSON configuration. Evaluators
check profile fields, question answers, explicit acknowledgements, and
allowlisted uploads. Upload size/type checks run before writing through the
configured Django storage; task evidence is event- and speaker-scoped.

## Upgrade, rollback, and security impact

An upgrade could rename `SpeakerProfile`, `Answer`, or change file-storage
semantics. Re-audit those models and their tests before upgrading. Plugin
evidence rows can be rolled back independently; uploaded bytes must be removed
according to configured storage retention policy.

The cost is evaluator-specific configuration and storage validation code, plus
the need to re-audit upstream profile/question fields after upgrades.

## Automated proof

`tests/test_onboarding_operations.py::test_completion_uses_executor_and_evidence`,
`test_upload_evaluator_rejects_unsafe_type`, and
`test_resources_sanitize_and_only_publish_visible` cover evidence and safety.
