# Decision: Buzz as an isolated bounded harness with a fail-closed provider adapter

## Goal and architecture depth

Issues #66/#67 propose Buzz (block/buzz, pinned upstream revision
`07a3c768d619db31fee3f0590f9433cdd1213e8f`) as the conversational operations
surface around SpeakerOps. This record fixes the integration boundary before
any bridge code lands: SpeakerOps remains the transactional and authorization
authority, Buzz owns collaboration events, and the only code admitted now is
step 1 of the #67 handoff — typed, fail-closed model-provider configuration
for the future agent bridge. This is an integration-boundary and deployment
blast-radius decision.

## Contract evidence and ambiguity

The pinned upstream revision establishes Buzz's operational footprint. Its
production Compose bundle runs five services (relay on
`ghcr.io/block/buzz`, Postgres 17, Redis 7, MinIO plus an init job) with four
named volumes (Postgres, Redis, MinIO, git data) and no default resource
limits; the relay image floats on `main` unless explicitly pinned. Five state
classes must be backed up: relay private key, owner key, Postgres, object
storage, and the git volume. Security is Nostr-based: NIP-42 for WebSocket,
NIP-98 for REST; channel membership is the only access control; the audit
chain is tamper-evident, not tamper-resistant; TLS is delegated to a reverse
proxy. Buzz is pre-1.0 and only `main` receives security fixes. Workflow
approval execution is explicitly incomplete upstream (approval tokens are not
persisted; runs fail at approval gates), and provider/model metadata does not
sync across desktop installs. The agent consumes any OpenAI-compatible
endpoint (Together AI or local Ollama/vLLM) through
`BUZZ_AGENT_PROVIDER=openai` with the chat dialect. Ambiguities accepted: no
official Buzz-on-DigitalOcean guide exists, upstream publishes no host sizing
minimums, and the Compose bundle hard-codes MinIO addressing.

## Options and trade-offs

Co-locating Buzz in the protected `speakerops` Compose project would reuse
one host but shares upgrade, disk, key, and cleanup blast radius with the
benchmarked product while Buzz is pre-1.0. Deploying the full stack to App
Platform fails on persistent local state. Starting on DOKS/Helm buys HA the
product has not earned. Letting the relay or SpeakerOps hold model
credentials would spread secrets across trust boundaries. Placing provider
configuration in SpeakerOps settings/`.env` would invite exactly that
coupling. The remaining option — a separate Droplet running upstream's
pinned Compose bundle, with a separate agent process owning provider
credentials, and only a typed configuration module in this repository —
costs an extra host and some duplication but keeps every failure domain and
secret scope independent.

## How the choice was made

The upstream Compose file, Compose README, SECURITY.md, VISION.md, and Helm
chart at the pinned revision were read as the deployment contract. The
existing SpeakerOps invariants were treated as non-negotiable: one canonical
root Compose entry point, immutable image digests, `speakerops`-prefixed
Compose projects enforced by `deploy/scripts/deploy-digitalocean.sh`, and the
domain command receipt/outbox pattern in `pretalx_speakerops/domain/` as the
only write path. The handoff comment on #67 ordered implementation
configuration-first, so the admitted code is exactly that step.

## Decision, costs, and guesses

Adopt RFC #67's recommendation. Buzz runs only as an isolated feasibility
deployment on a dedicated Droplet using upstream's Compose bundle with a
pinned image; it never joins the `speakerops` Compose project, `.env`
contract, or deploy scripts, and SpeakerOps must remain fully operable with
the entire Buzz stack stopped. The bridge/agent is a separate process with
its own least-privilege identity; model credentials live only in its
deployment environment (`deploy/buzz-agent.env.example` documents the blank
contract). `pretalx_speakerops/integrations/buzz/provider.py` pins the
provider dialect (`openai`/`chat`), fails closed on missing or malformed
provider, model, or base URL, rejects `latest` model aliases and plain HTTP
across hosts, requires keys for public endpoints, redacts secrets from
errors, repr, and status metadata, and hard-rejects `writes_enabled=true`
until the bounded-write step is separately approved. The runtime must not
import the adapter package. Guesses: Together AI as first profile with a
local endpoint substitutable; a single Droplet is adequate for the
feasibility trial; upstream approval-execution gaps will not block read-only
briefs.

## Upgrade and security impact

Re-audit this record before moving off the pinned Buzz revision: re-read the
Compose bundle, SECURITY.md supported-versions policy, and the workflow
approval status, and rerun the backup/restore drill for all five Buzz state
classes. Nostr pubkeys, NIP-05 handles, display names, and channel
membership are labels, never SpeakerOps authority; any future write path
must go through an explicit principal binding and the existing command
receipt contract. Provider keys must never appear in repository files,
Compose files, browser payloads, Nostr events, or logs. Enabling writes,
co-locating any Buzz service, or teaching the runtime to import the adapter
each require a new decision record.

## Automated proof

`tests/test_buzz_provider_config.py::test_missing_or_malformed_configuration_fails_closed_with_all_problems_named`,
`tests/test_buzz_provider_config.py::test_writes_cannot_be_enabled_before_the_bounded_write_step`,
`tests/test_buzz_provider_config.py::test_secret_never_leaks_through_repr_str_or_redacted_environ`, and
`tests/test_buzz_provider_config.py::test_buzz_stays_out_of_the_protected_speakerops_runtime`.
