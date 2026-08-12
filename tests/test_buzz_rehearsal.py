import io
import json
from pathlib import Path

import pytest

from tools.rehearse_buzz_reads import (
    LOCAL_MODEL,
    WORKFLOWS,
    build_profile_environment,
    child_environment,
    database_digest,
    load_agent_prompt,
    rehearse_workflow,
    run_checked,
    validate_local_opencode_config,
    workflow_prompt,
)

ROOT = Path(__file__).resolve().parents[1]


def test_rehearsal_names_exactly_eight_workflows_in_demo_order():
    assert [workflow.tool for workflow in WORKFLOWS] == [
        "release_readiness",
        "speaker_nudges",
        "review_progress",
        "content_readiness",
        "sync_recovery",
        "speaker_next_actions",
        "reviewer_next_assignment",
        "executive_readiness",
    ]
    assert [workflow.profile for workflow in WORKFLOWS] == [
        "operator",
        "operator",
        "operator",
        "operator",
        "operator",
        "speaker",
        "reviewer",
        "operator",
    ]
    assert [workflow.expected_heading for workflow in WORKFLOWS] == [
        "# Release readiness",
        "# Speaker nudges",
        "# Review progress",
        "# Content readiness",
        "# Accelevents sync recovery",
        "# Your next actions",
        "# Your next review",
        "# Executive readiness",
    ]


@pytest.mark.parametrize(
    ("profile", "principal", "capabilities", "subject"),
    [
        (
            "operator",
            "buzz-demo-operator-reader",
            "cfp_surface,conference_memory,content_readiness,executive_readiness,release_readiness,review_progress,speaker_nudges,sync_recovery,workflow_action_receipts",
            "",
        ),
        (
            "speaker",
            "buzz-demo-speaker-reader",
            "speaker_next_actions",
            "speaker@example.org",
        ),
        (
            "reviewer",
            "buzz-demo-reviewer-reader",
            "reviewer_next_assignment",
            "reviewer@example.org",
        ),
    ],
)
def test_profile_environment_is_explicit_least_privilege_and_secret_free(
    profile, principal, capabilities, subject
):
    environment = build_profile_environment(
        profile,
        repo_root=ROOT,
        compose_project="speakerops-hci",
        base_url="http://127.0.0.1:38001",
        event_slug="speakerops-demo",
    )

    assert environment["OPENCODE_CONFIG"] == str(ROOT / "opencode.json")
    assert environment["SPEAKEROPS_REPO_ROOT"] == str(ROOT)
    assert environment["SPEAKEROPS_COMPOSE_PROJECT"] == "speakerops-hci"
    assert environment["SPEAKEROPS_MCP_PRINCIPAL"] == principal
    assert environment["SPEAKEROPS_MCP_ALLOWED_EVENTS"] == "speakerops-demo"
    assert environment["SPEAKEROPS_MCP_CAPABILITIES"] == capabilities
    assert environment["SPEAKEROPS_MCP_SUBJECT_EMAIL"] == subject
    assert not any("KEY" in name or "PASSWORD" in name or "TOKEN" in name for name in environment)


def test_agent_prompt_comes_from_the_reviewed_snapshot():
    prompt = load_agent_prompt("speaker", ROOT)

    assert "only speaker_next_actions" in prompt
    assert "verbatim" in prompt


def test_opencode_agents_load_the_reviewed_snapshot_prompts_as_system_prompts():
    config = json.loads((ROOT / "opencode.json").read_text())

    assert set(config["agent"]) == {
        "speakerops-operator",
        "speakerops-speaker",
        "speakerops-reviewer",
    }
    for profile in ("operator", "speaker", "reviewer"):
        agent = config["agent"][f"speakerops-{profile}"]
        prompt_path = ROOT / "tools" / f"speakerops-{profile}.prompt.md"
        assert agent == {
            "description": f"Read-only SpeakerOps {profile} agent",
            "mode": "primary",
            "prompt": f"{{file:./tools/speakerops-{profile}.prompt.md}}",
            "tools": {"*": False, "speakerops-reads_*": True},
        }
        assert prompt_path.read_text().strip() == load_agent_prompt(profile, ROOT)


def test_rehearsal_invokes_the_matching_opencode_system_agent(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"stdout": "complete answer"})()

    monkeypatch.setattr("tools.rehearse_buzz_reads.run_checked", fake_run)
    workflow = WORKFLOWS[5]

    rehearse_workflow(
        workflow,
        environment={},
        repo_root=ROOT,
        event_slug="speakerops-demo",
    )

    command = calls[0]
    assert command[command.index("--agent") + 1] == "speakerops-speaker"
    assert load_agent_prompt("speaker", ROOT) not in command[-1]


def test_child_environment_drops_paid_provider_and_unrelated_credentials():
    inherited = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp/demo-home",
        "DOCKER_CONTEXT": "desktop-linux",
        "ANTHROPIC_API_KEY": "must-not-flow",
        "OPENAI_API_KEY": "must-not-flow",
        "GOOGLE_GENERATIVE_AI_API_KEY": "must-not-flow",
        "GEMINI_API_KEY": "must-not-flow",
        "AWS_ACCESS_KEY_ID": "must-not-flow",
        "AWS_SECRET_ACCESS_KEY": "must-not-flow",
        "AWS_SESSION_TOKEN": "must-not-flow",
        "AWS_BEARER_TOKEN_BEDROCK": "must-not-flow",
        "AZURE_OPENAI_API_KEY": "must-not-flow",
        "GITHUB_TOKEN": "must-not-flow",
        "DATABASE_URL": "must-not-flow",
    }

    result = child_environment(
        {"SPEAKEROPS_MCP_PRINCIPAL": "buzz-demo-operator-reader"},
        inherited=inherited,
    )

    assert result == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp/demo-home",
        "DOCKER_CONTEXT": "desktop-linux",
        "SPEAKEROPS_MCP_PRINCIPAL": "buzz-demo-operator-reader",
    }


def test_failed_child_output_is_not_copied_into_the_recorded_error(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "accidental secret stdout",
                "stderr": "accidental secret stderr",
            },
        )()

    monkeypatch.setattr("tools.rehearse_buzz_reads.subprocess.run", fake_run)

    with pytest.raises(RuntimeError) as error:
        run_checked(["opencode", "run", "prompt"], environment={}, cwd=tmp_path)

    assert "secret" not in str(error.value)
    assert "exit code 1" in str(error.value)


def test_database_digest_streams_data_only_dump_from_explicit_project(monkeypatch):
    calls = []

    class FakeProcess:
        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            self.stdout = io.BytesIO(
                b"\\restrict random-before\ndeterministic database dump\n"
                b"\\unrestrict random-after\n"
            )
            self.returncode = 0

        def wait(self):
            return self.returncode

    monkeypatch.setattr("tools.rehearse_buzz_reads.subprocess.Popen", FakeProcess)

    digest = database_digest(ROOT, "speakerops-hci")

    assert digest == "f2c328eb34a590e9497af499edd844b156c31176081b9b006d3890338db966de"
    command, kwargs = calls[0]
    assert command[:7] == [
        "docker",
        "compose",
        "--project-name",
        "speakerops-hci",
        "--file",
        str(ROOT / "docker-compose.yml"),
        "exec",
    ]
    assert "--data-only" in command[-1]
    assert kwargs["stderr"] == -3


def test_workflow_prompt_demands_byte_for_byte_tool_output():
    prompt = workflow_prompt(WORKFLOWS[0], ROOT, "speakerops-demo")

    assert "byte for byte" in prompt
    assert "Do not shorten it" in prompt
    assert "add text before or after it" in prompt


def test_local_config_validation_accepts_only_the_zero_paid_rehearsal_model():
    validate_local_opencode_config(
        json.dumps(
            {
                "model": LOCAL_MODEL,
                "provider": {"llama-server": {"options": {"baseURL": "http://127.0.0.1:8080/v1"}}},
            }
        )
    )

    with pytest.raises(ValueError, match="zero-paid local model"):
        validate_local_opencode_config(json.dumps({"model": "anthropic/claude"}))

    with pytest.raises(ValueError, match="loopback"):
        validate_local_opencode_config(
            json.dumps(
                {
                    "model": LOCAL_MODEL,
                    "provider": {
                        "llama-server": {"options": {"baseURL": "https://paid.example/v1"}}
                    },
                }
            )
        )
