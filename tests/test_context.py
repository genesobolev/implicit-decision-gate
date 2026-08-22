"""Coding-tool sandbox and attempt-context isolation tests."""

from __future__ import annotations

from pathlib import Path

from implicit_decision_gate.agent import (
    CodingAgent,
    ModelResponse,
    ScriptedModelClient,
)
from implicit_decision_gate.gate import AgentBackend, AttemptRecord, RolloutOption


def attempt(worktree: Path) -> AttemptRecord:
    """Build a trace record for a direct coding-agent test."""

    return AttemptRecord(
        number=1,
        worktree_path=str(worktree),
        base_commit="a" * 40,
        clean_start_verified=True,
        agent_backend=AgentBackend.SCRIPTED,
    )


def test_read_file_rejects_paths_outside_allowlist(tmp_path: Path) -> None:
    allowed = tmp_path / "examples" / "share-link-expiration"
    (allowed / "migrations").mkdir(parents=True)
    (allowed / "schema.sql").write_text("SELECT 1;\n", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    client = ScriptedModelClient(
        [
            ModelResponse.function_call(
                "read_file",
                {"path": "secret.txt"},
                call_id="outside",
            ),
            ModelResponse.function_call(
                "submit_migration",
                {"sql": "-- PRESERVE_EXISTING"},
                call_id="submit",
            ),
        ]
    )
    trace = attempt(tmp_path)
    proposal = CodingAgent(client).propose(
        brief="brief",
        attempt=trace,
        worktree_path=tmp_path,
        run_id="f" * 32,
        owner_option=None,
        persist=lambda: None,
    )
    assert proposal.migration == "-- PRESERVE_EXISTING"
    assert "error" in trace.tool_calls[0]["output"]
    assert "secret" not in trace.tool_calls[0]["output"]


def test_attempt_two_prompt_contains_only_brief_and_owner_decision(tmp_path: Path) -> None:
    allowed = tmp_path / "examples" / "share-link-expiration" / "migrations"
    allowed.mkdir(parents=True)
    client = ScriptedModelClient(
        [
            ModelResponse.function_call(
                "submit_migration",
                {"sql": "-- EXPIRE_EXISTING"},
            )
        ]
    )
    trace = AttemptRecord(
        number=2,
        worktree_path=str(tmp_path),
        base_commit="a" * 40,
        clean_start_verified=True,
        agent_backend=AgentBackend.SCRIPTED,
    )
    CodingAgent(client).propose(
        brief="ORIGINAL_BRIEF",
        attempt=trace,
        worktree_path=tmp_path,
        run_id="e" * 32,
        owner_option=RolloutOption.EXPIRE_EXISTING,
        persist=lambda: None,
    )
    request = str(client.requests[0])
    assert "ORIGINAL_BRIEF" in request
    assert "EXPIRE_EXISTING" in request
    assert "first migration" not in request.lower()
    assert "reviewer" not in request.lower()
    assert "modify attempt one" not in request.lower()
