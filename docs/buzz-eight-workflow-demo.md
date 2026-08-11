# Human demo: eight SpeakerOps buyer workflows in Buzz

This is the zero-paid-evaluation proof path for issues #66, #74, and the #41
Conference Memory differentiator. It does not replace the immutable #49 SBEK
baseline. A workflow earns **channel demonstrated** only after the evidence
listed here is captured from a real Buzz channel or DM.

## Three least-privilege agents

Import the three secret-free snapshots in Buzz Desktop:

| Agent | Snapshot | Allowed read tools | Fixed subject |
| --- | --- | --- | --- |
| Operator | `tools/speakerops-operator.agent.json` | release, nudges, review progress, content, sync, executive, memory | none |
| Speaker | `tools/speakerops-speaker.agent.json` | `speaker_next_actions` only | required |
| Reviewer | `tools/speakerops-reviewer.agent.json` | `reviewer_next_assignment` only | required |

Buzz snapshots deliberately exclude environment variables. After import, set
these non-secret process bindings in each agent's Desktop configuration:

```text
OPENCODE_CONFIG=/absolute/path/to/open-speaker-operations/opencode.json
SPEAKEROPS_REPO_ROOT=/absolute/path/to/open-speaker-operations
SPEAKEROPS_COMPOSE_PROJECT=speakerops-hci
SPEAKEROPS_BASE_URL=http://127.0.0.1:38001
SPEAKEROPS_MCP_ALLOWED_EVENTS=speakerops-demo
```

The absolute OpenCode config path is required because Buzz launches managed
agents from its `~/.buzz` nest rather than the repository. The checked-in MCP
launcher then runs the bridge inside the named SpeakerOps `web` container so
typed reads use the deterministic PostgreSQL data. It does not publish the
database or attach Buzz to a SpeakerOps network. Do not point it at another
Compose project.

On the current demo machine OpenCode's resolved default is the zero-paid local
`llama-server/qwen3.5-2b` endpoint. Confirm it with `opencode debug config`
before importing the snapshots. Keep the Buzz model/provider fields unset so
OpenCode uses that reviewed local configuration; do not introduce a paid model
credential during this rehearsal.

Then set one profile per process:

```text
# Operator
SPEAKEROPS_MCP_PRINCIPAL=buzz-demo-operator-reader
SPEAKEROPS_MCP_CAPABILITIES=release_readiness,speaker_nudges,review_progress,content_readiness,sync_recovery,executive_readiness,conference_memory
SPEAKEROPS_MCP_SUBJECT_EMAIL=

# Speaker
SPEAKEROPS_MCP_PRINCIPAL=buzz-demo-speaker-reader
SPEAKEROPS_MCP_CAPABILITIES=speaker_next_actions
SPEAKEROPS_MCP_SUBJECT_EMAIL=speaker@example.org

# Reviewer
SPEAKEROPS_MCP_PRINCIPAL=buzz-demo-reviewer-reader
SPEAKEROPS_MCP_CAPABILITIES=reviewer_next_assignment
SPEAKEROPS_MCP_SUBJECT_EMAIL=reviewer@example.org
```

Do not put model credentials, relay keys, passwords, or connector credentials
in an agent snapshot, channel, screenshot, or checked-in file. OpenCode resolves
these process values into `opencode.json`; the MCP bridge refuses missing,
wildcard, cross-event, and out-of-capability calls.

Before importing agents, verify the bridge target without starting or changing
containers (repeat with each profile's variables):

```sh
python3 tools/run_speakerops_mcp_bridge.py --check
opencode mcp list
```

For tonight's zero-paid rehearsal, the same checks and all eight prompts are
automated serially without exposing any credential:

```sh
python3 tools/rehearse_buzz_reads.py --check-only
python3 tools/rehearse_buzz_reads.py \
  --output-dir /absolute/private/evidence/directory
```

The command refuses a non-loopback or non-`llama-server/qwen3.5-2b` model,
strips ambient paid-provider and unrelated credentials from its child
processes, applies each least-privilege profile separately, and writes a
digest-bearing manifest. Its manifest deliberately says
`channel_demonstrated: false`; only a real Buzz channel or DM can change that
evidence status.

The first command must name a running `web` service and prove that its image
contains `tools/mcp_speakerops_server.py`. A connection failure after the
branch is built is a real runtime blocker; do not fall back to the host SQLite
configuration because it is not the demo system of record.

The #41 memory read has an additional clean-stack gate. Run the strict
coverage/import/verify commands in `buzz-demo/README.md` and retain the
verification report before opening the Operator channel. The expected corpus
is 13 series, 204 editions, 19,466 talks, 21,419 credits, 21,355 source
identities, and 14,068 provisional people. It must also report—not fill in—
1,067 missing formats and 6,077 missing tracks.

Before the nine prompts, authenticate three separate browser profiles with the
deterministic chair, speaker, and reviewer accounts. Open one allowed canonical
destination for each role, then preserve a non-disclosing denial for a speaker
or reviewer organizer URL and for the reviewer's native speaker directory.
This separates an MCP capability check from the destination's own server-side
authorization check.

For executable no-mutation evidence, take a digest immediately before the
nine MCP calls and again immediately after them, before any separately approved
write demonstration. Run from the repository root; these commands stream the
database dump into the digest and do not retain its contents:

```sh
docker compose --project-name speakerops-hci exec -T postgres sh -c \
  'pg_dump --data-only --no-owner --no-privileges --username="$POSTGRES_USER" "$POSTGRES_DB"' \
  | shasum -a 256 > /tmp/speakerops-buzz-before.sha256

# Run the nine typed reads and allowed GET-only link checks here.

docker compose --project-name speakerops-hci exec -T postgres sh -c \
  'pg_dump --data-only --no-owner --no-privileges --username="$POSTGRES_USER" "$POSTGRES_DB"' \
  | shasum -a 256 > /tmp/speakerops-buzz-after.sha256
cmp /tmp/speakerops-buzz-before.sha256 /tmp/speakerops-buzz-after.sha256
```

The digest must match. If it does not, stop and investigate; do not relabel the
conversation read-only. Browser login must happen before the first digest so
session bookkeeping cannot contaminate the comparison.

## Capture standard for every workflow

For every row below, retain:

1. the prompt and complete grounded answer in the Buzz thread;
2. the authoritative records/counts, why they matter now, and next action;
3. the source/trace section and generated timestamp;
4. the permission-aware `go/` link opening in at most one redirect;
5. a role-denial check where the row is self-scoped;
6. proof that the read caused no database mutation.

Do not mark a command-bearing flow complete until the same thread also shows
preview, explicit authoritative confirmation, idempotent result, and correlated
SpeakerOps receipt. The current nudge and sync tools intentionally stop at safe
preview, so their read demonstrations can pass while their action/receipt loops
remain open.

## Mandatory eight

| # | Agent / prompt | Required answer evidence | Required link/action evidence |
| ---: | --- | --- | --- |
| 1 | Operator: “What blocks release?” | Named schedule/content/task/decision/sync blockers and release verdict | Open each relevant resolution link; release action and thread receipt remain a separate write gate |
| 2 | Operator: “Who needs a nudge today?” | Deadline-ranked named recipients/tasks; explicit preview-only statement | Open filtered overdue tasks; later prove reminder preview → confirm → send receipt |
| 3 | Operator: “Where is review stalled?” | Round/pool progress, incomplete and overdue assignments, saved rubric state | Open organizer progress; exact reviewer links must recheck the destination user |
| 4 | Operator: “Which latest decks are ready for AV?” | Latest-version approval, missing/pending/changes/stale state, and owner | Open content/evidence links and the existing bundle surface |
| 5 | Operator: “Why is Accelevents out of sync?” | Failed item, sanitized failure class, latest attempt, selective retry preview | Open sync evidence; later prove confirmed retry preserves successes and posts receipt |
| 6 | Speaker DM: “What do I owe?” | Only `speaker@example.org` tasks, profile, and sessions | Open self-scoped checklist/profile/submission; prove another speaker is absent/denied |
| 7 | Reviewer DM: “What is next?” | Only `reviewer@example.org` open assignment, rubric, and saved state | Open exact assigned review; prove other reviewer, speaker identity, and organizer progress are absent/denied |
| 8 | Operator: “Are we ready?” | Aggregate funnel, exceptions, risks, and public evidence only | Open public status; prove no people, private notes, payloads, or admin capability appear |

## Clean-seed anchors

Use these fixed records to detect a wrong database, stale seed, or hallucinated
answer before accepting screenshots:

- Review progress names one blinded `DemoCon blinded review` round with one
  incomplete, overdue assignment and a rubric saved at 1 of 4 required answers.
- Reviewer next assignment names `Review: Designing Trustworthy Systems`, with
  one remaining/overdue item and the same 1-of-4 saved state. The blinded answer
  must not disclose speaker identity, biography, or company.
- Content readiness reports four upload tasks across two sessions: one ready and
  one not ready. `Trustworthy AI Needs Operational Guardrails` is ready;
  `Accepted: Operations That Scale` is blocked by a stale latest slides v2 and
  a changes-requested supporting document. Both sessions have explicit
  publication decisions.
- The Content answer includes canonical `content-console`, `evidence-file`, and
  `av-bundle` sources. A missing bundle link is a failed workflow.
- Conference Memory matches the strict corpus totals in the preflight section;
  it never turns missing format or track values into invented metadata.

The remaining workflow counts are intentionally derived from current event
state. They must reconcile to the named records in their answer rather than to
a copied number in this document.

## #41 hero differentiator (separate from the eight)

Ask the Operator:

> From our sourced conference history, who has verified return appearances and
> what Agent/Evals programming signals should the chair consider? Cite the
> records and tell me what the source does not provide.

The answer must show the real corpus totals; matching source-linked talks;
AIE-versus-peer topic counts; only explicitly verified cross-edition returning
speakers; missing format/track metadata left as not supplied; exact Conference
Memory and gated CRM links; and the statement that history is evidence, not an
acceptance recommendation. The literal historical catalog contains documented
source gaps, so never claim that every record has format and track metadata.

## Honest completion boundary

Passing the typed-read regressions proves deterministic database behavior; it
does not prove Buzz channel delivery. Passing this human script proves the nine
read conversations. Full #66 completion additionally needs at least one real
preview → confirmation → command → receipt loop, outbox/thread correlation, and
failure/replay evidence. #49 remains open until its 31-row human ledger and 22
official manual checks are completed and reviewed.
