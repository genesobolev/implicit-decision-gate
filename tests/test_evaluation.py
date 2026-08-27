"""Small deterministic adversarial matrix for the shared gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from implicit_decision_gate.api_probe import OWNER_AND_ADMIN, OWNER_ONLY
from implicit_decision_gate.gate import EvidenceClassification, ReviewerResult, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import EXPIRE_EXISTING, PRESERVE_EXISTING
from implicit_decision_gate.scenarios import (
    SHARE_LINK_EXPIRATION,
    WORKSPACE_EXPORT_AUTHORIZATION,
)
from tests.conftest import (
    ScriptedCodingClient,
    ScriptedReviewerClient,
    ScriptMarkerProbe,
    scripted_scenarios,
)


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    scenario: str
    artifacts: tuple[str, ...]
    selected: str | None
    expected: RunState


CASES = (
    EvaluationCase(
        "database converges",
        SHARE_LINK_EXPIRATION,
        (f"-- {EXPIRE_EXISTING}", f"-- {PRESERVE_EXISTING}"),
        PRESERVE_EXISTING,
        RunState.COMPLETED,
    ),
    EvaluationCase(
        "database ignores decision",
        SHARE_LINK_EXPIRATION,
        (f"-- {EXPIRE_EXISTING}", f"-- {EXPIRE_EXISTING}"),
        PRESERVE_EXISTING,
        RunState.FAILED,
    ),
    EvaluationCase(
        "database unmodeled outcome",
        SHARE_LINK_EXPIRATION,
        ("-- OTHER",),
        None,
        RunState.FAILED,
    ),
    EvaluationCase(
        "authorization converges",
        WORKSPACE_EXPORT_AUTHORIZATION,
        (f"# {OWNER_AND_ADMIN}", f"# {OWNER_ONLY}"),
        OWNER_ONLY,
        RunState.COMPLETED,
    ),
    EvaluationCase(
        "authorization ignores decision",
        WORKSPACE_EXPORT_AUTHORIZATION,
        (f"# {OWNER_AND_ADMIN}", f"# {OWNER_AND_ADMIN}"),
        OWNER_ONLY,
        RunState.FAILED,
    ),
    EvaluationCase(
        "authorization unmodeled outcome",
        WORKSPACE_EXPORT_AUTHORIZATION,
        ("# OTHER",),
        None,
        RunState.FAILED,
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_adversarial_gate_matrix(
    reference_repo: Path,
    tmp_path: Path,
    case: EvaluationCase,
) -> None:
    observer = ScriptMarkerProbe()
    coding = ScriptedCodingClient(case.artifacts)
    orchestrator = Orchestrator(
        repo_path=reference_repo,
        scenarios=scripted_scenarios(observer),
        coding_client=coding,
        reviewer_client=ScriptedReviewerClient(
            [
                ReviewerResult(
                    classification=EvidenceClassification.NOT_EVIDENCED,
                    evidence_quote=None,
                )
            ]
        ),
        worktree_root=tmp_path / case.name.replace(" ", "-"),
    )

    run = orchestrator.start(case.scenario)
    if case.selected is not None:
        assert run.state is RunState.AWAITING_OWNER
        orchestrator.answer(run.run_id, case.selected)
        run = orchestrator.resume(run.run_id)
        assert f"Authoritative owner decision: {case.selected}" in coding.prompts[1]

    assert run.state is case.expected
    assert len(run.attempts) == len(case.artifacts)
