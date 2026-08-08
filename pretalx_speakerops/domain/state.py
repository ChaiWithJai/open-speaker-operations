from dataclasses import dataclass
from typing import Callable


class TransitionError(ValueError):
    """Raised when a declared state transition is invalid."""


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    actors: frozenset[str] = frozenset({"any"})
    guard: Callable | None = None


@dataclass(frozen=True)
class StateMachine:
    states: frozenset[str]
    transitions: tuple[Transition, ...]
    terminal_states: frozenset[str] = frozenset()

    def validate(self, source: str, target: str, actor_role: str, aggregate) -> None:
        if source not in self.states or target not in self.states:
            raise TransitionError("Unknown state")
        if source in self.terminal_states:
            raise TransitionError("Terminal state cannot transition")
        for transition in self.transitions:
            if transition.source == source and transition.target == target:
                if "any" not in transition.actors and actor_role not in transition.actors:
                    raise TransitionError("Actor is not allowed")
                if transition.guard and not transition.guard(aggregate):
                    raise TransitionError("Transition guard failed")
                return
        raise TransitionError(f"Invalid transition: {source} -> {target}")
