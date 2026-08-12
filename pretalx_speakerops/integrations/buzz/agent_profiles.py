"""Least-privilege process profiles for the three Buzz demo agents.

Buzz agent snapshots intentionally exclude environment variables. Operators
apply these capability profiles in Buzz Desktop after import; OpenCode passes
the process environment into the MCP server through ``opencode.json``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BuzzAgentProfile:
    key: str
    snapshot: str
    capabilities: frozenset[str]
    subject_required: bool


AGENT_PROFILES = (
    BuzzAgentProfile(
        key="operator",
        snapshot="tools/speakerops-operator.agent.json",
        capabilities=frozenset(
            {
                "release_readiness",
                "speaker_nudges",
                "review_progress",
                "content_readiness",
                "sync_recovery",
                "executive_readiness",
                "conference_memory",
                "workflow_action_receipts",
            }
        ),
        subject_required=False,
    ),
    BuzzAgentProfile(
        key="speaker",
        snapshot="tools/speakerops-speaker.agent.json",
        capabilities=frozenset({"speaker_next_actions"}),
        subject_required=True,
    ),
    BuzzAgentProfile(
        key="reviewer",
        snapshot="tools/speakerops-reviewer.agent.json",
        capabilities=frozenset({"reviewer_next_assignment"}),
        subject_required=True,
    ),
)
