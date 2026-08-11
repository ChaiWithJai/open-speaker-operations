"""Competition-facing Buzz workflow contract.

The Buzz engine scaffolds are not the product.  This registry names the eight
buyer jobs from issue #66 that must be demonstrated in Buzz, plus the
Conference Memory differentiator from issue #41.  A workflow is not marked as
demonstrated merely because a read function or canonical link exists.
"""

from dataclasses import dataclass

PLANNED = "planned"
IMPLEMENTED = "implemented"


@dataclass(frozen=True)
class BuyerWorkflow:
    key: str
    persona: str
    question: str
    read_tool: str
    link_resources: tuple[str, ...]
    command_resources: tuple[str, ...] = ()
    read_status: str = PLANNED
    channel_demo_status: str = PLANNED

    @property
    def requires_receipt(self):
        return bool(self.command_resources)


BUYER_WORKFLOWS = (
    BuyerWorkflow(
        key="release-readiness",
        persona="program-chair",
        question="What blocks release?",
        read_tool="release_readiness",
        link_resources=(
            "conflicts-drilldown",
            "agenda-release",
            "content-console",
            "program-decisions",
        ),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="speaker-nudges",
        persona="speaker-coordinator",
        question="Who needs a nudge today?",
        read_tool="speaker_nudges",
        link_resources=("overdue-tasks",),
        command_resources=("reminder-send",),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="review-progress",
        persona="reviewer-lead",
        question="Where is review stalled?",
        read_tool="review_progress",
        link_resources=("review-queue", "round-review-assignment"),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="content-readiness",
        persona="content-production",
        question="Which latest decks are ready for AV?",
        read_tool="content_readiness",
        link_resources=("content-console", "evidence-file", "av-bundle"),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="sync-recovery",
        persona="integration-operator",
        question="Why is Accelevents out of sync?",
        read_tool="sync_recovery",
        link_resources=("sync-console",),
        command_resources=("sync-run-retry",),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="speaker-next-actions",
        persona="speaker",
        question="What do I owe?",
        read_tool="speaker_next_actions",
        link_resources=("speaker-checklist", "speaker-profile"),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="reviewer-next-assignment",
        persona="reviewer",
        question="What is next?",
        read_tool="reviewer_next_assignment",
        link_resources=("review-assignment", "review-queue"),
        read_status=IMPLEMENTED,
    ),
    BuyerWorkflow(
        key="executive-readiness",
        persona="executive-stakeholder",
        question="Are we ready?",
        read_tool="executive_readiness",
        link_resources=("status",),
        read_status=IMPLEMENTED,
    ),
)


CONFERENCE_MEMORY_DIFFERENTIATOR = BuyerWorkflow(
    key="conference-memory",
    persona="program-chair",
    question="Who and what should we bring back, and what evidence supports it?",
    read_tool="conference_memory",
    link_resources=("conference-memory", "conference-speaker", "crm-directory"),
    read_status=IMPLEMENTED,
)


# This is the complete inventory actually named in the checked-in relay audit.
# The audit text previously called it eight; only seven identifiers were recorded.
OBSERVED_ENGINE_SCAFFOLDS = (
    "test-message-echo",
    "test-reaction-thanks",
    "test-schedule",
    "test-webhook",
    "test-topic",
    "test-approval",
    "test-delay",
)
