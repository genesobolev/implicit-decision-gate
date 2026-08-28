"""Scenario-neutral decision and observation types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

type FactValue = str | int | bool | None
type EffectChange = Literal["ADDED", "REMOVED", "CHANGED"]

UNMODELED_OUTCOME = "UNMODELED"


class ObservedEffect(BaseModel):
    """One normalized system effect reported by a reusable rule."""

    rule_id: str
    change: EffectChange
    object_kind: str
    identity: str
    attribute: str
    before: FactValue = None
    after: FactValue = None


class ObservationResult(BaseModel):
    """Normalized facts and bounded outcomes keyed by decision identifier."""

    outcomes: dict[str, str]
    facts: dict[str, FactValue] = Field(default_factory=dict)
    effects: list[ObservedEffect] = Field(default_factory=list)


class EffectObserver(Protocol):
    """Observe one generated artifact against its committed context."""

    def observe(self, artifact: str, context: str) -> ObservationResult:
        """Return normalized system behavior."""


@dataclass(frozen=True)
class DecisionOption:
    """One owner-selectable behavior with deterministic acceptance criteria."""

    id: str
    behavior: str
    acceptance_criteria: str


@dataclass(frozen=True)
class DecisionSpec:
    """The bounded missing decision for one scenario."""

    id: str
    question: str
    reason: str
    options: tuple[DecisionOption, ...]


@dataclass(frozen=True)
class Scenario:
    """All scenario-specific inputs around the shared gate lifecycle."""

    id: str
    brief_path: Path
    context_path: Path
    context_label: str
    artifact_directory: Path
    artifact_suffix: str
    coding_instructions: str
    decisions: tuple[DecisionSpec, ...]
    observer: EffectObserver


def decision_by_id(decisions: tuple[DecisionSpec, ...], decision_id: str) -> DecisionSpec | None:
    """Return one declared decision by identifier."""

    return next((decision for decision in decisions if decision.id == decision_id), None)


def option_by_id(decision: DecisionSpec, option_id: str) -> DecisionOption | None:
    """Return one declared option by identifier."""

    return next((option for option in decision.options if option.id == option_id), None)
