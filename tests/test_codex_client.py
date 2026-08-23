"""Local Codex CLI adapter tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from implicit_decision_gate.agent import AgentError
from implicit_decision_gate.codex_client import CodexCLIModelClient
from implicit_decision_gate.gate import EvidenceClassification


def test_codex_returns_one_structured_sql_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        captured["cwd"] = kwargs["cwd"]
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"sql": "SELECT 1;"}),
            stderr="",
        )

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexCLIModelClient().propose_migration("Create a migration.")

    command = captured["command"]
    assert command[:2] == ["/usr/local/bin/codex", "exec"]
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in command
    assert "-C" not in command
    assert Path(captured["cwd"]).name.startswith("idg-codex-")
    assert command[-1] == "-"
    assert "--model" not in command
    assert captured["prompt"] == "Create a migration."
    assert captured["schema"] == {
        "type": "object",
        "properties": {"sql": {"type": "string"}},
        "required": ["sql"],
        "additionalProperties": False,
    }
    assert result == "SELECT 1;"


def test_codex_reviewer_uses_fresh_non_repo_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "classification": "NOT_EVIDENCED",
                    "evidence_quote": "",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexCLIModelClient().review_evidence("Review evidence.")

    assert "--skip-git-repo-check" in captured["command"]
    assert "-C" not in captured["command"]
    assert captured["prompt"] == "Review evidence."
    assert result.classification is EvidenceClassification.NOT_EVIDENCED
    assert result.evidence_quote is None


def test_codex_missing_binary_has_scripted_fallback_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(AgentError, match="--agent scripted"):
        CodexCLIModelClient().propose_migration("prompt")


def test_codex_timeout_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("codex", 1)

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(AgentError, match="timed out"):
        CodexCLIModelClient(timeout_seconds=1).propose_migration("prompt")


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (
            subprocess.CompletedProcess(
                ["codex"],
                1,
                stdout="",
                stderr="Not logged in",
            ),
            "not authenticated",
        ),
        (
            subprocess.CompletedProcess(
                ["codex"],
                0,
                stdout="not-json",
                stderr="",
            ),
            "invalid structured output",
        ),
        (
            subprocess.CompletedProcess(
                ["codex"],
                0,
                stdout=json.dumps({"sql": ""}),
                stderr="",
            ),
            "empty migration",
        ),
    ],
)
def test_codex_failures_are_clear(
    completed: subprocess.CompletedProcess[str],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: completed)

    with pytest.raises(AgentError, match=message):
        CodexCLIModelClient().propose_migration("prompt")
