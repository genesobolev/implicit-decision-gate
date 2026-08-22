"""Read-only and owner-answer CLI contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from implicit_decision_gate.agent import ModelResponse, ScriptedModelClient
from implicit_decision_gate.cli import main
from implicit_decision_gate.gate import RunState
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptMarkerProbe


def test_show_and_answer_work_without_model_environment(
    reference_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    coding = ScriptedModelClient(
        [
            ModelResponse.function_call(
                "submit_migration",
                {"sql": "-- EXPIRE_EXISTING"},
            )
        ]
    )
    reviewer = ScriptedModelClient(
        [ModelResponse.text('{"classification":"NOT_EVIDENCED","evidence_quote":null}')]
    )
    run = Orchestrator(
        repo_path=reference_repo,
        model_name="scripted-model",
        coding_client=coding,
        reviewer_client=reviewer,
        probe=ScriptMarkerProbe(),
        worktree_root=tmp_path / "worktrees",
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert run.state is RunState.AWAITING_OWNER

    monkeypatch.chdir(reference_repo)  # type: ignore[attr-defined]
    assert main(["show", run.run_id]) == 0
    shown = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert shown["state"] == "AWAITING_OWNER"
    assert shown["pending_question"]

    assert main(["answer", run.run_id, "--option", "PRESERVE_EXISTING"]) == 0
    answered = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert answered["state"] == "READY_TO_RESUME"
    assert answered["owner_option"] == "PRESERVE_EXISTING"
