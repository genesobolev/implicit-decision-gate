"""Scenario-neutral policy, decision, and observation types."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

type FactValue = str | int | bool | None
type EffectChange = Literal["ADDED", "REMOVED", "CHANGED"]


class ObservedEffect(BaseModel):
    """One normalized system effect reported by a reusable rule."""

    rule_id: str
    change: EffectChange
    object_kind: str
    identity: str
    attribute: str
    before: FactValue = None
    after: FactValue = None


class InvariantStatus(StrEnum):
    """Whether one authoritative requirement held during observation."""

    PASSED = "PASSED"
    VIOLATED = "VIOLATED"


class InvariantResult(BaseModel):
    """Observed evidence for one requirement that isn't owner-selectable."""

    invariant_id: str
    expected: str
    observed: str
    status: InvariantStatus
    evidence: Mapping[str, FactValue] = Field(default_factory=dict)


class DecisionObservation(BaseModel):
    """One recognized option on an owner-selectable decision axis."""

    decision_id: str
    option_id: str
    evidence: Mapping[str, FactValue] = Field(default_factory=dict)


class UnknownEffect(BaseModel):
    """Observed behavior that the approved decision vocabulary can't classify."""

    surface_id: str
    rule_id: str
    description: str
    decision_id: str | None = None
    evidence: Mapping[str, FactValue] = Field(default_factory=dict)


class CoverageStatus(StrEnum):
    """Execution status for one required coverage rule."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MISSING = "MISSING"


class CoverageResult(BaseModel):
    """Observer attestation that one coverage rule executed."""

    rule_id: str
    status: CoverageStatus
    evidence_digest: str | None = None


class ObservationResult(BaseModel):
    """Normalized requirements, decisions, unknowns, facts, and effects."""

    invariants: list[InvariantResult] = Field(default_factory=list)
    decisions: list[DecisionObservation] = Field(default_factory=list)
    unknown_effects: list[UnknownEffect] = Field(default_factory=list)
    facts: dict[str, FactValue] = Field(default_factory=dict)
    effects: list[ObservedEffect] = Field(default_factory=list)
    coverage: list[CoverageResult] = Field(default_factory=list)


class EffectObserver(Protocol):
    """Observe one generated artifact against its committed context."""

    def observe(self, artifact: str, context: str) -> ObservationResult:
        """Return normalized system behavior."""


class EffectDispositionStatus(StrEnum):
    """Policy disposition for one observed effect."""

    EXPECTED = "EXPECTED"
    ALLOWED = "ALLOWED"
    FORBIDDEN = "FORBIDDEN"
    UNCLASSIFIED = "UNCLASSIFIED"


class EffectDisposition(BaseModel):
    """One effect and the policy decision that controls gate behavior."""

    effect_id: str
    effect: ObservedEffect
    status: EffectDispositionStatus
    policy_id: str | None = None
    policy_version: str | None = None
    reason: str


class EffectClassifier(Protocol):
    """Classify effects without changing the observed evidence."""

    @property
    def id(self) -> str:
        """Return the stable policy identifier."""

    @property
    def version(self) -> str:
        """Return the policy implementation version."""

    def classify(
        self,
        effect: ObservedEffect,
        decisions: dict[str, str],
    ) -> tuple[EffectDispositionStatus, str] | None:
        """Return one claimed disposition and reason, or no claim."""


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
class CoverageRuleSpec:
    """One required observer rule in a scenario coverage policy."""

    id: str
    surface_id: str
    observer_id: str
    observer_version: str
    owner: str
    description: str
    required: bool = True


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
    invariant_ids: tuple[str, ...]
    coverage_rules: tuple[CoverageRuleSpec, ...]
    effect_classifiers: tuple[EffectClassifier, ...]
    observer: EffectObserver
    policy_version: str = "1"


class DecisionOptionSnapshot(BaseModel):
    """Persisted owner option from an immutable scenario policy."""

    id: str
    behavior: str
    acceptance_criteria: str


class DecisionSpecSnapshot(BaseModel):
    """Persisted decision definition from an immutable scenario policy."""

    id: str
    question: str
    reason: str
    options: list[DecisionOptionSnapshot]


class CoverageRuleSnapshot(BaseModel):
    """Persisted required rule from an immutable coverage policy."""

    id: str
    surface_id: str
    observer_id: str
    observer_version: str
    owner: str
    description: str
    required: bool


class EffectClassifierSnapshot(BaseModel):
    """Persisted effect-classifier identity."""

    id: str
    version: str


class ScenarioPolicySnapshot(BaseModel):
    """Immutable policy inputs used for one durable run."""

    schema_version: int = 1
    scenario_id: str
    policy_version: str
    invariant_ids: list[str]
    decisions: list[DecisionSpecSnapshot]
    coverage_rules: list[CoverageRuleSnapshot]
    effect_classifiers: list[EffectClassifierSnapshot]


def scenario_policy_snapshot(scenario: Scenario) -> ScenarioPolicySnapshot:
    """Build the immutable policy representation for a scenario."""

    return ScenarioPolicySnapshot(
        scenario_id=scenario.id,
        policy_version=scenario.policy_version,
        invariant_ids=list(scenario.invariant_ids),
        decisions=[
            DecisionSpecSnapshot(
                id=decision.id,
                question=decision.question,
                reason=decision.reason,
                options=[
                    DecisionOptionSnapshot(
                        id=option.id,
                        behavior=option.behavior,
                        acceptance_criteria=option.acceptance_criteria,
                    )
                    for option in decision.options
                ],
            )
            for decision in scenario.decisions
        ],
        coverage_rules=[
            CoverageRuleSnapshot(
                id=rule.id,
                surface_id=rule.surface_id,
                observer_id=rule.observer_id,
                observer_version=rule.observer_version,
                owner=rule.owner,
                description=rule.description,
                required=rule.required,
            )
            for rule in scenario.coverage_rules
        ],
        effect_classifiers=[
            EffectClassifierSnapshot(id=classifier.id, version=classifier.version)
            for classifier in scenario.effect_classifiers
        ],
    )


def scenario_policy_digest(snapshot: ScenarioPolicySnapshot) -> str:
    """Return a stable digest for one persisted scenario policy."""

    payload = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def decision_by_id(decisions: tuple[DecisionSpec, ...], decision_id: str) -> DecisionSpec | None:
    """Return one declared decision by identifier."""

    return next((decision for decision in decisions if decision.id == decision_id), None)


def option_by_id(decision: DecisionSpec, option_id: str) -> DecisionOption | None:
    """Return one declared option by identifier."""

    return next((option for option in decision.options if option.id == option_id), None)
