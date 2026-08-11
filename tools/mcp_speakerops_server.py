#!/usr/bin/env python3
"""stdio MCP server exposing SpeakerOps typed reads to the Buzz agent.

The Buzz agent runtime is ``opencode acp``; this server is registered in
``opencode.json`` so the agent can answer workflow questions by calling typed
read tools (never direct database access). See
``docs/product-standard-buzz-workflows.md``.

Run (from the repo root):
    .venv/bin/python tools/mcp_speakerops_server.py

Environment:
    PRETALX_CONFIG_FILE  path to the pretalx config (default:
                         docker/pretalx-local.cfg)
    SPEAKEROPS_BASE_URL  origin used to absolutize ``go/`` links
                         (default: http://localhost:8000)
"""

import os
import sys
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault(
    "PRETALX_CONFIG_FILE", str(REPO_ROOT / "docker" / "pretalx-local.cfg")
)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pretalx.common.settings.test_settings")
os.environ.setdefault("SPEAKEROPS_BASE_URL", "http://localhost:8000")

import django  # noqa: E402

django.setup()

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
    content_readiness_message,
    release_readiness_message,
)

SERVER_NAME = "speakerops-reads"

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "event_slug": {"type": "string", "description": "Event slug, e.g. demo."},
        "base_url": {
            "type": "string",
            "description": "Origin used to absolutize go/ links. Defaults to "
            "SPEAKEROPS_BASE_URL.",
        },
    },
    "required": ["event_slug"],
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

READS = {
    "release_readiness": release_readiness_message,
    "content_readiness": content_readiness_message,
}


async def _handle_list_tools(ctx, params: RequestParams) -> ListToolsResult:
    return ListToolsResult(tools=[RELEASE_READINESS_TOOL, CONTENT_READINESS_TOOL])


async def _handle_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    read = READS.get(params.name)
    if read is None:
        raise ValueError(f"unknown tool: {params.name}")
    arguments = params.arguments or {}
    base_url = arguments.get("base_url") or os.environ.get("SPEAKEROPS_BASE_URL")
    try:
        result = await anyio.to_thread.run_sync(
            partial(read, arguments["event_slug"], base_url=base_url)
        )
    except (KeyError, ValueError) as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=str(exc))], is_error=True
        )
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
