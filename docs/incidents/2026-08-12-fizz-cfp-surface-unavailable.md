# Fizz CFP surface tool unavailable

## Summary

On 2026-08-12, Fizz could not answer: “What does the surface area for submitting and
reviewing CFPs look like? Show me canonical URL paths and which user type to use to
explore this.” It correctly failed closed instead of inventing records, but the failure
violated the documented buyer contract.

This was not a database outage or a broken MCP transport. The product contract promised a
typed CFP read and canonical CFP links in `docs/buzz-demo-map.md`, while the MCP server and
the operator capability allow-lists did not implement or expose that read.

## Evidence and occurrences

1. The Buzz conversation at 18:16 showed Fizz reporting that the matching SpeakerOps read
   tool for `speakerops-demo` was unavailable. The concurrently running Codex-backed Fizz
   process had initialized and connected to the relay, so the fail-closed response was a
   missing-capability result rather than a transport failure.
2. The same omission existed in both independently maintained runtime allow-lists: the
   operator profile and the rehearsal profile. That meant both a real Buzz session and the
   local rehearsal path could start successfully without the CFP capability.

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

## RIOA

| Type | Action | Status |
|---|---|---|
| Reinforce | Keep the MCP bridge fail-closed when a capability is absent. | Preserved |
| Improve | Add the read-only `cfp_surface` tool with typed event data, canonical `/go/` links, roles, timestamp, and inference trace. | Implemented |
| Improve | Include `cfp_surface` in both operator capability sources and the demo environment documentation. | Implemented |
| Improve | Exercise the exact question through the MCP call handler, not only the Python read function. | Implemented |
| Omit | Do not add Buzz-side mutations or pretend the public guide is the native submit action. | Enforced in output |
| Automate | Reconcile the MCP catalog, agent profiles, rehearsal profiles, and exact-prompt expectations in regression tests. | Implemented for CFP; inventory consolidation remains follow-up work |

## Preventive principles

1. A documented supported agent question must map to a named typed tool before it is used in
   demo copy.
2. Tool implementation, MCP registration, and the deployed principal allow-list are one
   release unit.
3. Test the user’s exact intent through the protocol boundary and assert authoritative links,
   roles, evidence, and read-only behavior.

## Capability inventory checklist

- [x] Typed read exists.
- [x] MCP tool description matches the user intent.
- [x] MCP dispatcher routes the tool.
- [x] Operator agent profile allows the tool.
- [x] Rehearsal-generated operator environment allows the tool.
- [x] Demo runbook lists the tool.
- [x] Exact-prompt regression asserts submitter, reviewer, and chair `/go/` URLs.
- [x] Regression proves the read does not mutate CFP, question, round, or pool state.
- [ ] After merge/deploy, restart the managed Fizz process so its environment receives the
  new capability, then retain one real Buzz answer and link-open artifact.

## Verification

- Focused regression suite: 55 tests passed.
- Ruff: all changed Python files passed.
- Production and the currently running managed Fizz process were not mutated by this branch.
