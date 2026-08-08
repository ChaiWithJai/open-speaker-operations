from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import CommandReceipt, OutboxEvent, TransitionLog
from .state import StateMachine, TransitionError


@dataclass(frozen=True)
class Command:
    event: object
    aggregate_model: type
    aggregate_id: int
    action: str
    target_state: str
    state_machine: StateMachine
    actor_role: str = "any"
    payload: dict | None = None


def execute(command: Command, actor, key: str, expected_version: int | None = None):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionError("Authenticated actor required")
    with transaction.atomic():
        receipt = (
            CommandReceipt.objects.select_for_update().filter(event=command.event, key=key).first()
        )
        if receipt:
            return command.aggregate_model.objects.get(pk=receipt.aggregate_id), True

        aggregate = command.aggregate_model.objects.select_for_update().get(pk=command.aggregate_id)
        if aggregate.event_id != command.event.id:
            raise PermissionError("Aggregate is outside the event scope")
        if expected_version is not None and aggregate.version != expected_version:
            raise TransitionError("Optimistic version check failed")
        source = aggregate.status
        command.state_machine.validate(source, command.target_state, command.actor_role, aggregate)
        aggregate.status = command.target_state
        aggregate.version += 1
        aggregate.save(update_fields=["status", "version", "updated"])
        TransitionLog.objects.create(
            event=command.event,
            aggregate_type=aggregate._meta.label,
            aggregate_id=aggregate.pk,
            from_state=source,
            to_state=aggregate.status,
            actor=actor,
            metadata=command.payload or {},
        )
        outbox = OutboxEvent.objects.create(
            event=command.event,
            kind=command.action,
            aggregate_type=aggregate._meta.label,
            aggregate_id=aggregate.pk,
            payload=command.payload or {},
        )
        receipt = CommandReceipt.objects.create(
            event=command.event,
            key=key,
            command=command.action,
            aggregate_type=aggregate._meta.label,
            aggregate_id=aggregate.pk,
            result={"id": aggregate.pk, "status": aggregate.status},
        )
        transaction.on_commit(lambda: dispatch_outbox(outbox.pk))
        return aggregate, False


def dispatch_outbox(outbox_id: int) -> None:
    OutboxEvent.objects.filter(pk=outbox_id, processed__isnull=True).update(
        processed=timezone.now()
    )
