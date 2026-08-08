import pytest
from django_scopes import scope

from pretalx_speakerops.domain.commands import Command, execute
from pretalx_speakerops.domain.state import StateMachine, Transition, TransitionError
from pretalx_speakerops.models import (
    CommandReceipt,
    OnboardingTask,
    OutboxEvent,
    TaskDefinition,
    TransitionLog,
)


@pytest.mark.django_db(transaction=True)
def test_executor_is_atomic_and_idempotent(event, users):
    with scope(event=event):
        task = OnboardingTask.objects.create(
            event=event,
            speaker=users["speaker"],
            definition=TaskDefinition.objects.create(
                event=event,
                slug="ack",
                name="Acknowledgement",
                instructions="Ack",
                completion_criteria="Click",
            ),
        )
        machine = StateMachine(
            states=frozenset({"pending", "complete"}),
            transitions=(Transition("pending", "complete", frozenset({"speaker"})),),
            terminal_states=frozenset({"complete"}),
        )
        command = Command(
            event=event,
            aggregate_model=OnboardingTask,
            aggregate_id=task.pk,
            action="onboarding.complete",
            target_state="complete",
            state_machine=machine,
            actor_role="speaker",
        )
        result, replay = execute(command, users["speaker"], "task-1", expected_version=0)
        replayed, was_replay = execute(command, users["speaker"], "task-1")
        assert result.status == replayed.status == "complete"
        assert replay is False and was_replay is True
        assert CommandReceipt.objects.filter(event=event, key="task-1").count() == 1
        assert TransitionLog.objects.filter(event=event).count() == 1
        assert OutboxEvent.objects.filter(event=event).count() == 1


def test_transition_table_is_exhaustive():
    machine = StateMachine(
        states=frozenset({"pending", "complete"}),
        transitions=(Transition("pending", "complete"),),
        terminal_states=frozenset({"complete"}),
    )
    machine.validate("pending", "complete", "any", object())
    with pytest.raises(TransitionError):
        machine.validate("complete", "pending", "any", object())
    with pytest.raises(TransitionError):
        machine.validate("pending", "pending", "any", object())
