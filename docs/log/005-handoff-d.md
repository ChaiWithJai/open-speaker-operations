# Work unit 005: M4 Accelevents boundary

- **Intent:** Turn the explicit Accelevents gap into a judgeable mock-backed
  synchronization proof without pretending Enterprise credentials exist.
- **Time box:** M4 integration core and local-stack backfill.
- **Ran:** Read committed API evidence, added configurable `Key` auth, mock
  HTTP endpoints, duplicate reconciliation, request fingerprints, external
  identities, executor-backed sync item transitions, attempt history, and
  failure injection.
- **Failed:** The first retry implementation reused an executor receipt key
  across attempts, leaving a failed item failed after the remote retry. A
  second issue lost the attempt counter after refreshing the aggregate. Both
  were fixed with attempt-specific receipt keys and explicit counter
  persistence.
- **Guesses labelled:** The initial evidence set appeared to have no update
  endpoint, so changed items were previewed as `update` but failed honestly at
  execution. Review caught that this was an evidence omission, not an API
  limitation. The mock does not model undocumented pagination/rate limits/role
  authorization.
- **Abandoned:** No attempt was made to hide missing credentials or fabricate a
  production connection. The dashboard keeps a credential-blocked state.
- **What we would do differently:** Start with the partial-retry test before
  adding seed records; it exposed the idempotency-key collision immediately.
- **Doom-loop:** Not invoked; the retry bug remained on the protected path and
  was fixed rather than cut.
