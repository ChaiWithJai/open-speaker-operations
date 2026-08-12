# Fizz CFP surface tool unavailable

## Summary

On 2026-08-12, Fizz could not answer: “What does the surface area for submitting and
reviewing CFPs look like? Show me canonical URL paths and which user type to use to
explore this.” It correctly failed closed instead of inventing records, but the failure
violated the documented buyer contract.

This was not a database outage. Two independent gaps produced the same fail-closed answer:

1. The product contract promised a typed CFP read and canonical CFP links in
   `docs/buzz-demo-map.md`, while the MCP server and operator allow-lists did not implement
   that read.
2. After the read was added, Buzz restarted Fizz into a retained per-channel Codex session.
   The `CODEX_CONFIG` process override was present, but that retained session still exposed
   its old tool inventory. A project-scoped `~/.buzz/.codex/config.toml` entry made the MCP
   server available to both new and resumed sessions.

## Evidence and occurrences

1. The Buzz conversation at 18:16 showed Fizz reporting that the matching SpeakerOps read
   tool for `speakerops-demo` was unavailable. The concurrently running Codex-backed Fizz
   process had initialized and connected to the relay, so the fail-closed response was a
   missing-capability result rather than a transport failure.
2. The same omission existed in both independently maintained runtime allow-lists: the
   operator profile and the rehearsal profile. That meant both a real Buzz session and the
   local rehearsal path could start successfully without the CFP capability.
3. At 23:07 UTC, a stable post-restart replay reached Codex. Its explicit tool inventory
   query returned `[]`, and it completed with the same refusal. This ruled out message
   loss and isolated the second gap to Codex session configuration.
4. At 23:12 UTC, after installing the MCP definition in the project-scoped Codex config
   and restarting Fizz, the same prompt discovered
   `mcp__speakerops_reads__cfp_surface`, invoked it once, and produced the complete typed
   ACP answer. The ACP harness did not publish that answer to the relay.
5. At 23:17 UTC, the same typed result was published through the signed Buzz CLI. Relay
   event `df8e52e0de8e91c6f8a38d5cec61a93b4d3992996048766451d26c3ea349a439`
   and the visible Fizz DM both contain the clean role-specific answer.

Repository evidence:

- The pre-existing contract specifies CFP configuration, routing, deadline state, and the
  two canonical routes at `docs/buzz-demo-map.md:70`.
- The fix implements the event-scoped read and role-specific canonical links at
  `pretalx_speakerops/integrations/buzz/cfp_reads.py:31`.
- The fix registers the tool in the MCP catalog and dispatcher at
  `tools/mcp_speakerops_server.py:267` and `tools/mcp_speakerops_server.py:341`.
- The fix exposes it to the operator in both configuration sources at
  `pretalx_speakerops/integrations/buzz/agent_profiles.py:19` and
  `tools/rehearse_buzz_reads.py:62`.

## Root cause

The repository treated the eight rapid-fire demo workflows as the complete MCP capability
inventory. CFP surface exploration was documented as a judged buyer moment, but it was not
represented by a tool contract that tests could reconcile with the MCP catalog and every
operator allow-list. Documentation, runtime registration, and deployment profiles therefore
drifted independently.

The response itself was correct: inventing CFP state or URLs would have been worse. The
defect was allowing a documented supported question to reach a deployed agent without a
matching typed read.

The live configuration also treated a successful agent restart and online presence as MCP
readiness. That assumption was false for a retained per-channel Codex session: process
environment and relay health were green while the session's tool inventory remained stale.
The supported project-scoped Codex configuration is therefore the durable installation
surface; online presence alone is not a capability preflight.

A third boundary remained outside SpeakerOps: Codex emitted a complete `agent_message` and
`task_complete`, but `buzz-acp` did not create a relay event. Therefore neither an ACP trace
nor a typing/reaction indicator is a delivery receipt. Until the harness publication defect
is fixed upstream, the supported fallback is an explicitly signed `buzz messages send`
followed by a relay read-back.

## RIOA

| Type | Action | Status |
|---|---|---|
| Reinforce | Keep the MCP bridge fail-closed when a capability is absent. | Preserved |
| Improve | Add the read-only `cfp_surface` tool with typed event data, canonical `/go/` links, roles, timestamp, and inference trace. | Implemented |
| Improve | Include `cfp_surface` in both operator capability sources and the demo environment documentation. | Implemented |
| Improve | Exercise the exact question through the MCP call handler, not only the Python read function. | Implemented |
| Improve | Install the MCP definition in project-scoped Codex config for Buzz's `~/.buzz` working directory; do not rely only on `CODEX_CONFIG` for retained sessions. | Implemented on demo machine; documented for operators |
| Omit | Do not add Buzz-side mutations or pretend the public guide is the native submit action. | Enforced in output |
| Automate | Reconcile the MCP catalog, agent profiles, rehearsal profiles, and exact-prompt expectations in regression tests. | Implemented for CFP; inventory consolidation remains follow-up work |
| Automate | Gate buyer rehearsal on an in-session tool inventory check and one exact typed read, not agent presence. | Runbook requirement added; native Buzz automation remains follow-up work |
| Reinforce | Require a relay event ID and visible same-channel message before calling a workflow delivered. | Implemented in runbook and incident evidence |

## Preventive principles

1. A documented supported agent question must map to a named typed tool before it is used in
   demo copy.
2. Tool implementation, MCP registration, and the deployed principal allow-list are one
   release unit.
3. Test the user’s exact intent through the protocol boundary and assert authoritative links,
   roles, evidence, and read-only behavior.
4. Treat an agent as ready only after the active channel session can list the required MCP
   tool and complete a typed read. “Online” proves relay presence, not capability delivery.
5. Treat delivery as complete only when the signed answer can be read back from the relay;
   `agent_message`, `task_complete`, reactions, and typing state are insufficient.

## Capability inventory checklist

- [x] Typed read exists.
- [x] MCP tool description matches the user intent.
- [x] MCP dispatcher routes the tool.
- [x] Operator agent profile allows the tool.
- [x] Rehearsal-generated operator environment allows the tool.
- [x] Demo runbook lists the tool.
- [x] Exact-prompt regression asserts submitter, reviewer, and chair `/go/` URLs.
- [x] Regression proves the read does not mutate CFP, question, round, or pool state.
- [x] Project-scoped Codex MCP config installed for Buzz's `~/.buzz` working directory.
- [x] Managed Fizz restarted after relay subscriptions were confirmed.
- [x] Exact request retained in Buzz with the typed answer, three role-specific `/go/`
  links, timestamp, inference trace, and no-mutation statement, using the signed CLI
  fallback after ACP publication failed.
- [ ] Retain a successful browser-open artifact for each role-specific link.

## Verification

- Focused regression suite: 55 tests passed.
- Ruff: all changed Python files passed.
- Native Codex/Buzz replay: exact prompt passed at 23:12 UTC through
  `mcp__speakerops_reads__cfp_surface`; the ACP publication step failed.
- Signed Buzz fallback: relay event
  `df8e52e0de8e91c6f8a38d5cec61a93b4d3992996048766451d26c3ea349a439`
  was read back from the originating Fizz DM with the complete typed result.
