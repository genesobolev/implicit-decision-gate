"""Opt-in real-model and PostgreSQL end-to-end test."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from implicit_decision_gate.agent import build_coding_prompt
from implicit_decision_gate.api_probe import DockerAuthorizationProbe
from implicit_decision_gate.codex_client import (
    CODEX_MODEL,
    CODEX_REASONING_EFFORT,
    CodexCLIModelClient,
)
from implicit_decision_gate.gate import RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import (
    COMPOSE_ADMIN_DSN,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
    PostgresProbe,
)
from implicit_decision_gate.scenarios import (
    SHARE_LINK_EXPIRATION,
    scenario_registry,
)
from tests.conftest import BRIEF, SCHEMA
from tests.test_probe import postgres_available

LIVE_ENABLED = os.environ.get("IDG_LIVE_CODEX") == "1" and shutil.which("codex") is not None
LIVE_SCENARIOS = scenario_registry(
    PostgresProbe(COMPOSE_ADMIN_DSN),
    DockerAuthorizationProbe(),
)
SHARE_LINK_SCENARIO = LIVE_SCENARIOS[SHARE_LINK_EXPIRATION]


@pytest.mark.skipif(
    not LIVE_ENABLED or not postgres_available(),
    reason="IDG_LIVE_CODEX=1, an authenticated Codex CLI, and PostgreSQL 17 are required",
)
def test_live_model_honors_preserve_owner_decision() -> None:
    prompt = build_coding_prompt(
        scenario=SHARE_LINK_SCENARIO,
        brief=BRIEF,
        context=SCHEMA,
        attempt_number=2,
        owner_option=PRESERVE_EXISTING,
    )

    artifact = CodexCLIModelClient().propose_artifact(prompt)
    result = PostgresProbe(COMPOSE_ADMIN_DSN).observe(artifact, SCHEMA)

    assert result.outcome == PRESERVE_EXISTING


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
        scenarios=LIVE_SCENARIOS,
        coding_client=CodexCLIModelClient(),
        reviewer_client=CodexCLIModelClient(),
        worktree_root=tmp_path / "live-worktrees",
    ).start()
    assert first.state is RunState.AWAITING_OWNER
    assert all(record.model == CODEX_MODEL for record in first.model_invocations)
    assert all(
        record.reasoning_effort == CODEX_REASONING_EFFORT for record in first.model_invocations
    )
    assert first.attempts[0].observation is not None
    observed = first.attempts[0].observation.outcome
    selected = EXPIRE_EXISTING if observed == PRESERVE_EXISTING else PRESERVE_EXISTING
    Orchestrator(repo_path=reference_repo, scenarios=LIVE_SCENARIOS).answer(
        first.run_id,
        selected,
    )
    completed = Orchestrator(
        repo_path=reference_repo,
        scenarios=LIVE_SCENARIOS,
        coding_client=CodexCLIModelClient(),
        reviewer_client=CodexCLIModelClient(),
        worktree_root=tmp_path / "live-worktrees",
    ).resume(first.run_id)
    assert completed.state is RunState.COMPLETED
    assert completed.attempts[1].observation is not None
    assert completed.attempts[1].observation.outcome == selected
    assert len(completed.model_invocations) == 3
