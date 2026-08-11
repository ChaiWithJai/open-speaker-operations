"""Static regression contract for the isolated ADR 014 Buzz demo harness."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "buzz-demo" / "compose.yml"
ENV_EXAMPLE_PATH = ROOT / "buzz-demo" / ".env.example"
RUNBOOK_PATH = ROOT / "buzz-demo" / "README.md"
AUDITED_BUZZ_IMAGE = (
    "ghcr.io/block/buzz@sha256:ff848b46692ca254d0b275deaa24a8e32e4e510ab28787027178453b729f7ebd"
)


def _compose():
    return yaml.safe_load(COMPOSE_PATH.read_text())


def _example_env():
    values = {}
    for line in ENV_EXAMPLE_PATH.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_relay_is_digest_pinned_loopback_only_and_fail_closed():
    compose = _compose()
    relay = compose["services"]["relay"]
    example = _example_env()

    assert relay["image"].startswith("${BUZZ_IMAGE:?")
    assert re.fullmatch(r"ghcr\.io/block/buzz@sha256:[0-9a-f]{64}", example["BUZZ_IMAGE"])
    assert example["BUZZ_IMAGE"] == AUDITED_BUZZ_IMAGE
    assert ":main" not in example["BUZZ_IMAGE"]
    assert relay["ports"] == ["127.0.0.1:${BUZZ_HTTP_PORT:-3100}:3000"]
    assert relay["environment"]["BUZZ_REQUIRE_AUTH_TOKEN"] == "true"
    assert relay["environment"]["BUZZ_REQUIRE_RELAY_MEMBERSHIP"] == "true"
    assert relay["environment"]["RELAY_OWNER_PUBKEY"].startswith("${RELAY_OWNER_PUBKEY:?")
    assert example["BUZZ_REQUIRE_AUTH_TOKEN"] == "true"
    assert example["BUZZ_REQUIRE_RELAY_MEMBERSHIP"] == "true"
    assert example["RELAY_OWNER_PUBKEY"] == ""


def test_every_service_is_bounded_and_project_resources_are_isolated():
    compose = _compose()

    assert compose["name"] == "buzz-demo"
    assert set(compose["services"]) == {
        "relay",
        "postgres",
        "redis",
        "minio",
        "minio-init",
    }
    for name, service in compose["services"].items():
        assert float(service["cpus"]) > 0, f"{name} needs a CPU limit"
        assert re.fullmatch(r"[1-9][0-9]*(?:m|g)", service["mem_limit"]), (
            f"{name} needs a memory limit"
        )
        assert service["networks"] == ["buzz-demo-net"]

    assert set(compose["volumes"]) == {
        "buzz-postgres-data",
        "buzz-redis-data",
        "buzz-minio-data",
        "buzz-git-data",
    }
    assert set(compose["networks"]) == {"buzz-demo-net"}
    assert "speakerops" not in str(compose).lower()
    assert not any(resource.get("external") for resource in compose["volumes"].values())
    assert not any(resource.get("external") for resource in compose["networks"].values())


def test_runbook_has_disk_guardrails_and_project_scoped_teardown():
    runbook = RUNBOOK_PATH.read_text()

    assert "at least 10 GiB free" in runbook
    assert "Native Linux production hosts" in runbook
    assert "utilization below 80%" in runbook
    assert "Docker Desktop demo hosts" in runbook
    assert "do not use the host volume's percentage as a standalone stop gate" in runbook
    assert "virtual-disk allocation" in runbook
    assert "docker system df -v" in runbook
    assert "DockerRootDir` is inside the Linux VM" in runbook
    assert "--project-name buzz-demo" in runbook
    assert "up --detach --wait" in runbook
    assert "down --volumes --remove-orphans" in runbook
    assert "Never use `docker system prune`" in runbook
    assert "never delete SpeakerOps" in runbook
