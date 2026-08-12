# OpenCode as the Buzz agent harness

Buzz is the harness — the coordination, identity, and messaging plane.
Agents that Buzz spawns run inside a configurable runtime ("harness"). This
document pins OpenCode as the runtime we standardize on, why, and how to
bring a new machine to the same state.

## The architecture in one line

`buzz-acp` spawns `opencode acp` and drives it over the Agent Client Protocol
(JSON-RPC over stdio); OpenCode is the coding agent, Buzz is the harness that
decides when and where it works.

## How Buzz selects a runtime

- Every agent instance stores a preferred runtime id (`runtime`), plus
  harness-specific `model` / `provider` / `env_vars`.
- Runtime discovery (`managed_agents::discovery`) resolves the runtime id to
  a launch command. The **OpenCode preset** is built in:
  `command: "opencode"`, `args: ["acp"]`.
- A custom harness JSON placed in the app's `custom_harnesses/` directory is
  *not* allowed to shadow a preset id — `id: "opencode"` is already claimed,
  so nothing needs to be installed to use OpenCode. Only the `opencode` CLI
  must be present on `PATH`.

## Why OpenCode (and why adoption is low-friction)

| Runtime | Getting it working | Notes |
| --- | --- | --- |
| **OpenCode** | One CLI install, no vendor account | Open-source, self-contained binary; uses the user's own model config |
| `claude` | Anthropic account + API key | Vendor credential required |
| `codex` | OpenAI account + credential | Vendor credential required |
| `goose` | Databricks config / provider setup | Heavier adapter config |
| `grok` | xAI account + credential | Vendor credential required |

OpenCode is the only entry that works with whatever model credentials the
operator already has (or none at all, with a local model). There is no
vendor account, no adapter, and no per-machine credential ceremony — which is
why it is the uniform default for all machines.

## Verify the integration point on a machine

```sh
opencode --version                      # must be on PATH (e.g. ~/.opencode/bin)
opencode acp --help                     # should list "start ACP (Agent Client Protocol) server"
```

Functional check — start `opencode acp` and complete the ACP `initialize`
handshake over stdio:

```sh
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"probe","version":"0.1"}}}' \
  | opencode acp --pure --cwd .
```

A valid reply advertises `agentCapabilities` (loadSession, MCP over http/sse,
session/prompt capabilities). `opencode acp` is a stdio server: it exits
cleanly when stdin closes, so this must be piped, not run with closed stdin.

## Provision an agent on OpenCode (owner-reviewed)

Agent creation is deliberately owner-gated. The relay owner drafts the agent;
the owner's Buzz Desktop reviews and saves it. Runtime selection happens at
save time in the Desktop form.

Option A — import the committed snapshot:

1. Share `tools/opencode-dev.agent.json` in the target channel as an
   attachment (or send it to the owner).
2. In Buzz Desktop, the owner imports the `.agent.json` (Buzz detects the
   `buzz-agent-snapshot` format and offers an import card), confirms the
   runtime is **OpenCode**, and saves.
3. Add the imported agent to the target channel. Buzz spawns `opencode acp`
   as the agent process and manages its lifecycle.

Option B — draft from the CLI (opens the prefilled Desktop form):

```sh
BUZZ_RELAY_URL=<relay> BUZZ_PRIVATE_KEY=<owner key> \
  buzz agents draft-create \
  --channel <channel-uuid> \
  --display-name "OpenCode Dev" \
  --system-prompt "You are a focused engineering agent running on OpenCode."
```

Then save the draft in Buzz Desktop and select runtime **OpenCode**. Leave
model/provider unset — OpenCode auto-detects from its own config, which is
the point: Buzz carries no vendor credentials.

A ready-to-import snapshot is committed at `tools/opencode-dev.agent.json`
in the `buzz-agent-snapshot` v1 manifest format (`format`, `version`,
`definition` with `runtime: "opencode"`, `profile`, `memory`).

## Reference: configuration surface

| Item | Value / location |
| --- | --- |
| OpenCode preset | `managed_agents::discovery::presets` — `id: "opencode"`, `command: "opencode"`, `args: ["acp"]` |
| Custom harnesses (cannot shadow presets) | app data `custom_harnesses/*.json` |
| Agent instances / personas | app data `agents/managed-agents.json` |
| Nest (agent workspace) | `~/.buzz` |
| Install docs | https://opencode.ai/docs |
