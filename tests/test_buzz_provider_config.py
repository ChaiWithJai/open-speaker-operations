"""Contract tests for the Buzz agent provider configuration (issue #67, step 1)."""

import re
from pathlib import Path

import pytest

from pretalx_speakerops.integrations.buzz import (
    SECRET_ENV_VARS,
    ProviderConfigError,
    ProviderProfile,
    redact_environ,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-test-together-key-000111222333"

TOGETHER_ENV = {
    "BUZZ_AGENT_PROVIDER": "openai",
    "OPENAI_COMPAT_API": "chat",
    "OPENAI_COMPAT_BASE_URL": "https://api.together.ai/v1",
    "OPENAI_COMPAT_MODEL": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "OPENAI_COMPAT_API_KEY": SECRET,
}

LOCAL_ENV = {
    "BUZZ_AGENT_PROVIDER": "openai",
    "OPENAI_COMPAT_API": "chat",
    "OPENAI_COMPAT_BASE_URL": "http://127.0.0.1:11434/v1",
    "OPENAI_COMPAT_MODEL": "qwen2.5-coder-32b-q4",
}


def test_together_profile_parses_with_writes_disabled_and_public_status_card():
    profile = ProviderProfile.from_env(TOGETHER_ENV)
    assert profile.writes_enabled is False
    assert profile.max_retries == 2 and profile.timeout_seconds == 30.0
    card = profile.status_card()
    assert card["provider_label"] == "Together AI"
    assert card["model_label"] == TOGETHER_ENV["OPENAI_COMPAT_MODEL"]
    assert card["endpoint_host"] == "api.together.ai"
    assert card["writes_enabled"] is False and card["capabilities"] == []
    assert SECRET not in str(card)


def test_local_profile_parses_without_key_and_hides_private_topology():
    profile = ProviderProfile.from_env(LOCAL_ENV)
    assert profile.api_key is None
    assert profile.status_card()["endpoint_host"] == "private"


def test_bare_hostnames_are_private_only_when_explicitly_allow_listed():
    compose_internal = dict(LOCAL_ENV, OPENAI_COMPAT_BASE_URL="http://ollama:11434/v1")
    # Search domains or controlled DNS can resolve a bare hostname anywhere,
    # so without an allow-list entry it is treated as public: plain http is
    # rejected and an API key is required.
    with pytest.raises(ProviderConfigError) as excinfo:
        ProviderProfile.from_env(compose_internal)
    message = str(excinfo.value)
    assert "BUZZ_AGENT_PRIVATE_HOSTS" in message
    allow_listed = dict(compose_internal, BUZZ_AGENT_PRIVATE_HOSTS="ollama")
    assert ProviderProfile.from_env(allow_listed).is_private_endpoint


@pytest.mark.parametrize(
    "hostname",
    ["model.internal", "model.local", "model.localdomain"],
)
def test_private_looking_dns_suffixes_require_an_explicit_allow_list(hostname):
    private_looking = dict(
        LOCAL_ENV,
        OPENAI_COMPAT_BASE_URL=f"http://{hostname}:11434/v1",
    )
    with pytest.raises(ProviderConfigError) as excinfo:
        ProviderProfile.from_env(private_looking)
    assert "BUZZ_AGENT_PRIVATE_HOSTS" in str(excinfo.value)

    allow_listed = dict(private_looking, BUZZ_AGENT_PRIVATE_HOSTS=hostname)
    assert ProviderProfile.from_env(allow_listed).is_private_endpoint


def test_provider_client_contract_never_follows_redirects():
    assert ProviderProfile.from_env(TOGETHER_ENV).follow_redirects is False
    assert ProviderProfile.from_env(LOCAL_ENV).follow_redirects is False


def test_missing_or_malformed_configuration_fails_closed_with_all_problems_named():
    with pytest.raises(ProviderConfigError) as excinfo:
        ProviderProfile.from_env({"OPENAI_COMPAT_API_KEY": SECRET})
    message = str(excinfo.value)
    for variable in (
        "BUZZ_AGENT_PROVIDER",
        "OPENAI_COMPAT_API",
        "OPENAI_COMPAT_BASE_URL",
        "OPENAI_COMPAT_MODEL",
    ):
        assert variable in message
    assert SECRET not in message


@pytest.mark.parametrize(
    "overrides",
    [
        {"BUZZ_AGENT_PROVIDER": "anthropic"},
        {"OPENAI_COMPAT_API": "responses"},
        {"OPENAI_COMPAT_BASE_URL": "http://api.together.ai/v1"},
        {"OPENAI_COMPAT_BASE_URL": "https://user:pass@api.together.ai/v1"},
        {"OPENAI_COMPAT_BASE_URL": "ftp://api.together.ai/v1"},
        {"OPENAI_COMPAT_MODEL": "meta-llama/latest"},
        {"OPENAI_COMPAT_MODEL": "llama3:latest"},
        {"OPENAI_COMPAT_API_KEY": ""},
        {"BUZZ_AGENT_MAX_RETRIES": "99"},
        {"BUZZ_AGENT_TIMEOUT_SECONDS": "soon"},
        {"BUZZ_AGENT_WRITES_ENABLED": "maybe"},
    ],
)
def test_invalid_profiles_are_rejected(overrides):
    with pytest.raises(ProviderConfigError):
        ProviderProfile.from_env(dict(TOGETHER_ENV, **overrides))


def test_writes_cannot_be_enabled_before_the_bounded_write_step():
    with pytest.raises(ProviderConfigError) as excinfo:
        ProviderProfile.from_env(dict(TOGETHER_ENV, BUZZ_AGENT_WRITES_ENABLED="true"))
    assert "must remain 'false'" in str(excinfo.value)


def test_secret_never_leaks_through_repr_str_or_redacted_environ():
    profile = ProviderProfile.from_env(TOGETHER_ENV)
    assert SECRET not in repr(profile) and SECRET not in str(profile)
    assert SECRET not in repr(profile.api_key)
    assert profile.api_key.reveal() == SECRET
    redacted = redact_environ(dict(TOGETHER_ENV, PATH="/usr/bin"))
    assert redacted["OPENAI_COMPAT_API_KEY"] == "***redacted***"
    assert redacted["PATH"] == "/usr/bin"
    assert redacted["OPENAI_COMPAT_BASE_URL"] == TOGETHER_ENV["OPENAI_COMPAT_BASE_URL"]


def test_agent_env_example_lists_every_variable_with_blank_secrets():
    example = (ROOT / "deploy" / "buzz-agent.env.example").read_text()
    assignments = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for variable in (
        "BUZZ_AGENT_PROVIDER",
        "OPENAI_COMPAT_API",
        "OPENAI_COMPAT_BASE_URL",
        "OPENAI_COMPAT_MODEL",
        "OPENAI_COMPAT_API_KEY",
        "BUZZ_AGENT_WRITES_ENABLED",
    ):
        assert variable in assignments
    for secret_variable in SECRET_ENV_VARS:
        assert assignments[secret_variable] == ""
    assert assignments["BUZZ_AGENT_WRITES_ENABLED"] == "false"


def test_buzz_stays_out_of_the_protected_speakerops_runtime():
    """Issue #67 isolation invariant: no co-location, no ambient credentials."""
    compose = (ROOT / "docker-compose.yml").read_text()
    assert not re.search(r"(?i)buzz|minio|nostr|relay", compose)
    assert "OPENAI_COMPAT" not in compose
    for env_example in (".env.example", ".env.local.example"):
        content = (ROOT / env_example).read_text()
        assert "BUZZ_AGENT" not in content and "OPENAI_COMPAT" not in content
    plugin_sources = list((ROOT / "pretalx_speakerops").rglob("*.py"))
    buzz_dir = ROOT / "pretalx_speakerops" / "integrations" / "buzz"
    importers = [
        path
        for path in plugin_sources
        if buzz_dir not in path.parents and "integrations.buzz" in path.read_text()
    ]
    assert importers == [], f"Buzz adapter must stay unimported by the runtime: {importers}"
