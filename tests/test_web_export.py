from __future__ import annotations

from pathlib import Path

from implicit_decision_gate.gate import RunState
from implicit_decision_gate.scenario import ObservationResult
from implicit_decision_gate.scenarios import scenario_registry
from implicit_decision_gate.web_export import DemoDataset


class EmptyObserver:
    """Provide a protocol-compatible observer for policy inspection."""

    def observe(self, artifact: str, context: str) -> ObservationResult:
        del artifact, context
        return ObservationResult()


def test_static_web_replays_use_the_typed_gate_contract() -> None:
    path = Path("web/public/demo-runs.json")
    dataset = DemoDataset.model_validate_json(path.read_text(encoding="utf-8"))

    assert dataset.schema_version == 1
    assert {run.state for run in dataset.runs} >= {
        RunState.AWAITING_OWNER,
        RunState.COVERAGE_GAP,
        RunState.COMPLETED,
        RunState.FAILED,
    }
    assert any(run.failure is not None for run in dataset.runs)
    assert any(run.coverage_gaps for run in dataset.runs)
    assert any(len(run.attempts) == 2 for run in dataset.runs)

    policies = scenario_registry(EmptyObserver(), EmptyObserver())
    for run in dataset.runs:
        policy = policies[run.scenario]
        invariant_ids = set(policy.invariant_ids)
        decision_ids = {decision.id for decision in policy.decisions}
        coverage_ids = {rule.id for rule in policy.coverage_rules}
        classifier_ids = {classifier.id for classifier in policy.effect_classifiers}
        assert {item.decision_id for item in run.decisions} <= decision_ids
        for attempt in run.attempts:
            assert {item.invariant_id for item in attempt.invariants} <= invariant_ids
            assert {item.decision_id for item in attempt.decisions} <= decision_ids
            assert {item.rule_id for item in attempt.coverage} <= coverage_ids
            assert {
                item.policy_id for item in attempt.effect_dispositions if item.policy_id is not None
            } <= classifier_ids
