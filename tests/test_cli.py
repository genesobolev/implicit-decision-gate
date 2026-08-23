"""Public CLI contract test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from implicit_decision_gate.cli import main
from implicit_decision_gate.gate import EvidenceClassification, ReviewerResult
from tests.conftest import ScriptMarkerProbe


class DeterministicCodexClient:
    """Stand in for Codex at the CLI dependency boundary."""

    def propose_migration(self, prompt: str) -> str:
        if "Owner decision: PRESERVE_EXISTING" in prompt:
            return "-- PRESERVE_EXISTING"
        return "-- EXPIRE_EXISTING"

    def review_evidence(self, prompt: str) -> ReviewerResult:
        del prompt
        return ReviewerResult(
            classification=EvidenceClassification.NOT_EVIDENCED,
            evidence_quote=None,
        )


def test_cli_pauses_inspects_answers_and_resumes(
    reference_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the public workflow with Codex replaced only at the test boundary."""

    monkeypatch.chdir(reference_repo)
    monkeypatch.setattr(
        "implicit_decision_gate.cli.CodexCLIModelClient",
        DeterministicCodexClient,
    )
    monkeypatch.setattr(
        "implicit_decision_gate.cli.PostgresProbe",
        lambda _dsn: ScriptMarkerProbe(),
    )

    assert main(["start"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["state"] == "AWAITING_OWNER"
    assert "agent_backend" not in started

    run_id = started["run_id"]
    assert main(["show", run_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["state"] == "AWAITING_OWNER"
    assert shown["pending_question"]

    assert main(["answer", run_id, "--option", "PRESERVE_EXISTING"]) == 0
    answered = json.loads(capsys.readouterr().out)
    assert answered["state"] == "READY_TO_RESUME"
    assert answered["owner_option"] == "PRESERVE_EXISTING"

    assert main(["resume", run_id]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "COMPLETED"
    assert completed["owner_option"] == "PRESERVE_EXISTING"


def test_start_rejects_the_removed_backend_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["start", "--agent", "scripted"])

    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
