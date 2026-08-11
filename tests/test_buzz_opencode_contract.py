import json
import os
import subprocess
import sys
from pathlib import Path

from pretalx_speakerops.integrations.buzz.agent_profiles import AGENT_PROFILES
from pretalx_speakerops.integrations.buzz.buyer_workflows import (
    BUYER_WORKFLOWS,
    CONFERENCE_MEMORY_DIFFERENTIATOR,
)

ROOT = Path(__file__).resolve().parents[1]


def test_direct_mcp_server_refuses_an_implicit_database_configuration():
    environment = os.environ.copy()
    environment.pop("PRETALX_CONFIG_FILE", None)
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mcp_speakerops_server.py")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "refuses an implicit database" in result.stderr


CONFIG = ROOT / "opencode.json"


def test_opencode_bridge_inherits_fail_closed_scope_from_each_buzz_agent_process():
    config = json.loads(CONFIG.read_text())
    bridge = config["mcp"]["speakerops-reads"]

    assert bridge["type"] == "local"
    assert bridge["command"] == [
        "python3",
        "{env:SPEAKEROPS_REPO_ROOT}/tools/run_speakerops_mcp_bridge.py",
    ]
    assert bridge["enabled"] is True
    environment = bridge["environment"]
    assert environment == {
        "SPEAKEROPS_REPO_ROOT": "{env:SPEAKEROPS_REPO_ROOT}",
        "SPEAKEROPS_COMPOSE_PROJECT": "{env:SPEAKEROPS_COMPOSE_PROJECT}",
        "SPEAKEROPS_BASE_URL": "{env:SPEAKEROPS_BASE_URL}",
        "SPEAKEROPS_MCP_PRINCIPAL": "{env:SPEAKEROPS_MCP_PRINCIPAL}",
        "SPEAKEROPS_MCP_ALLOWED_EVENTS": "{env:SPEAKEROPS_MCP_ALLOWED_EVENTS}",
        "SPEAKEROPS_MCP_CAPABILITIES": "{env:SPEAKEROPS_MCP_CAPABILITIES}",
        "SPEAKEROPS_MCP_SUBJECT_EMAIL": "{env:SPEAKEROPS_MCP_SUBJECT_EMAIL}",
    }
    assert all("example.org" not in value for value in environment.values())


def test_three_agent_profiles_partition_all_tools_and_keep_self_service_separate():
    profiles = {profile.key: profile for profile in AGENT_PROFILES}
    assert set(profiles) == {"operator", "speaker", "reviewer"}
    expected = {workflow.read_tool for workflow in BUYER_WORKFLOWS}
    expected.add(CONFERENCE_MEMORY_DIFFERENTIATOR.read_tool)
    assert set().union(*(profile.capabilities for profile in AGENT_PROFILES)) == expected
    assert not profiles["operator"].capabilities & {
        "speaker_next_actions",
        "reviewer_next_assignment",
    }
    assert profiles["speaker"].capabilities == {"speaker_next_actions"}
    assert profiles["reviewer"].capabilities == {"reviewer_next_assignment"}
    assert profiles["operator"].subject_required is False
    assert profiles["speaker"].subject_required is True
    assert profiles["reviewer"].subject_required is True


def test_agent_snapshots_are_portable_secret_free_and_role_specific():
    for profile in AGENT_PROFILES:
        snapshot = json.loads((ROOT / profile.snapshot).read_text())
        assert snapshot["format"] == "buzz-agent-snapshot"
        assert snapshot["version"] == 1
        assert snapshot["definition"]["runtime"] == "opencode"
        assert snapshot["memory"] == {"level": "none"}
        serialized = json.dumps(snapshot).casefold()
        assert "env_vars" not in serialized
        assert "private_key" not in serialized
        assert "api_key" not in serialized
        assert "password" not in serialized

    operator, speaker, reviewer = (
        json.loads((ROOT / profile.snapshot).read_text())["definition"]["systemPrompt"]
        for profile in AGENT_PROFILES
    )
    assert "read-only" in operator
    assert "only speaker_next_actions" in speaker
    assert "only reviewer_next_assignment" in reviewer
    assert all("verbatim" in prompt for prompt in (operator, speaker, reviewer))
