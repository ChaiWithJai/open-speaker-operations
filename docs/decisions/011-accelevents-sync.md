# Decision: Credential-agnostic Accelevents synchronization

## Goal and architecture depth

The competition goal is a judgeable synchronization proof, despite having no
Enterprise Accelevents credentials. This is an integration-boundary decision:
the local product owns idempotency and audit state while the remote API remains
replaceable behind a credential-agnostic client.

## Contract evidence and ambiguity

The committed API evidence establishes `Key` authentication, slug-based
`eventUrl`, bare integer speaker IDs, speaker/session creation, and duplicate
error `4068906`. Create pages also document an `Authorization` header, so the
connection stores the header name instead of hard-coding the ambiguity away.
The captured contract contains no idempotency key. The initial evidence set was
incomplete and omitted update endpoints; review supplied and committed
`update-session.raw.md` and `update-speaker-and-get-speakers.raw.md`, which
establish PUT update paths and void-200 responses. The adapter now treats those
as authoritative.

## Options and trade-offs

Blindly creating on every retry corrupts the remote state and deterministically
hits duplicate-speaker errors. A local identity/fingerprint table costs schema
and reconciliation code but makes unchanged retries no-ops. A forked remote
client cannot solve missing credentials. A fake adapter with no HTTP boundary
would be easy but would not prove contract fidelity.

## How the choice was made

The committed evidence files were treated as authoritative. Contract tests
exercise the mock through real HTTP, including `Key`, bare integer responses,
duplicate `4068906`, and injected failures. Preview compares persisted
fingerprints; execution persists `ExternalIdentity`, attempts, request
fingerprints, and executor-backed item transitions.

## Decision, costs, and guesses

Use configurable base URL and auth header, bounded retries, local identities,
fingerprints, duplicate reconciliation through `speakerWithSessions`, and PUT
updates keyed by the stored external identity. Successful void-200 updates
retain that identity and replace its fingerprint. Speaker error `4090121` is
surfaced as a terminal, non-retryable email-change failure. The mock does not
claim to reproduce Accelevents authorization roles, pagination, rate limits,
or full field validation.

## Upgrade and security impact

Credentials are server-side connection references and never browser data.
Re-audit the recorded contract before changing mappings. The mock must remain
obviously separate from production endpoints.

## Automated proof

`tests/test_m4.py::test_mock_contract_auth_duplicate_and_bare_integer`,
`tests/test_m4.py::test_partial_run_retry_does_not_resend_successful_item`, and
`tests/test_m4.py::test_update_then_preview_is_noop_and_stale_preview_is_rejected`.
