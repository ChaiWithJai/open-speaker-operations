#!/usr/bin/env python3
"""Run the SpeakerOps MCP bridge inside the deterministic Compose web service.

Buzz starts OpenCode from its ``~/.buzz`` nest, not from this repository. The
typed reads also need the demo PostgreSQL database inside the isolated
SpeakerOps Compose project; starting the bridge directly on the host would use
``docker/pretalx-local.cfg`` and an unrelated SQLite database. This small
stdio-transparent launcher closes both gaps without publishing PostgreSQL.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

POLICY_ENV = (
    "SPEAKEROPS_BASE_URL",
    "SPEAKEROPS_MCP_PRINCIPAL",
    "SPEAKEROPS_MCP_ALLOWED_EVENTS",
    "SPEAKEROPS_MCP_CAPABILITIES",
    "SPEAKEROPS_MCP_SUBJECT_EMAIL",
)
PROJECT_ENV = "SPEAKEROPS_COMPOSE_PROJECT"
REPO_ENV = "SPEAKEROPS_REPO_ROOT"
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def bridge_command(environ: dict[str, str] | None = None) -> list[str]:
    """Return the exact, bounded Compose exec command or fail closed."""

    environ = dict(os.environ if environ is None else environ)
    problems: list[str] = []
    repo_value = environ.get(REPO_ENV, "").strip()
    repo_root = Path(repo_value).expanduser().resolve() if repo_value else None
    compose_file = repo_root / "docker-compose.yml" if repo_root else None
    project = environ.get(PROJECT_ENV, "").strip()

    if repo_root is None or not repo_root.is_dir():
        problems.append(f"{REPO_ENV} must name the checked-out repository")
    elif compose_file is None or not compose_file.is_file():
        problems.append(f"{REPO_ENV} must contain docker-compose.yml")
    if not project or not PROJECT_NAME.fullmatch(project):
        problems.append(f"{PROJECT_ENV} must be an explicit valid Compose project name")
    for name in POLICY_ENV[:-1]:
        if not environ.get(name, "").strip():
            problems.append(f"{name} is required")
    if problems:
        raise ValueError("Buzz MCP launcher configuration is invalid: " + "; ".join(problems))

    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(compose_file),
        "exec",
        "--no-TTY",
    ]
    for name in POLICY_ENV:
        command.extend(("--env", f"{name}={environ.get(name, '').strip()}"))
    command.extend(("web", "python", "tools/mcp_speakerops_server.py"))
    return command


def check_runtime(command: list[str]) -> None:
    """Prove the targeted project is running and contains the bridge code."""

    exec_index = command.index("exec")
    compose_prefix = command[:exec_index]
    result = subprocess.run(
        [*compose_prefix, "ps", "--status", "running", "--services"],
        check=True,
        capture_output=True,
        text=True,
    )
    if "web" not in set(result.stdout.splitlines()):
        raise RuntimeError("the targeted Compose project has no running web service")
    bridge_file = subprocess.run(
        [
            *compose_prefix,
            "exec",
            "--no-TTY",
            "web",
            "test",
            "-f",
            "/app/tools/mcp_speakerops_server.py",
        ],
        check=False,
    )
    if bridge_file.returncode:
        raise RuntimeError(
            "the targeted web image does not contain /app/tools/mcp_speakerops_server.py; "
            "build and recreate this exact Compose project from the Buzz read branch first"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the targeted running web container contains the MCP server, then exit",
    )
    args = parser.parse_args()
    try:
        command = bridge_command()
        if args.check:
            check_runtime(command)
            print("Buzz MCP runtime is ready.")
            return
        os.execvp(command[0], command)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
