from pretalx_speakerops.canonical_links import COMMAND, RESOURCES
from pretalx_speakerops.integrations.buzz.buyer_workflows import (
    BUYER_WORKFLOWS,
    CONFERENCE_MEMORY_DIFFERENTIATOR,
    IMPLEMENTED,
    OBSERVED_ENGINE_SCAFFOLDS,
    PLANNED,
)

MANDATORY_BUYER_WORKFLOWS = {
    "release-readiness",
    "speaker-nudges",
    "review-progress",
    "content-readiness",
    "sync-recovery",
    "speaker-next-actions",
    "reviewer-next-assignment",
    "executive-readiness",
}


def _resources():
    return {resource.resource: resource for resource in RESOURCES}


def test_exactly_eight_buyer_workflows_are_named_separately_from_engine_scaffolds():
    assert {workflow.key for workflow in BUYER_WORKFLOWS} == MANDATORY_BUYER_WORKFLOWS
    assert len(BUYER_WORKFLOWS) == 8
    assert len({workflow.persona for workflow in BUYER_WORKFLOWS}) == 8
    assert not MANDATORY_BUYER_WORKFLOWS.intersection(OBSERVED_ENGINE_SCAFFOLDS)
    assert len(OBSERVED_ENGINE_SCAFFOLDS) == 7


def test_every_buyer_workflow_has_a_typed_read_and_safe_canonical_links():
    resources = _resources()
    for workflow in (*BUYER_WORKFLOWS, CONFERENCE_MEMORY_DIFFERENTIATOR):
        assert workflow.read_tool
        assert workflow.question.endswith("?")
        assert workflow.link_resources
        for name in workflow.link_resources:
            assert name in resources, (workflow.key, name)
            assert resources[name].interaction != COMMAND, (workflow.key, name)


def test_command_workflows_name_commands_and_require_receipts():
    resources = _resources()
    command_workflows = [workflow for workflow in BUYER_WORKFLOWS if workflow.requires_receipt]
    assert {workflow.key for workflow in command_workflows} == {
        "speaker-nudges",
        "sync-recovery",
    }
    for workflow in command_workflows:
        for name in workflow.command_resources:
            assert resources[name].interaction == COMMAND, (workflow.key, name)


def test_only_existing_typed_reads_claim_implementation_and_no_channel_demo_is_claimed():
    implemented = {
        workflow.read_tool for workflow in BUYER_WORKFLOWS if workflow.read_status == IMPLEMENTED
    }
    assert implemented == {workflow.read_tool for workflow in BUYER_WORKFLOWS}
    assert all(workflow.channel_demo_status == PLANNED for workflow in BUYER_WORKFLOWS)
    assert CONFERENCE_MEMORY_DIFFERENTIATOR.channel_demo_status == PLANNED


def test_conference_memory_is_the_issue_41_differentiator_not_a_ninth_mandatory_row():
    assert CONFERENCE_MEMORY_DIFFERENTIATOR.key == "conference-memory"
    assert CONFERENCE_MEMORY_DIFFERENTIATOR not in BUYER_WORKFLOWS
    assert CONFERENCE_MEMORY_DIFFERENTIATOR.read_status == IMPLEMENTED
    assert "conference-memory" in CONFERENCE_MEMORY_DIFFERENTIATOR.link_resources
    assert "conference-speaker" in CONFERENCE_MEMORY_DIFFERENTIATOR.link_resources
