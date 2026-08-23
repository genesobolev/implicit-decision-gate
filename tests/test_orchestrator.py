"""Durable gate behavior across isolated coding attempts."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

from implicit_decision_gate.gate import (
    EvidenceClassification,
    GateError,
    ReviewerResult,
    RolloutOption,
    RunState,
    RunStore,
    sha256_text,
)
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import (
    ScriptedCodingClient,
    ScriptedReviewerClient,
    ScriptMarkerProbe,
    run_git,
)

RESUME_SCRIPT = """
import sys
from pathlib import Path

from implicit_decision_gate.gate import GateError, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptedCodingClient, ScriptMarkerProbe

try:
    run = Orchestrator(
        repo_path=Path(sys.argv[1]),
        coding_client=ScriptedCodingClient(["-- PRESERVE_EXISTING"]),
        probe=ScriptMarkerProbe(),
        worktree_root=Path(sys.argv[3]),
    ).resume(sys.argv[2])
except GateError as error:
    print(error, file=sys.stderr)
    raise SystemExit(2) from error
raise SystemExit(0 if run.state is RunState.COMPLETED else 3)
"""


def not_evidenced() -> ReviewerResult:
    """Return the expected result for the intentionally incomplete brief."""

    return ReviewerResult(
        classification=EvidenceClassification.NOT_EVIDENCED,
        evidence_quote=None,
    )


def orchestrator(
    repo: Path,
    worktree_root: Path,
    coding_client: ScriptedCodingClient,
    reviewer_client: ScriptedReviewerClient,
    probe: ScriptMarkerProbe,
) -> Orchestrator:
    """Build a fully scripted controller."""

    return Orchestrator(
        repo_path=repo,
        coding_client=coding_client,
        reviewer_client=reviewer_client,
        probe=probe,
        worktree_root=worktree_root,
    )


def wait_for_processes(
    processes: list[subprocess.Popen[str]],
) -> list[tuple[str, str]]:
    """Collect subprocess output and clean up every child on timeout."""

    try:
        return [process.communicate(timeout=30) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_awaiting_owner_is_durable_and_blocks_more_model_work(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    coding = ScriptedCodingClient(["-- EXPIRE_EXISTING"])
    reviewer = ScriptedReviewerClient([not_evidenced()])
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        coding,
        reviewer,
        ScriptMarkerProbe(),
    ).start()

    assert run.state is RunState.AWAITING_OWNER
    assert run.decision is not None
    assert run.decision.observed is RolloutOption.EXPIRE_EXISTING
    assert run.decision.selected is None
    assert run.attempts[0].coding_prompt == coding.prompts[0]
    assert run.reviewer_prompt == reviewer.prompts[0]

    blocked_client = ScriptedCodingClient(["-- PRESERVE_EXISTING"])
    separate_process = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        blocked_client,
        ScriptedReviewerClient([]),
        ScriptMarkerProbe(),
    )
    with pytest.raises(GateError, match="READY_TO_RESUME"):
        separate_process.resume(run.run_id)
    assert blocked_client.prompts == []
    persisted = RunStore(reference_repo).load(run.run_id)
    assert persisted.state is RunState.AWAITING_OWNER
    assert len(persisted.attempts) == 1


def test_start_reads_the_brief_from_the_pinned_commit(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    brief_path = reference_repo / "examples/share-link-expiration/brief.md"
    brief_path.write_text("uncommitted replacement brief\n", encoding="utf-8")
    coding = ScriptedCodingClient(["-- EXPIRE_EXISTING"])

    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        coding,
        ScriptedReviewerClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start()

    assert "uncommitted replacement brief" not in run.original_brief
    assert run.original_brief in coding.prompts[0]


def test_concurrent_resumes_execute_attempt_two_once(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    run = orchestrator(
        reference_repo,
        tmp_path / "first-worktree",
        ScriptedCodingClient(["-- EXPIRE_EXISTING"]),
        ScriptedReviewerClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start()
    Orchestrator(repo_path=reference_repo).answer(
        run.run_id,
        RolloutOption.PRESERVE_EXISTING,
    )
    store = RunStore(reference_repo)
    command = [
        sys.executable,
        "-c",
        RESUME_SCRIPT,
        str(reference_repo),
        run.run_id,
        str(tmp_path / "second-worktrees"),
    ]

    with store.lock(run.run_id):
        processes = [
            subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        assert all(process.poll() is None for process in processes)
    outputs = wait_for_processes(processes)

    assert sorted(process.wait() for process in processes) == [0, 2]
    persisted = store.load(run.run_id)
    assert persisted.state is RunState.COMPLETED
    assert len(persisted.attempts) == 2
    assert "resume requires READY_TO_RESUME" in "".join(stderr for _, stderr in outputs)


def test_owner_decision_regenerates_in_a_clean_context(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    first_sql = "-- FIRST_MIGRATION_SECRET EXPIRE_EXISTING"
    worktrees = tmp_path / "worktrees"
    first_client = ScriptedCodingClient([first_sql])
    first = orchestrator(
        reference_repo,
        worktrees,
        first_client,
        ScriptedReviewerClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start()

    answered = Orchestrator(repo_path=reference_repo).answer(
        first.run_id,
        RolloutOption.PRESERVE_EXISTING,
    )
    assert answered.state is RunState.READY_TO_RESUME
    assert answered.decision is not None
    assert answered.decision.selected is RolloutOption.PRESERVE_EXISTING
    assert answered.decision.answered_at is not None

    second_client = ScriptedCodingClient(["-- PRESERVE_EXISTING"])
    completed = orchestrator(
        reference_repo,
        worktrees,
        second_client,
        ScriptedReviewerClient([]),
        ScriptMarkerProbe(),
    ).resume(first.run_id)

    assert completed.state is RunState.COMPLETED
    assert len(completed.attempts) == 2
    assert all(attempt.clean_start_verified for attempt in completed.attempts)
    assert completed.attempts[0].worktree_path != completed.attempts[1].worktree_path
    assert completed.attempts[0].migration_digest == sha256_text(f"{first_sql}\n")
    assert completed.attempts[1].migration_digest == sha256_text("-- PRESERVE_EXISTING\n")
    assert completed.attempts[1].coding_prompt == second_client.prompts[0]

    first_artifact = RunStore(reference_repo).run_path(first.run_id) / "attempt-1.sql"
    assert first_artifact.read_text(encoding="utf-8") == f"{first_sql}\n"
    assert stat.S_IMODE(first_artifact.stat().st_mode) == 0o444

    second_prompt = second_client.prompts[0]
    assert "Owner decision: PRESERVE_EXISTING" in second_prompt
    assert "FIRST_MIGRATION_SECRET" not in second_prompt
    assert "NOT_EVIDENCED" not in second_prompt

    first_worktree = Path(completed.attempts[0].worktree_path)
    second_worktree = Path(completed.attempts[1].worktree_path)
    assert run_git(first_worktree, "rev-parse", "HEAD") == completed.base_commit
    assert run_git(second_worktree, "rev-parse", "HEAD") == completed.base_commit
    assert (
        len(list((first_worktree / "examples/share-link-expiration/migrations").glob("*.sql"))) == 1
    )
    second_migrations = list(
        (second_worktree / "examples/share-link-expiration/migrations").glob("*.sql")
    )
    assert len(second_migrations) == 1
    assert "FIRST_MIGRATION_SECRET" not in second_migrations[0].read_text(encoding="utf-8")


@pytest.mark.parametrize("second_sql", ["-- EXPIRE_EXISTING", "-- OTHER"])
def test_second_attempt_mismatch_or_unmodeled_fails(
    reference_repo: Path,
    tmp_path: Path,
    second_sql: str,
) -> None:
    first = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedCodingClient(["-- EXPIRE_EXISTING"]),
        ScriptedReviewerClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start()
    Orchestrator(repo_path=reference_repo).answer(
        first.run_id,
        RolloutOption.PRESERVE_EXISTING,
    )
    second_client = ScriptedCodingClient([second_sql])
    failed = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        second_client,
        ScriptedReviewerClient([]),
        ScriptMarkerProbe(),
    ).resume(first.run_id)

    assert failed.state is RunState.FAILED
    assert len(failed.attempts) == 2
    assert len(second_client.prompts) == 1
    with pytest.raises(GateError, match="AWAITING_OWNER"):
        Orchestrator(repo_path=reference_repo).answer(
            first.run_id,
            RolloutOption.EXPIRE_EXISTING,
        )


def test_unmodeled_first_attempt_fails_without_review(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    reviewer = ScriptedReviewerClient([])
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedCodingClient(["-- OTHER"]),
        reviewer,
        ScriptMarkerProbe(),
    ).start()

    assert run.state is RunState.FAILED
    assert reviewer.prompts == []
    assert run.decision is None
