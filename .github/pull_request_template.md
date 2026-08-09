## Capability and outcome

<!-- Name the capability and the user/operator behavior this changes or preserves. -->

Closes #

## Boundaries

- [ ] Authorization is enforced server-side.
- [ ] State-changing behavior is POST-only, atomic, and retry-safe where applicable.
- [ ] Event-owned data remains explicitly event-scoped.
- [ ] External writes and source-provenance behavior remain auditable.

## Schema and operations

- Migration impact: <!-- none / additive / data migration with ADR and recovery link -->
- Deploy or credential impact: <!-- none / describe -->
- Rollback or recovery evidence: <!-- not applicable / link -->

## Verification

- [ ] `make check`
- [ ] Focused behavior/regression tests
- [ ] Browser and accessibility evidence when rendering changed
- [ ] Query/performance evidence when request cost may change
- [ ] No secrets, browser state, dumps, screenshots, traces, or generated output committed

Evidence:

<!-- Commands, results, and private/local artifact paths. -->
