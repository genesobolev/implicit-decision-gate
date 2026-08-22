"""Opt-in real-model and PostgreSQL end-to-end test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from implicit_decision_gate.agent import OpenAIModelClient
from implicit_decision_gate.gate import RolloutOption, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import PostgresProbe
from tests.test_probe import ADMIN_DSN, postgres_available

LIVE_ENABLED = bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("IDG_MODEL"))


@pytest.mark.skipif(
    not LIVE_ENABLED or not postgres_available(),
    reason="OPENAI_API_KEY, IDG_MODEL, and the PostgreSQL 17 container are required",
)
def test_live_model_can_pause_and_complete_second_attempt(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    model_name = os.environ["IDG_MODEL"]
    first = Orchestrator(
        repo_path=reference_repo,
        model_name=model_name,
        coding_client=OpenAIModelClient(api_key),
        reviewer_client=OpenAIModelClient(api_key),
        probe=PostgresProbe(ADMIN_DSN),
        worktree_root=tmp_path / "live-worktrees",
    ).start(Path("examples/share-link-expiration/brief.md"))
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
        model_name=model_name,
        coding_client=OpenAIModelClient(api_key),
        reviewer_client=OpenAIModelClient(api_key),
        probe=PostgresProbe(ADMIN_DSN),
        worktree_root=tmp_path / "live-worktrees",
    ).resume(first.run_id)
    assert completed.state is RunState.COMPLETED
    assert completed.attempts[1].probe_result is not None
    assert completed.attempts[1].probe_result.rollout_option is selected
