from pathlib import Path

import pytest

from tools.run_speakerops_mcp_bridge import POLICY_ENV, bridge_command, check_runtime

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_image_contains_the_bridge_path_required_by_the_launcher():
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    runtime_dependencies = (
        (ROOT / "pyproject.toml").read_text().split("[project.optional-dependencies]", 1)[0]
    )
    assert "COPY tools/mcp_speakerops_server.py /app/tools/mcp_speakerops_server.py" in dockerfile
    assert "!tools/mcp_speakerops_server.py" in dockerignore
    assert '"mcp>=2.0.0"' in runtime_dependencies


def _environment(**overrides):
    values = {
        "SPEAKEROPS_REPO_ROOT": str(ROOT),
        "SPEAKEROPS_COMPOSE_PROJECT": "speakerops-hci",
        "SPEAKEROPS_BASE_URL": "http://127.0.0.1:38001",
        "SPEAKEROPS_MCP_PRINCIPAL": "buzz-demo-operator-reader",
        "SPEAKEROPS_MCP_ALLOWED_EVENTS": "speakerops-demo",
        "SPEAKEROPS_MCP_CAPABILITIES": "release_readiness",
        "SPEAKEROPS_MCP_SUBJECT_EMAIL": "",
    }
    values.update(overrides)
    return values


def test_launcher_targets_only_the_explicit_project_and_container_bridge():
    command = bridge_command(_environment())

    assert command[:7] == [
        "docker",
        "compose",
        "--project-name",
        "speakerops-hci",
        "--file",
        str(ROOT / "docker-compose.yml"),
        "exec",
    ]
    assert "--no-TTY" in command
    assert command[-3:] == ["web", "python", "tools/mcp_speakerops_server.py"]
    assert "PRETALX_CONFIG_FILE" not in " ".join(command)
    for name in POLICY_ENV:
        assert f"{name}={_environment()[name]}" in command


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SPEAKEROPS_REPO_ROOT", ""),
        ("SPEAKEROPS_COMPOSE_PROJECT", ""),
        ("SPEAKEROPS_COMPOSE_PROJECT", "../other"),
        ("SPEAKEROPS_BASE_URL", ""),
        ("SPEAKEROPS_MCP_PRINCIPAL", ""),
        ("SPEAKEROPS_MCP_ALLOWED_EVENTS", ""),
        ("SPEAKEROPS_MCP_CAPABILITIES", ""),
    ],
)
def test_launcher_fails_closed_when_required_scope_is_missing(name, value):
    with pytest.raises(ValueError, match=name):
        bridge_command(_environment(**{name: value}))


def test_launcher_does_not_require_a_self_service_subject_for_operator_profile():
    command = bridge_command(_environment(SPEAKEROPS_MCP_SUBJECT_EMAIL=""))
    assert "SPEAKEROPS_MCP_SUBJECT_EMAIL=" in command


def test_runtime_check_reports_stale_web_image(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "ps" in command:
            return type("Result", (), {"stdout": "web\n", "returncode": 0})()
        return type("Result", (), {"stdout": "", "returncode": 1})()

    monkeypatch.setattr("tools.run_speakerops_mcp_bridge.subprocess.run", run)

    with pytest.raises(RuntimeError, match="build and recreate this exact Compose project"):
        check_runtime(bridge_command(_environment()))
    assert calls[-1][-4:] == ["web", "test", "-f", "/app/tools/mcp_speakerops_server.py"]
