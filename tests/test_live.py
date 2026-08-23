"""Opt-in real-model and PostgreSQL end-to-end test."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from implicit_decision_gate.agent import build_coding_prompt
from implicit_decision_gate.codex_client import CodexCLIModelClient
from implicit_decision_gate.gate import RolloutOption, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import PostgresProbe
from tests.conftest import BRIEF, SCHEMA
from tests.test_probe import ADMIN_DSN, postgres_available

LIVE_ENABLED = os.environ.get("IDG_LIVE_CODEX") == "1" and shutil.which("codex") is not None


@pytest.mark.skipif(
    not LIVE_ENABLED or not postgres_available(),
    reason="IDG_LIVE_CODEX=1, an authenticated Codex CLI, and PostgreSQL 17 are required",
)
def test_live_model_honors_preserve_owner_decision() -> None:
    prompt = build_coding_prompt(
        brief=BRIEF,
        schema=SCHEMA,
        attempt_number=2,
        owner_option=RolloutOption.PRESERVE_EXISTING,
    )

    migration = CodexCLIModelClient().propose_migration(prompt)
    result = PostgresProbe(ADMIN_DSN).probe(migration, SCHEMA)

    assert result.rollout_option is RolloutOption.PRESERVE_EXISTING


@pytest.mark.skipif(
    not LIVE_ENABLED or not postgres_available(),
    reason="IDG_LIVE_CODEX=1, an authenticated Codex CLI, and PostgreSQL 17 are required",
)
def test_live_model_can_pause_and_complete_second_attempt(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    first = Orchestrator(
        repo_path=reference_repo,
        coding_client=CodexCLIModelClient(),
        reviewer_client=CodexCLIModelClient(),
        probe=PostgresProbe(ADMIN_DSN),
        worktree_root=tmp_path / "live-worktrees",
    ).start()
    assert first.state is RunState.AWAITING_OWNER
    assert first.attempts[0].probe_result is not None
    observed = first.attempts[0].probe_result.rollout_option
    selected = (
        RolloutOption.EXPIRE_EXISTING
        if observed is RolloutOption.PRESERVE_EXISTING
        else RolloutOption.PRESERVE_EXISTING
    )
    Orchestrator(repo_path=reference_repo).answer(first.run_id, selected)
    completed = Orchestrator(
        repo_path=reference_repo,
        coding_client=CodexCLIModelClient(),
        reviewer_client=CodexCLIModelClient(),
        probe=PostgresProbe(ADMIN_DSN),
        worktree_root=tmp_path / "live-worktrees",
    ).resume(first.run_id)
    assert completed.state is RunState.COMPLETED
    assert completed.attempts[1].probe_result is not None
    assert completed.attempts[1].probe_result.rollout_option is selected
