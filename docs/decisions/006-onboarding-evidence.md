# Onboarding evidence evaluators

## Context

M2 requires task completion to represent evidence rather than a button click.
Pretalx already stores speaker profiles and question answers, and its file
fields use the configured Django storage.

## Decision

Task definitions declare an evaluator key and JSON configuration. The initial
evaluators are profile fields, question answers, acknowledgements, and
restricted uploads. Upload validation applies allowlisted extensions and byte
limits before writing through Django's configured `FileField` storage.

## Consequences

Adding a task type does not require changing task instances. The evaluator
registry remains plugin-owned and can later be expanded with richer forms.
