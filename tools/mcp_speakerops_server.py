#!/usr/bin/env python3
"""stdio MCP server exposing SpeakerOps typed reads to the Buzz agent.

The Buzz agent runtime is ``opencode acp``; this server is registered in
``opencode.json`` so the agent can answer workflow questions by calling typed
read tools (never direct database access). See
``docs/product-standard-buzz-workflows.md``.

Run through ``tools/run_speakerops_mcp_bridge.py``. Direct execution is
refused unless the caller explicitly supplies ``PRETALX_CONFIG_FILE`` or
``DJANGO_SETTINGS_MODULE``; silently falling back to a checkout database would
produce a confidently wrong operational answer.

Environment:
    PRETALX_CONFIG_FILE             path to the pretalx config
    SPEAKEROPS_BASE_URL             fixed origin for ``go/`` links
    SPEAKEROPS_MCP_PRINCIPAL        named read-only bridge identity
    SPEAKEROPS_MCP_ALLOWED_EVENTS   explicit comma-separated event slugs
    SPEAKEROPS_MCP_CAPABILITIES     explicit comma-separated tool names
    SPEAKEROPS_MCP_SUBJECT_EMAIL    optional fixed self-service subject
"""

import os
import re
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if not (
    os.environ.get("PRETALX_CONFIG_FILE", "").strip()
    or os.environ.get("DJANGO_SETTINGS_MODULE", "").strip()
):
    raise SystemExit(
        "SpeakerOps MCP refuses an implicit database: set PRETALX_CONFIG_FILE or "
        "DJANGO_SETTINGS_MODULE, or use tools/run_speakerops_mcp_bridge.py"
    )
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pretalx.settings")

import django  # noqa: E402


def _setup_django(setup=None) -> None:
    """Keep framework startup diagnostics off the JSON-RPC stdout stream."""

    setup = django.setup if setup is None else setup
    with redirect_stdout(sys.stderr):
        setup()


_setup_django()

import anyio  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import (  # noqa: E402
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    RequestParams,
    TextContent,
    Tool,
)

from pretalx_speakerops.buzz_reads import (  # noqa: E402
    conference_memory_message,
    content_readiness_message,
    release_readiness_message,
)
from pretalx_speakerops.integrations.buzz.operations_reads import (  # noqa: E402
    executive_readiness_message,
    sync_recovery_message,
    workflow_action_receipts_message,
)
from pretalx_speakerops.integrations.buzz.review_reads import (  # noqa: E402
    review_progress_message,
    reviewer_next_assignment_message,
)
from pretalx_speakerops.integrations.buzz.speaker_reads import (  # noqa: E402
    speaker_next_actions_message,
    speaker_nudges_message,
)

SERVER_NAME = "speakerops-reads"
ENV_PRINCIPAL = "SPEAKEROPS_MCP_PRINCIPAL"
ENV_ALLOWED_EVENTS = "SPEAKEROPS_MCP_ALLOWED_EVENTS"
ENV_BASE_URL = "SPEAKEROPS_BASE_URL"
ENV_CAPABILITIES = "SPEAKEROPS_MCP_CAPABILITIES"
ENV_SUBJECT_EMAIL = "SPEAKEROPS_MCP_SUBJECT_EMAIL"
_EVENT_SLUG = re.compile(r"^[A-Za-z0-9_-]+$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ReadPolicy:
    """Fail-closed deployment scope for the read-only bridge process."""

    principal: str
    allowed_events: frozenset[str]
    capabilities: frozenset[str]
    base_url: str
    subject_email: str = ""

    def authorize(self, event_slug: str, capability: str) -> None:
        if event_slug not in self.allowed_events:
            raise ValueError("event is not authorized for this read principal")
        if capability not in self.capabilities:
            raise ValueError("tool is not authorized for this read principal")


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    local_http = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{ENV_BASE_URL} must be an absolute HTTP(S) origin")
    if parsed.scheme != "https" and not local_http:
        raise ValueError(f"{ENV_BASE_URL} requires HTTPS outside loopback")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{ENV_BASE_URL} must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError(f"{ENV_BASE_URL} must be an origin without a path")
    return value.rstrip("/")


def load_read_policy(environ=None) -> ReadPolicy:
    environ = os.environ if environ is None else environ
    principal = environ.get(ENV_PRINCIPAL, "").strip()
    raw_events = environ.get(ENV_ALLOWED_EVENTS, "")
    events = frozenset(item.strip() for item in raw_events.split(",") if item.strip())
    raw_capabilities = environ.get(ENV_CAPABILITIES, "")
    capabilities = frozenset(item.strip() for item in raw_capabilities.split(",") if item.strip())
    base_url = environ.get(ENV_BASE_URL, "").strip()
    subject_email = environ.get(ENV_SUBJECT_EMAIL, "").strip().casefold()
    problems = []
    if not principal:
        problems.append(f"{ENV_PRINCIPAL} is required")
    if not events:
        problems.append(f"{ENV_ALLOWED_EVENTS} requires at least one event slug")
    elif "*" in events or any(not _EVENT_SLUG.fullmatch(item) for item in events):
        problems.append(f"{ENV_ALLOWED_EVENTS} must contain explicit valid event slugs, never '*'")
    if not capabilities:
        problems.append(f"{ENV_CAPABILITIES} requires at least one read tool")
    elif "*" in capabilities or any(not _CAPABILITY.fullmatch(item) for item in capabilities):
        problems.append(f"{ENV_CAPABILITIES} must contain explicit valid tool names, never '*'")
    if subject_email and ("@" not in subject_email or len(subject_email) > 254):
        problems.append(f"{ENV_SUBJECT_EMAIL} must be a valid email address when set")
    try:
        normalized_base_url = _base_url(base_url)
    except ValueError as exc:
        problems.append(str(exc))
        normalized_base_url = ""
    if problems:
        raise ValueError("read bridge configuration is invalid: " + "; ".join(problems))
    return ReadPolicy(
        principal=principal,
        allowed_events=events,
        capabilities=capabilities,
        base_url=normalized_base_url,
        subject_email=subject_email,
    )


READ_SCHEMA = {
    "type": "object",
    "properties": {
        "event_slug": {
            "type": "string",
            "description": (
                "Exact event slug named by the operator. Preserve it verbatim; "
                "never shorten or infer it."
            ),
        },
    },
    "required": ["event_slug"],
    "additionalProperties": False,
}

CORRELATED_ACTION_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "event_slug": READ_SCHEMA["properties"]["event_slug"],
        "claimed_channel_id": {
            "type": "string",
            "maxLength": 200,
            "description": "Caller-claimed Buzz channel identifier; not independently attested.",
        },
        "claimed_trigger_event_id": {
            "type": "string",
            "maxLength": 200,
            "description": "Caller-claimed Buzz trigger event identifier; not attested.",
        },
    },
    "required": ["event_slug", "claimed_channel_id", "claimed_trigger_event_id"],
    "additionalProperties": False,
}

EXACT_RECEIPT_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "event_slug": READ_SCHEMA["properties"]["event_slug"],
        "correlation_id": {
            "type": "string",
            "format": "uuid",
            "description": "Exact correlation identifier returned by the originating workflow.",
        },
    },
    "required": ["event_slug", "correlation_id"],
    "additionalProperties": False,
}

RELEASE_READINESS_TOOL = Tool(
    name="release_readiness",
    description=(
        "Answer 'can we release?' / 'what blocks release?' for an event. "
        "Returns a formatted message with the verdict, named schedule "
        "conflicts (with blocking flag), the attention rollup, schedule "
        "version state, the canonical go/ URL source list (checkable "
        "against the registry), and the trace of inference."
    ),
    inputSchema=READ_SCHEMA,
)

CONTENT_READINESS_TOOL = Tool(
    name="content_readiness",
    description=(
        "Answer 'which latest decks are AV-ready, and who owns what's "
        "not?' for an event. Returns a formatted message with the not-ready "
        "set (missing / pending / changes-requested / stale, each with an "
        "owner), the AV-ready set, the rollup, the canonical go/ URL source "
        "list (checkable against the registry), and the trace of inference."
    ),
    inputSchema=READ_SCHEMA,
)

CONFERENCE_MEMORY_TOOL = Tool(
    name="conference_memory",
    description=(
        "Answer the issue #41 conference-memory question from sourced historical records. "
        "Returns corpus coverage, verified returning AIE speakers with source citations, "
        "explicit provenance gaps, and canonical Conference Memory / CRM links."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "event_slug": READ_SCHEMA["properties"]["event_slug"],
            "query": {
                "type": "string",
                "maxLength": 160,
                "description": "Optional source-backed title, topic, speaker, or edition query.",
            },
        },
        "required": ["event_slug"],
        "additionalProperties": False,
    },
)

SPEAKER_NUDGES_TOOL = Tool(
    name="speaker_nudges",
    description=(
        "Answer 'who needs a nudge today?' with a deadline-ranked, preview-only "
        "recipient/task set and permission-aware task links. Never sends mail."
    ),
    inputSchema=CORRELATED_ACTION_READ_SCHEMA,
)

REVIEW_PROGRESS_TOOL = Tool(
    name="review_progress",
    description=(
        "Answer 'where is review stalled?' with round/pool progress, named overdue "
        "assignments, persisted rubric state, and permission-aware review links."
    ),
    inputSchema=READ_SCHEMA,
)

SYNC_RECOVERY_TOOL = Tool(
    name="sync_recovery",
    description=(
        "Explain failed Accelevents synchronization items and their sanitized latest "
        "attempt, with a selective retry preview. Never executes or exposes a retry command."
    ),
    inputSchema=CORRELATED_ACTION_READ_SCHEMA,
)

SPEAKER_NEXT_ACTIONS_TOOL = Tool(
    name="speaker_next_actions",
    description=(
        "Answer 'what do I owe?' for the deployment-bound speaker identity. Returns only "
        "that speaker's tasks, sessions, profile, and self-scoped links."
    ),
    inputSchema=READ_SCHEMA,
)

REVIEWER_NEXT_ASSIGNMENT_TOOL = Tool(
    name="reviewer_next_assignment",
    description=(
        "Answer 'what is next?' for the deployment-bound reviewer identity. Returns only "
        "that reviewer's open assignments, rubric/save state, and self-scoped links."
    ),
    inputSchema=READ_SCHEMA,
)

EXECUTIVE_READINESS_TOOL = Tool(
    name="executive_readiness",
    description=(
        "Answer 'are we ready?' with an aggregate lifecycle funnel, exceptions, risks, "
        "and public evidence only. Exposes no people or administrative capability."
    ),
    inputSchema=READ_SCHEMA,
)

WORKFLOW_ACTION_RECEIPTS_TOOL = Tool(
    name="workflow_action_receipts",
    description=(
        "Read sanitized receipts for recent human-confirmed speaker-nudge and selective-sync "
        "actions. Returns actor, correlation, outcome counts, and canonical receipt links; "
        "never performs or approves an action."
    ),
    inputSchema=EXACT_RECEIPT_READ_SCHEMA,
)

READS = {
    "release_readiness": release_readiness_message,
    "speaker_nudges": speaker_nudges_message,
    "review_progress": review_progress_message,
    "content_readiness": content_readiness_message,
    "sync_recovery": sync_recovery_message,
    "speaker_next_actions": speaker_next_actions_message,
    "reviewer_next_assignment": reviewer_next_assignment_message,
    "executive_readiness": executive_readiness_message,
    "workflow_action_receipts": workflow_action_receipts_message,
    "conference_memory": conference_memory_message,
}

TOOLS = [
    RELEASE_READINESS_TOOL,
    SPEAKER_NUDGES_TOOL,
    REVIEW_PROGRESS_TOOL,
    CONTENT_READINESS_TOOL,
    SYNC_RECOVERY_TOOL,
    SPEAKER_NEXT_ACTIONS_TOOL,
    REVIEWER_NEXT_ASSIGNMENT_TOOL,
    EXECUTIVE_READINESS_TOOL,
    WORKFLOW_ACTION_RECEIPTS_TOOL,
    CONFERENCE_MEMORY_TOOL,
]

SELF_SCOPED_READS = {"speaker_next_actions", "reviewer_next_assignment"}


async def _handle_list_tools(ctx, params: RequestParams) -> ListToolsResult:
    policy = load_read_policy()
    tools = []
    for tool in TOOLS:
        if tool.name not in policy.capabilities:
            continue
        schema = deepcopy(tool.input_schema)
        schema["properties"]["event_slug"]["enum"] = sorted(policy.allowed_events)
        tools.append(tool.model_copy(update={"input_schema": schema}))
    return ListToolsResult(tools=tools)


async def _handle_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    read = READS.get(params.name)
    if read is None:
        raise ValueError(f"unknown tool: {params.name}")
    arguments = params.arguments or {}
    try:
        policy = load_read_policy()
        event_slug = arguments["event_slug"]
        policy.authorize(event_slug, params.name)
        kwargs = {"base_url": policy.base_url}
        if params.name in {"speaker_nudges", "sync_recovery"}:
            claimed_channel_id = str(arguments.get("claimed_channel_id", "")).strip()
            claimed_trigger_event_id = str(arguments.get("claimed_trigger_event_id", "")).strip()
            if not claimed_channel_id or not claimed_trigger_event_id:
                raise ValueError(
                    "correlated action preview requires claimed channel and trigger event IDs"
                )
            kwargs.update(
                requesting_principal=policy.principal,
                claimed_channel_id=claimed_channel_id[:200],
                claimed_trigger_event_id=claimed_trigger_event_id[:200],
            )
        if params.name == "workflow_action_receipts":
            kwargs["requesting_principal"] = policy.principal
            kwargs["correlation_id"] = arguments["correlation_id"]
        if params.name == "conference_memory":
            kwargs["query"] = arguments.get("query", "")
        if params.name in SELF_SCOPED_READS:
            if not policy.subject_email:
                raise ValueError("self-scoped tool requires a deployment-bound subject identity")
            kwargs["subject_email"] = policy.subject_email
        result = await anyio.to_thread.run_sync(partial(read, event_slug, **kwargs))
    except (KeyError, ValueError) as exc:
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
    return CallToolResult(content=[TextContent(type="text", text=result)])


def build_server() -> Server:
    server = Server(SERVER_NAME)
    server.add_request_handler("tools/list", RequestParams, _handle_list_tools)
    server.add_request_handler("tools/call", CallToolRequestParams, _handle_call_tool)
    return server


async def _serve(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(_serve, build_server())


if __name__ == "__main__":
    main()
