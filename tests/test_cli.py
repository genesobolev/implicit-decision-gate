"""Public CLI contract test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from implicit_decision_gate.cli import main
from tests.conftest import ScriptMarkerProbe


def test_scripted_cli_pauses_inspects_answers_and_resumes(
    reference_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise the credential-free happy path from the repository root."""

    monkeypatch.chdir(reference_repo)
    monkeypatch.setattr(
        "implicit_decision_gate.cli.PostgresProbe",
        lambda _dsn: ScriptMarkerProbe(),
    )

    assert main(["start"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["state"] == "AWAITING_OWNER"
    assert started["agent_backend"] == "scripted"

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
    assert completed["agent_backend"] == "scripted"
