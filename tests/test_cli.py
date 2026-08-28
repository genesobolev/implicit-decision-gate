"""Public CLI contract test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from implicit_decision_gate.api_probe import (
    ADMINISTRATOR_ACCESS,
    CREATE_ANOTHER_EXPORT,
    OWNER_AND_ADMIN,
    OWNER_ONLY,
    REPEAT_REQUEST,
    REUSE_ACTIVE_EXPORT,
)
from implicit_decision_gate.cli import main
from implicit_decision_gate.gate import (
    EvidenceClassification,
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)
from implicit_decision_gate.probe import COMPOSE_ADMIN_DSN, EXISTING_LINK_ROLLOUT
from implicit_decision_gate.scenarios import WORKSPACE_EXPORT_AUTHORIZATION
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

    def propose_artifact(self, prompt: str) -> str:
        if "create_export" in prompt:
            if f"Authoritative owner decision for {ADMINISTRATOR_ACCESS}: {OWNER_ONLY}" in prompt:
                return f"# {OWNER_ONLY} {REUSE_ACTIVE_EXPORT}"
            return f"# {OWNER_AND_ADMIN} {CREATE_ANOTHER_EXPORT}"
        if f"Authoritative owner decision for {EXISTING_LINK_ROLLOUT}: PRESERVE_EXISTING" in prompt:
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
    probe_dsns: list[str] = []

    def build_probe(admin_dsn: str) -> ScriptMarkerProbe:
        probe_dsns.append(admin_dsn)
        return ScriptMarkerProbe()

    monkeypatch.setattr(
        "implicit_decision_gate.cli.PostgresProbe",
        build_probe,
    )

    assert main(["start"]) == 0
    assert probe_dsns == [COMPOSE_ADMIN_DSN]
    started = json.loads(capsys.readouterr().out)
    assert started["state"] == "AWAITING_OWNER"
    assert started["scenario"] == "share-link-expiration"
    assert "agent_backend" not in started
    assert [record["role"] for record in started["model_invocations"]] == [
        "CODING_AGENT",
        "EVIDENCE_REVIEWER",
    ]
    assert len(started["decision_requests"]) == 1

    run_id = started["run_id"]
    assert main(["show", run_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["state"] == "AWAITING_OWNER"
    assert shown["decision_requests"] == started["decision_requests"]
    assert "pending_question" not in shown
    decision_request = shown["decision_requests"][0]
    assert decision_request["id"] == "existing_item_sharing_link_rollout"
    assert decision_request["question"] == "What should happen to existing item-sharing links?"
    assert decision_request["observed"]["option"] == "EXPIRE_EXISTING"
    assert [option["option"] for option in decision_request["options"]] == [
        "PRESERVE_EXISTING",
        "EXPIRE_EXISTING",
    ]
    assert [option["command"] for option in decision_request["options"]] == [
        f"uv run idg answer {run_id} --decision {EXISTING_LINK_ROLLOUT} --option PRESERVE_EXISTING",
        f"uv run idg answer {run_id} --decision {EXISTING_LINK_ROLLOUT} --option EXPIRE_EXISTING",
    ]
    assert all(option["behavior"] for option in decision_request["options"])

    assert (
        main(
            [
                "answer",
                run_id,
                "--decision",
                EXISTING_LINK_ROLLOUT,
                "--option",
                "PRESERVE_EXISTING",
            ]
        )
        == 0
    )
    answered = json.loads(capsys.readouterr().out)
    assert answered["state"] == "READY_TO_RESUME"
    assert answered["owner_options"] == {EXISTING_LINK_ROLLOUT: "PRESERVE_EXISTING"}
    assert answered["decision_requests"] == []

    assert main(["resume", run_id]) == 0
    assert probe_dsns == [COMPOSE_ADMIN_DSN] * 4
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "COMPLETED"
    assert completed["owner_options"] == {EXISTING_LINK_ROLLOUT: "PRESERVE_EXISTING"}
    assert completed["decision_requests"] == []
    assert [record["attempt_number"] for record in completed["model_invocations"]] == [
        1,
        None,
        2,
    ]


def test_cli_collects_two_answers_before_one_retry(
    reference_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(reference_repo)
    monkeypatch.setattr(
        "implicit_decision_gate.cli.CodexCLIModelClient",
        DeterministicCodexClient,
    )
    monkeypatch.setattr(
        "implicit_decision_gate.cli.DockerAuthorizationProbe",
        ScriptMarkerProbe,
    )

    assert main(["start", "--scenario", WORKSPACE_EXPORT_AUTHORIZATION]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["state"] == "AWAITING_OWNER"
    assert [request["id"] for request in started["decision_requests"]] == [
        ADMINISTRATOR_ACCESS,
        REPEAT_REQUEST,
    ]
    assert [record["decision_id"] for record in started["model_invocations"]] == [
        None,
        ADMINISTRATOR_ACCESS,
        REPEAT_REQUEST,
    ]
    run_id = started["run_id"]

    assert (
        main(
            [
                "answer",
                run_id,
                "--decision",
                ADMINISTRATOR_ACCESS,
                "--option",
                OWNER_ONLY,
            ]
        )
        == 0
    )
    partially_answered = json.loads(capsys.readouterr().out)
    assert partially_answered["state"] == "AWAITING_OWNER"
    assert [request["id"] for request in partially_answered["decision_requests"]] == [
        REPEAT_REQUEST
    ]
    assert main(["resume", run_id]) == 2
    assert "resume requires READY_TO_RESUME" in capsys.readouterr().err

    assert (
        main(
            [
                "answer",
                run_id,
                "--decision",
                REPEAT_REQUEST,
                "--option",
                REUSE_ACTIVE_EXPORT,
            ]
        )
        == 0
    )
    answered = json.loads(capsys.readouterr().out)
    assert answered["state"] == "READY_TO_RESUME"
    assert answered["owner_options"] == {
        ADMINISTRATOR_ACCESS: OWNER_ONLY,
        REPEAT_REQUEST: REUSE_ACTIVE_EXPORT,
    }

    assert main(["resume", run_id]) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["state"] == "COMPLETED"
    assert len(completed["attempt_digests"]) == 2


def test_start_rejects_the_removed_backend_selector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["start", "--agent", "scripted"])

    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
