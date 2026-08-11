# Product standard: workflows answer from the system of record with a link to the view

**Status: adopted.** This is the product direction for the Buzz workflow
surface, stated as an enforceable standard. It binds every current and future
workflow, not just a demo script. Origin: operator/agent failure at the
product-defining question — "query the database and give me the link to the
view" — and the PRD promise in #66 ("Ask the conference what needs attention,
decide in the room, and move the real workflow forward with receipts").

## The problem the standard exists to fix

The system of record (SpeakerOps / pretalx web UI) is authoritative but
hostile to its own operators: every read costs latency, a multi-click
navigation tree, and — for anything privileged — the SSO loop. Operators do
not want another tab, another form, another redirect. They want the answer
and the exact view, already found.

The workflow surface is not a chat toy. It is the fix for that hostility.
A workflow that reproduces the pain it is supposed to remove has failed the
product.

## The standard

Every workflow MUST, for each workflow question it handles:

1. **Answer from the database.** Query the system of record through a typed
   read bridge (never from agent chat context, never from hardcoded memory).
   The answer is the real data, reconcileable to named records.
2. **Return a durable, one-click link to the exact view.** The link resolves
   through the `go/{resource}/{opaque-id}` resolver — one redirect maximum,
   authorization decided server-side — straight to the exact record or
   filtered collection. The operator clicks once and lands on the answer;
   no SOR navigation hunt, no SSO loop.
3. **Be read-safe by default.** Links navigate; they never mutate. Mutating
   work stays behind typed commands with preview and receipt, and is never
   handed out as a link.
4. **Never send the operator into the SOR to answer a read.** If the
   workflow answer is not complete in the message + link, the workflow is
   non-conformant.

Every workflow question must be answerable in the message and the link; the
web UI is for acting, not for finding.

## Conformance

A workflow conforms only when it satisfies all four clauses above in an
end-to-end demonstration. A workflow that echoes chat text, answers from
static content, or finishes with "open SpeakerOps and look at X" is
non-conformant regardless of how polished the message is.

## The typed read bridge

The answer-to-link bridge is a stdio MCP server
(`tools/mcp_speakerops_server.py`), registered in `opencode.json` as the
`speakerops-reads` toolset and launched by the agent harness. It exposes one
typed read per workflow question — the first is `release_readiness`
(`pretalx_speakerops/buzz_reads.py`), answering "can we release?" and "what
blocks release?" (demo-map row 5).

Each read:

1. Queries the system of record through Django (never from chat context).
2. Returns a rendered operator message — the verdict, what blocks it, the
   attention rollup, and the schedule state — so the answer lives in the
   message itself (clause 4), not in a payload the agent must translate.
3. Carries the canonical `go/` links to the exact views, built from
   `pretalx_speakerops/canonical_links.py` and resolved by the
   `go/{resource}/{opaque-id}` resolver — one redirect maximum, authorization
   decided server-side. The message prints a **source list** (resource,
   `go/` link, target route, audience, exactness) cross-checkable against the
   registry, so an operator can verify every link before clicking.
4. Prints a **trace of inference**: each numbered step used to derive the
   answer (event resolution, schedule read, warning classification with
   blocking counts, attention rollup, link construction) plus the
   `generated_at` timestamp.
5. Never mutates. Mutating work stays behind typed commands with preview and
   receipt; a read tool that writes is a regression.

The model only ever sees these typed reads; it has no database access. The
rendered message is the workflow answer: the model relays it verbatim rather
than paraphrasing against a raw payload.

## Current state (honest baseline)

| Workflow | Conformant? | Why |
| --- | --- | --- |
| `test-message-echo` | No | Chat echo scaffold; no DB query, no link |
| `test-reaction-thanks` | No | Chat reaction scaffold; no DB query, no link |
| `test-schedule` | No | Trigger scaffold; no DB query, no link |
| `test-webhook` | No | Trigger scaffold; no DB query, no link |
| `test-topic` | No | Chat scaffold; no DB query, no link |
| `test-approval` | No | Scaffold; approval gates unimplemented upstream |
| `test-delay` | No | Timing scaffold; no DB query, no link |

These eight workflows were built to verify the Buzz workflow engine, not to
serve this standard. They occupy the workflow surface and must be reworked or
replaced by workflows that conform. See the investigation issue for the
focused landing path.

## Supporting contracts

- `buzz-demo-map.md` beat 3 defines the link grammar this standard requires;
  the `go/{resource}/{opaque-id}` resolver it references lives in
  `pretalx_speakerops/go_resolver.py` with the anchor registry in
  `pretalx_speakerops/canonical_links.py`.
- ADR-014 fixes the integration boundary: SpeakerOps remains the authority,
  Buzz owns collaboration, and the only admitted bridge code is typed and
  fail-closed. This standard is the product-side requirement that bridge
  must satisfy. The MCP read bridge is the first admitted bridge code.
- #66 success metrics this standard serves: ≥80% task completion without
  manually searching SpeakerOps navigation; ≥90% of generated links resolve
  in one navigation to the exact record; 0 state changes from GET links.
- The `release_readiness` read is exercised by
  `tests/test_speakerops_mcp.py`, which covers the data contract, the link
  grammar, the rendered message (verdict, source list, trace of inference),
  the MCP tool registration, and the JSON-RPC framing.
