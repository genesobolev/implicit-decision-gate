"""Read-only and owner-answer CLI contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from implicit_decision_gate.agent import ModelResponse, ScriptedModelClient
from implicit_decision_gate.cli import main
from implicit_decision_gate.gate import AgentBackend, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptMarkerProbe


def test_scripted_cli_runs_without_credentials(
    reference_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the public scripted start, answer, and resume workflow."""

    monkeypatch.chdir(reference_repo)
    monkeypatch.setattr(
        "implicit_decision_gate.cli.PostgresProbe",
        lambda _dsn: ScriptMarkerProbe(),
    )

    assert (
        main(
            [
                "start",
                "--repo",
                ".",
                "--brief",
                "examples/share-link-expiration/brief.md",
            ]
        )
        == 0
    )
    started = json.loads(capsys.readouterr().out)
    assert started["state"] == "AWAITING_OWNER"
    assert started["agent_backend"] == "scripted"

    run_id = started["run_id"]
    assert main(["answer", run_id, "--option", "PRESERVE_EXISTING"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "READY_TO_RESUME"

    assert main(["resume", run_id]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "COMPLETED"
    assert completed["owner_option"] == "PRESERVE_EXISTING"
    assert completed["agent_backend"] == "scripted"


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
        agent_backend=AgentBackend.SCRIPTED,
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
