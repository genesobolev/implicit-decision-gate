"""Stable presentation contract for notebook and web replays."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from implicit_decision_gate.gate import (
    CoverageGapRecord,
    DecisionRecord,
    FailureRecord,
    RunRecord,
    RunState,
)
from implicit_decision_gate.scenario import (
    CoverageResult,
    DecisionObservation,
    EffectDisposition,
    InvariantResult,
    UnknownEffect,
)


class DemoAttempt(BaseModel):
    """The four independently evaluated surfaces for one attempt."""

    number: int
    artifact_digest: str | None = None
    invariants: list[InvariantResult] = Field(default_factory=list)
    decisions: list[DecisionObservation] = Field(default_factory=list)
    unknown_effects: list[UnknownEffect] = Field(default_factory=list)
    effect_dispositions: list[EffectDisposition] = Field(default_factory=list)
    coverage: list[CoverageResult] = Field(default_factory=list)


class DemoRun(BaseModel):
    """One replayable run using only persisted gate vocabulary."""

    id: str
    label: str
    scenario: str
    state: RunState
    summary: str
    policy_digest: str
    attempts: list[DemoAttempt]
    decisions: list[DecisionRecord] = Field(default_factory=list)
    coverage_gaps: list[CoverageGapRecord] = Field(default_factory=list)
    failure: FailureRecord | None = None


class DemoDataset(BaseModel):
    """Versioned data consumed by the static walkthrough."""

    schema_version: int = 1
    generated_from: str
    runs: list[DemoRun]


def demo_run_from_record(run: RunRecord, *, label: str, summary: str) -> DemoRun:
    """Project one durable run into the presentation contract."""

    attempts: list[DemoAttempt] = []
    for attempt in run.attempts:
        observation = attempt.observation
        attempts.append(
            DemoAttempt(
                number=attempt.number,
                artifact_digest=attempt.artifact_digest,
                invariants=observation.invariants if observation is not None else [],
                decisions=observation.decisions if observation is not None else [],
                unknown_effects=(observation.unknown_effects if observation is not None else []),
                effect_dispositions=attempt.effect_dispositions,
                coverage=(
                    attempt.coverage_manifest.results
                    if attempt.coverage_manifest is not None
                    else []
                ),
            )
        )
    return DemoRun(
        id=run.run_id,
        label=label,
        scenario=run.scenario_id,
        state=run.state,
        summary=summary,
        policy_digest=run.policy_digest,
        attempts=attempts,
        decisions=run.decisions,
        coverage_gaps=run.coverage_gaps,
        failure=run.failure,
    )


def load_demo_run(path: Path, *, label: str, summary: str) -> DemoRun:
    """Load a persisted run and convert it for presentation."""

    run = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
    return demo_run_from_record(run, label=label, summary=summary)


def build_demo_dataset(runs: Sequence[DemoRun], *, generated_from: str) -> DemoDataset:
    """Build a deterministic, versioned presentation dataset."""

    return DemoDataset(generated_from=generated_from, runs=list(runs))
