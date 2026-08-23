"""Public CLI contract test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from implicit_decision_gate.cli import main
from implicit_decision_gate.gate import (
    EvidenceClassification,
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)
from tests.conftest import ScriptMarkerProbe


class DeterministicCodexClient:
    """Stand in for Codex at the CLI dependency boundary."""

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Return deterministic model provenance."""

        return ModelInvocationRecord(
            role=role,
            attempt_number=attempt_number,
            model="deterministic-test-client",
            reasoning_effort="deterministic",
            codex_cli_version="not-applicable",
        )

    def propose_migration(self, prompt: str) -> str:
        if "Authoritative owner decision: PRESERVE_EXISTING" in prompt:
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
    assert [record["role"] for record in started["model_invocations"]] == [
        "CODING_AGENT",
        "EVIDENCE_REVIEWER",
    ]
    assert started["decision_request"] is not None

    run_id = started["run_id"]
    assert main(["show", run_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["state"] == "AWAITING_OWNER"
    assert shown["decision_request"] == started["decision_request"]
    assert "pending_question" not in shown
    decision_request = shown["decision_request"]
    assert decision_request["id"] == "existing_item_sharing_link_rollout"
    assert decision_request["question"] == "What should happen to existing item-sharing links?"
    assert decision_request["observed"]["option"] == "EXPIRE_EXISTING"
    assert [option["option"] for option in decision_request["options"]] == [
        "PRESERVE_EXISTING",
        "EXPIRE_EXISTING",
    ]
    assert [option["command"] for option in decision_request["options"]] == [
        f"uv run idg answer {run_id} --option PRESERVE_EXISTING",
        f"uv run idg answer {run_id} --option EXPIRE_EXISTING",
    ]
    assert all(option["behavior"] for option in decision_request["options"])

    assert main(["answer", run_id, "--option", "PRESERVE_EXISTING"]) == 0
    answered = json.loads(capsys.readouterr().out)
    assert answered["state"] == "READY_TO_RESUME"
    assert answered["owner_option"] == "PRESERVE_EXISTING"
    assert answered["decision_request"] is None

    assert main(["resume", run_id]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "COMPLETED"
    assert completed["owner_option"] == "PRESERVE_EXISTING"
    assert completed["decision_request"] is None
    assert [record["attempt_number"] for record in completed["model_invocations"]] == [
        1,
        None,
        2,
    ]


def test_start_rejects_the_removed_backend_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["start", "--agent", "scripted"])

    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
