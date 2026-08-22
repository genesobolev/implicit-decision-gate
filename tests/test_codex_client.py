"""Local Codex CLI adapter tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from implicit_decision_gate.agent import AgentError, ModelTransportError
from implicit_decision_gate.codex_client import CodexCLIModelClient


def coding_request() -> dict[str, Any]:
    """Build the normalized coding request used by adapter tests."""

    return {
        "input": [{"role": "user", "content": "Create a migration."}],
        "tools": [
            {"name": "read_file"},
            {"name": "submit_migration"},
        ],
    }


def test_codex_tool_output_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "tool_name": "submit_migration",
                    "path": "",
                    "sql": "SELECT 1;",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", fake_run)

    response = CodexCLIModelClient().complete(
        coding_request(),
        working_directory=tmp_path,
    )

    command = captured["command"]
    assert command[:2] == ["/usr/local/bin/codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("-C") + 1] == str(tmp_path)
    assert command[-1] == "-"
    assert "--model" not in command
    assert "Create a migration." in captured["prompt"]
    assert captured["schema"]["properties"]["tool_name"]["enum"] == [
        "read_file",
        "submit_migration",
    ]
    assert response.tool_calls[0].name == "submit_migration"
    assert json.loads(response.tool_calls[0].arguments) == {"sql": "SELECT 1;"}


def test_codex_reviewer_output_uses_fresh_non_repo_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
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

    response = CodexCLIModelClient().complete(
        {"input": [{"role": "user", "content": "Review evidence."}]}
    )

    assert "--skip-git-repo-check" in captured_command
    assert json.loads(response.output_text) == {
        "classification": "NOT_EVIDENCED",
        "evidence_quote": None,
    }


def test_codex_missing_binary_has_scripted_fallback_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(AgentError, match="--agent scripted"):
        CodexCLIModelClient().complete(coding_request())


def test_codex_timeout_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("codex", 1)

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/codex")
    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(ModelTransportError, match="timed out"):
        CodexCLIModelClient(timeout_seconds=1).complete(coding_request())


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
        CodexCLIModelClient().complete(coding_request())
