#!/usr/bin/env python3
"""Fail-closed, zero-paid rehearsal for the eight Buzz buyer reads.

This command does not start Buzz, create agents, or mutate SpeakerOps. It proves
the exact OpenCode -> MCP -> explicitly named SpeakerOps Compose path that Buzz
will launch, then can run the eight prompts serially with the approved local
model. Real Buzz channel evidence still requires the owner-controlled relay and
Buzz Desktop steps in ``docs/buzz-eight-workflow-demo.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

LOCAL_MODEL = "llama-server/qwen3.5-2b"
LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
INHERITED_RUNTIME_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
    }
)


@dataclass(frozen=True)
class Profile:
    principal: str
    capabilities: tuple[str, ...]
    subject_email: str
    snapshot: str


PROFILES = {
    "operator": Profile(
        principal="buzz-demo-operator-reader",
        capabilities=(
            "release_readiness",
            "speaker_nudges",
            "review_progress",
            "content_readiness",
            "sync_recovery",
            "executive_readiness",
            "conference_memory",
        ),
        subject_email="",
        snapshot="tools/speakerops-operator.agent.json",
    ),
    "speaker": Profile(
        principal="buzz-demo-speaker-reader",
        capabilities=("speaker_next_actions",),
        subject_email="speaker@example.org",
        snapshot="tools/speakerops-speaker.agent.json",
    ),
    "reviewer": Profile(
        principal="buzz-demo-reviewer-reader",
        capabilities=("reviewer_next_assignment",),
        subject_email="reviewer@example.org",
        snapshot="tools/speakerops-reviewer.agent.json",
    ),
}


@dataclass(frozen=True)
class Workflow:
    number: int
    profile: str
    tool: str
    question: str
    expected_heading: str


WORKFLOWS = (
    Workflow(1, "operator", "release_readiness", "What blocks release?", "# Release readiness"),
    Workflow(2, "operator", "speaker_nudges", "Who needs a nudge today?", "# Speaker nudges"),
    Workflow(3, "operator", "review_progress", "Where is review stalled?", "# Review progress"),
    Workflow(
        4,
        "operator",
        "content_readiness",
        "Which latest decks are ready for AV?",
        "# Content readiness",
    ),
    Workflow(
        5,
        "operator",
        "sync_recovery",
        "Why is Accelevents out of sync?",
        "# Accelevents sync recovery",
    ),
    Workflow(6, "speaker", "speaker_next_actions", "What do I owe?", "# Your next actions"),
    Workflow(
        7,
        "reviewer",
        "reviewer_next_assignment",
        "What is next?",
        "# Your next review",
    ),
    Workflow(8, "operator", "executive_readiness", "Are we ready?", "# Executive readiness"),
)


def build_profile_environment(
    profile_name: str,
    *,
    repo_root: Path,
    compose_project: str,
    base_url: str,
    event_slug: str,
) -> dict[str, str]:
    """Return the non-secret, fail-closed environment for one Buzz agent."""

    profile = PROFILES[profile_name]
    return {
        "OPENCODE_CONFIG": str(repo_root / "opencode.json"),
        "SPEAKEROPS_REPO_ROOT": str(repo_root),
        "SPEAKEROPS_COMPOSE_PROJECT": compose_project,
        "SPEAKEROPS_BASE_URL": base_url,
        "SPEAKEROPS_MCP_PRINCIPAL": profile.principal,
        "SPEAKEROPS_MCP_ALLOWED_EVENTS": event_slug,
        "SPEAKEROPS_MCP_CAPABILITIES": ",".join(sorted(profile.capabilities)),
        "SPEAKEROPS_MCP_SUBJECT_EMAIL": profile.subject_email,
    }


def load_agent_prompt(profile_name: str, repo_root: Path) -> str:
    snapshot = json.loads((repo_root / PROFILES[profile_name].snapshot).read_text())
    return snapshot["definition"]["systemPrompt"]


def validate_local_opencode_config(serialized: str) -> None:
    """Reject a paid/non-loopback model before any rehearsal prompt is sent."""

    config = json.loads(serialized)
    if config.get("model") != LOCAL_MODEL:
        raise ValueError(f"OpenCode must resolve the approved zero-paid local model {LOCAL_MODEL}")
    base_url = (
        config.get("provider", {}).get("llama-server", {}).get("options", {}).get("baseURL", "")
    )
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("the zero-paid rehearsal model endpoint must be loopback HTTP")


def child_environment(
    explicit: dict[str, str], *, inherited: dict[str, str] | None = None
) -> dict[str, str]:
    """Keep only runtime essentials, never ambient credentials, in child processes."""

    inherited = os.environ if inherited is None else inherited
    environment = {
        name: value for name, value in inherited.items() if name in INHERITED_RUNTIME_ENV
    }
    environment.update(explicit)
    return environment


def database_digest(repo_root: Path, compose_project: str) -> str:
    """Stream a data-only PostgreSQL dump into SHA-256 without retaining data."""

    command = [
        "docker",
        "compose",
        "--project-name",
        compose_project,
        "--file",
        str(repo_root / "docker-compose.yml"),
        "exec",
        "--no-TTY",
        "postgres",
        "sh",
        "-c",
        'pg_dump --data-only --no-owner --no-privileges --username="$POSTGRES_USER" "$POSTGRES_DB"',
    ]
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        env=child_environment({}),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    digest = hashlib.sha256()
    if process.stdout is None:  # pragma: no cover - subprocess contract guard
        raise RuntimeError("database digest did not expose a stdout stream")
    canonical_lines = []
    for line in process.stdout:
        # PostgreSQL 17 emits a fresh random psql safety token on every dump.
        # It is transport metadata, not database state, so omit both lines.
        if line.startswith((b"\\restrict ", b"\\unrestrict ")):
            continue
        canonical_lines.append(line)
    for line in sorted(canonical_lines):
        # COPY represents embedded newlines with escapes, so bytewise line
        # sorting canonicalizes unspecified table row order without data loss.
        digest.update(line)
    if process.wait():
        raise RuntimeError(
            "database digest failed; child output was suppressed because it may contain "
            "sensitive data"
        )
    return digest.hexdigest()


def run_checked(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=child_environment(environment),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(command[:3])} failed with exit code {result.returncode}; "
            "child output was suppressed because it may contain sensitive data"
        )
    return result


def preflight_profile(profile_name: str, environment: dict[str, str], repo_root: Path) -> None:
    run_checked(
        [sys.executable, "tools/run_speakerops_mcp_bridge.py", "--check"],
        environment=environment,
        cwd=repo_root,
        timeout=30,
    )
    result = run_checked(
        ["opencode", "mcp", "list"],
        environment=environment,
        cwd=repo_root,
        timeout=30,
    )
    if "connected" not in result.stdout.casefold():
        raise RuntimeError(f"speakerops-reads did not connect for {profile_name}")


def validate_local_runtime(environment: dict[str, str], repo_root: Path) -> None:
    result = run_checked(
        ["opencode", "debug", "config"],
        environment=environment,
        cwd=repo_root,
        timeout=30,
    )
    validate_local_opencode_config(result.stdout)


def workflow_prompt(workflow: Workflow, repo_root: Path, event_slug: str) -> str:
    return (
        f"{load_agent_prompt(workflow.profile, repo_root)}\n\n"
        f"For event {event_slug}, call {workflow.tool} exactly once and answer this "
        f"question: {workflow.question}\n\n"
        "Copy the complete formatted tool output byte for byte into one Markdown code block. "
        "It is already the final answer. Do not shorten it, change a character or URL, or "
        "add text before or after it."
    )


def rehearse_workflow(
    workflow: Workflow,
    *,
    environment: dict[str, str],
    repo_root: Path,
    event_slug: str,
) -> str:
    result = run_checked(
        [
            "opencode",
            "run",
            "--model",
            LOCAL_MODEL,
            "--format",
            "default",
            "--title",
            f"Buzz read {workflow.number}: {workflow.tool}",
            workflow_prompt(workflow, repo_root, event_slug),
        ],
        environment=environment,
        cwd=repo_root,
    )
    answer = result.stdout.strip()
    return answer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--compose-project", default="speakerops-hci")
    parser.add_argument("--base-url", default="http://127.0.0.1:38001")
    parser.add_argument("--event", default="speakerops-demo")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    environments = {
        name: build_profile_environment(
            name,
            repo_root=repo_root,
            compose_project=args.compose_project,
            base_url=args.base_url,
            event_slug=args.event,
        )
        for name in PROFILES
    }

    validate_local_runtime(environments["operator"], repo_root)
    for name, environment in environments.items():
        preflight_profile(name, environment, repo_root)
        print(f"PASS {name}: OpenCode MCP bridge connected")
    if args.check_only:
        print(f"PASS local model: {LOCAL_MODEL} at {LOCAL_BASE_URL}")
        return
    if args.output_dir is None:
        raise SystemExit("--output-dir is required unless --check-only is used")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    started_at = datetime.now(UTC)
    overall_started = perf_counter()
    before_digest = database_digest(repo_root, args.compose_project)
    (output_dir / "database-before.sha256").write_text(f"{before_digest}\n")
    failure: Exception | None = None
    try:
        for workflow in WORKFLOWS:
            path = output_dir / f"{workflow.number:02d}-{workflow.tool}.md"
            workflow_started = perf_counter()
            answer = rehearse_workflow(
                workflow,
                environment=environments[workflow.profile],
                repo_root=repo_root,
                event_slug=args.event,
            )
            path.write_text(f"# {workflow.question}\n\n{answer}\n")
            if (
                workflow.expected_heading not in answer
                or "Generated " not in answer
                or "Trace" not in answer
            ):
                raise RuntimeError(
                    f"{workflow.tool} returned an incomplete answer; full stdout is at {path}"
                )
            records.append(
                {
                    **asdict(workflow),
                    "status": "pass",
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "elapsed_seconds": round(perf_counter() - workflow_started, 3),
                }
            )
            print(f"PASS {workflow.number}/8 {workflow.tool}")
    except Exception as exc:
        failure = exc
        records.append(
            {
                **asdict(workflow),
                "status": "fail",
                "error": str(exc),
                "file": path.name if path.exists() else None,
                "elapsed_seconds": round(perf_counter() - workflow_started, 3),
            }
        )
        records.extend(
            {
                **asdict(pending),
                "status": "not_run",
                "reason": f"stopped after {workflow.tool} failed completeness validation",
            }
            for pending in WORKFLOWS
            if pending.number > workflow.number
        )

    after_digest = database_digest(repo_root, args.compose_project)
    (output_dir / "database-after.sha256").write_text(f"{after_digest}\n")
    digest_match = before_digest == after_digest
    manifest = {
        "started_at": started_at.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(perf_counter() - overall_started, 3),
        "model": LOCAL_MODEL,
        "compose_project": args.compose_project,
        "base_url": args.base_url,
        "event": args.event,
        "channel_demonstrated": False,
        "limitation": "OpenCode/MCP rehearsal only; capture the same answers in Buzz Desktop.",
        "database_integrity": {
            "algorithm": "sha256",
            "before": before_digest,
            "after": after_digest,
            "match": digest_match,
        },
        "workflows": records,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not digest_match:
        raise RuntimeError("database digest changed during the read-only rehearsal")
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
