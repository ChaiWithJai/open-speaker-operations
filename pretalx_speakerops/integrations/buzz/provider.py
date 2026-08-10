"""Typed model-provider configuration for the Buzz agent bridge.

Step 1 ("configuration only") of the issue #67 integration handoff. This
module owns parsing and validation of the OpenAI-compatible provider profile
used by the speakerops-buzz agent process. It performs no network calls, no
inference, and no SpeakerOps reads or writes.

Invariants enforced here:

- The provider dialect is pinned to Buzz's generic OpenAI-compatible chat mode.
- Configuration fails closed: a missing or malformed provider, model, or base
  URL raises with every problem named, and never echoes secret values.
- Plain-HTTP endpoints are accepted only for loopback/private IP addresses,
  well-known local hostnames, or hosts explicitly allow-listed via
  ``BUZZ_AGENT_PRIVATE_HOSTS``. A bare single-label hostname is NOT assumed
  private: search domains or controlled DNS can resolve it anywhere, so it
  must be allow-listed to count as private topology.
- Public endpoints require an API key; a provider-side "latest" model alias is
  rejected as a production pin.
- The provider client contract forbids following redirects
  (``follow_redirects`` is always ``False``): a redirect must never carry the
  Authorization header to another origin.
- Writes stay disabled until the bounded-write step of the handoff lands, so
  ``BUZZ_AGENT_WRITES_ENABLED`` must remain ``false``.
- The API key is redacted from ``repr``, error messages, status metadata, and
  the diagnostic environment snapshot.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ENV_PROVIDER = "BUZZ_AGENT_PROVIDER"
ENV_API = "OPENAI_COMPAT_API"
ENV_BASE_URL = "OPENAI_COMPAT_BASE_URL"
ENV_MODEL = "OPENAI_COMPAT_MODEL"
ENV_API_KEY = "OPENAI_COMPAT_API_KEY"
ENV_TIMEOUT = "BUZZ_AGENT_TIMEOUT_SECONDS"
ENV_MAX_RETRIES = "BUZZ_AGENT_MAX_RETRIES"
ENV_MAX_OUTPUT_TOKENS = "BUZZ_AGENT_MAX_OUTPUT_TOKENS"
ENV_WRITES_ENABLED = "BUZZ_AGENT_WRITES_ENABLED"
ENV_PRIVATE_HOSTS = "BUZZ_AGENT_PRIVATE_HOSTS"

SECRET_ENV_VARS = (ENV_API_KEY,)
REDACTED = "***redacted***"

SUPPORTED_PROVIDER = "openai"
SUPPORTED_API = "chat"

_PRIVATE_HOSTS = {"localhost", "host.docker.internal"}
_PRIVATE_SUFFIXES = (".internal", ".local", ".localdomain")
_PROVIDER_LABELS = {"api.together.ai": "Together AI", "api.together.xyz": "Together AI"}


class ProviderConfigError(Exception):
    """All configuration problems for one load attempt, without secret values."""

    def __init__(self, problems: list[str]):
        self.problems = tuple(problems)
        super().__init__(
            "Buzz provider configuration is invalid; refusing to start:\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )


class _Secret:
    """API key holder that never leaks through repr/str/logging."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash((_Secret, self._value))


def _is_private_host(host: str, allowed_hosts: frozenset[str] = frozenset()) -> bool:
    lowered = host.lower()
    if lowered in _PRIVATE_HOSTS or lowered in allowed_hosts:
        return True
    if lowered.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        # Hostnames — including bare single-label names, which search domains
        # or controlled DNS can resolve anywhere — are private only when
        # explicitly allow-listed above.
        return False
    return address.is_private or address.is_loopback


def _is_latest_alias(model: str) -> bool:
    lowered = model.lower()
    return lowered == "latest" or lowered.endswith((":latest", "@latest", "-latest", "/latest"))


@dataclass(frozen=True)
class ProviderProfile:
    """Validated OpenAI-compatible provider profile for the Buzz agent."""

    provider: str
    api: str
    base_url: str
    model: str
    api_key: _Secret | None
    timeout_seconds: float = 30.0
    max_retries: int = 2
    max_output_tokens: int = 1024
    writes_enabled: bool = False
    capabilities: tuple[str, ...] = field(default=())
    private_hosts: frozenset[str] = field(default=frozenset())
    # Contract for the future HTTP client: never follow a redirect (and so
    # never forward Authorization to another origin). Not configurable.
    follow_redirects: bool = False

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def is_private_endpoint(self) -> bool:
        return _is_private_host(self.host, self.private_hosts)

    @property
    def provider_label(self) -> str:
        return _PROVIDER_LABELS.get(self.host.lower(), "OpenAI-compatible endpoint")

    def status_card(self) -> dict:
        """Non-secret runtime metadata the agent may publish to Buzz clients.

        Excludes the API key always, and the raw base URL whenever the
        endpoint is private topology.
        """
        return {
            "provider_label": self.provider_label,
            "model_label": self.model,
            "api": self.api,
            "endpoint_host": "private" if self.is_private_endpoint else self.host,
            "capabilities": list(self.capabilities),
            "writes_enabled": self.writes_enabled,
        }

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "ProviderProfile":
        problems: list[str] = []

        provider = (environ.get(ENV_PROVIDER) or "").strip()
        if not provider:
            problems.append(f"{ENV_PROVIDER} is required")
        elif provider != SUPPORTED_PROVIDER:
            problems.append(
                f"{ENV_PROVIDER} must be '{SUPPORTED_PROVIDER}' "
                "(Buzz generic OpenAI-compatible mode)"
            )

        api = (environ.get(ENV_API) or "").strip()
        if not api:
            problems.append(f"{ENV_API} is required")
        elif api != SUPPORTED_API:
            problems.append(f"{ENV_API} must be '{SUPPORTED_API}' for Together/local endpoints")

        allowed_hosts = frozenset(
            part.strip().lower()
            for part in (environ.get(ENV_PRIVATE_HOSTS) or "").split(",")
            if part.strip()
        )

        base_url = (environ.get(ENV_BASE_URL) or "").strip()
        host = ""
        if not base_url:
            problems.append(f"{ENV_BASE_URL} is required")
        else:
            parts = urlsplit(base_url)
            host = parts.hostname or ""
            if parts.scheme not in {"http", "https"} or not host:
                problems.append(f"{ENV_BASE_URL} must be an absolute http(s) URL")
            elif parts.username or parts.password:
                problems.append(f"{ENV_BASE_URL} must not embed credentials")
            elif parts.query or parts.fragment:
                problems.append(f"{ENV_BASE_URL} must not carry a query string or fragment")
            elif parts.scheme == "http" and not _is_private_host(host, allowed_hosts):
                problems.append(
                    f"{ENV_BASE_URL} uses plain http on a host that is not loopback, "
                    f"a private address, or allow-listed in {ENV_PRIVATE_HOSTS}; "
                    "endpoints that cross hosts require TLS"
                )

        model = (environ.get(ENV_MODEL) or "").strip()
        if not model:
            problems.append(f"{ENV_MODEL} is required; Buzz cannot discover provider catalogs")
        elif _is_latest_alias(model):
            problems.append(f"{ENV_MODEL} must pin an exact model ID, not a 'latest' alias")

        raw_key = (environ.get(ENV_API_KEY) or "").strip()
        if base_url and host and not _is_private_host(host, allowed_hosts) and not raw_key:
            problems.append(f"{ENV_API_KEY} is required for non-private endpoints")

        timeout = _parse_number(
            environ, ENV_TIMEOUT, problems, default=30.0, low=1, high=300, kind=float
        )
        retries = _parse_number(
            environ, ENV_MAX_RETRIES, problems, default=2, low=0, high=5, kind=int
        )
        max_tokens = _parse_number(
            environ, ENV_MAX_OUTPUT_TOKENS, problems, default=1024, low=1, high=32768, kind=int
        )

        writes_enabled = False
        raw_writes = (environ.get(ENV_WRITES_ENABLED) or "false").strip().lower()
        if raw_writes == "true":
            problems.append(
                f"{ENV_WRITES_ENABLED} must remain 'false'; bounded writes land only "
                "after the read-only contract suite passes (issue #67 handoff step 5)"
            )
        elif raw_writes != "false":
            problems.append(f"{ENV_WRITES_ENABLED} must be 'true' or 'false'")

        if problems:
            raise ProviderConfigError(problems)

        return cls(
            provider=provider,
            api=api,
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=_Secret(raw_key) if raw_key else None,
            timeout_seconds=timeout,
            max_retries=retries,
            max_output_tokens=max_tokens,
            writes_enabled=writes_enabled,
            private_hosts=allowed_hosts,
        )


def _parse_number(environ, name, problems, *, default, low, high, kind):
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        problems.append(f"{name} must be a number")
        return default
    if not low <= value <= high:
        problems.append(f"{name} must be between {low} and {high}")
        return default
    return value


def redact_environ(environ: Mapping[str, str]) -> dict:
    """Copy an environment mapping with provider secrets masked for diagnostics."""
    return {
        key: (REDACTED if key in SECRET_ENV_VARS and value else value)
        for key, value in environ.items()
    }
