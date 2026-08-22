"""Persisted state machine, limits, and end-to-end scripted runs."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from implicit_decision_gate.agent import (
    ModelResponse,
    ModelTransportError,
    ScriptedModelClient,
)
from implicit_decision_gate.gate import (
    GateError,
    RolloutOption,
    RunState,
    RunStore,
    sha256_text,
)
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptMarkerProbe

RESUME_SCRIPT = """
import sys
from pathlib import Path

from implicit_decision_gate.agent import ModelResponse, ScriptedModelClient
from implicit_decision_gate.gate import GateError, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptMarkerProbe

try:
    run = Orchestrator(
        repo_path=Path(sys.argv[1]),
        model_name="scripted-model",
        coding_client=ScriptedModelClient(
            [
                ModelResponse.function_call(
                    "submit_migration",
                    {"sql": "-- PRESERVE_EXISTING"},
                )
            ]
        ),
        reviewer_client=ScriptedModelClient([]),
        probe=ScriptMarkerProbe(),
        worktree_root=Path(sys.argv[3]),
    ).resume(sys.argv[2])
except GateError as error:
    print(error, file=sys.stderr)
    raise SystemExit(2) from error
raise SystemExit(0 if run.state is RunState.COMPLETED else 3)
"""


def submit(sql: str, call_id: str = "submit") -> ModelResponse:
    """Create a scripted migration submission."""

    return ModelResponse.function_call(
        "submit_migration",
        {"sql": sql},
        call_id=call_id,
    )


def not_evidenced(explanation: str = "") -> ModelResponse:
    """Create the expected evidence result, optionally with ignored prose."""

    return ModelResponse.text(
        json.dumps(
            {
                "classification": "NOT_EVIDENCED",
                "evidence_quote": None,
                "explanation": explanation,
            }
        )
    )


def orchestrator(
    repo: Path,
    worktree_root: Path,
    coding_client: ScriptedModelClient,
    reviewer_client: ScriptedModelClient,
    probe: ScriptMarkerProbe,
) -> Orchestrator:
    """Build a fully scripted controller."""

    return Orchestrator(
        repo_path=repo,
        model_name="scripted-model",
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


def test_awaiting_owner_persists_and_blocks_model_calls(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    first_client = ScriptedModelClient([submit("-- EXPIRE_EXISTING")])
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        first_client,
        ScriptedModelClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert run.state is RunState.AWAITING_OWNER

    blocked_client = ScriptedModelClient([submit("-- PRESERVE_EXISTING")])
    separate_process = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        blocked_client,
        ScriptedModelClient([]),
        ScriptMarkerProbe(),
    )
    with pytest.raises(GateError, match="READY_TO_RESUME"):
        separate_process.resume(run.run_id)
    assert blocked_client.requests == []
    persisted = RunStore(reference_repo).load(run.run_id)
    assert persisted.state is RunState.AWAITING_OWNER
    assert persisted.coding_attempt_count == 1


def test_concurrent_answers_accept_exactly_one_owner_decision(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedModelClient([submit("-- EXPIRE_EXISTING")]),
        ScriptedModelClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    store = RunStore(reference_repo)
    commands = [
        [
            sys.executable,
            "-m",
            "implicit_decision_gate.cli",
            "answer",
            run.run_id,
            "--option",
            option.value,
        ]
        for option in (
            RolloutOption.PRESERVE_EXISTING,
            RolloutOption.EXPIRE_EXISTING,
        )
    ]

    with store.lock(run.run_id):
        processes = [
            subprocess.Popen(
                command,
                cwd=reference_repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for command in commands
        ]
        assert all(process.poll() is None for process in processes)
    outputs = wait_for_processes(processes)

    assert sorted(process.wait() for process in processes) == [0, 2]
    success_index = next(
        index for index, process in enumerate(processes) if process.returncode == 0
    )
    successful_answer = json.loads(outputs[success_index][0])
    persisted = store.load(run.run_id)
    assert persisted.state is RunState.READY_TO_RESUME
    assert persisted.owner_answer_count == 1
    assert persisted.owner_option == RolloutOption(successful_answer["owner_option"])
    assert "answer requires AWAITING_OWNER" in "".join(stderr for _, stderr in outputs)


def test_concurrent_resumes_execute_attempt_two_once(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    run = orchestrator(
        reference_repo,
        tmp_path / "first-worktree",
        ScriptedModelClient([submit("-- EXPIRE_EXISTING")]),
        ScriptedModelClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
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
    assert persisted.coding_attempt_count == 2
    assert len(persisted.attempts) == 2
    assert "resume requires READY_TO_RESUME" in "".join(stderr for _, stderr in outputs)


def test_scripted_run_accepts_opposite_option_and_completes(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    first_sql = "-- FIRST_MIGRATION_SECRET EXPIRE_EXISTING"
    reviewer_secret = "REVIEWER_SECRET"
    first = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedModelClient([submit(first_sql)]),
        ScriptedModelClient([not_evidenced(reviewer_secret)]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert first.state is RunState.AWAITING_OWNER

    answer_controller = Orchestrator(repo_path=reference_repo)
    answered = answer_controller.answer(first.run_id, RolloutOption.PRESERVE_EXISTING)
    assert answered.state is RunState.READY_TO_RESUME
    second_client = ScriptedModelClient([submit("-- PRESERVE_EXISTING")])
    completed = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        second_client,
        ScriptedModelClient([]),
        ScriptMarkerProbe(),
    ).resume(first.run_id)

    assert completed.state is RunState.COMPLETED
    assert completed.owner_answer_count == 1
    assert completed.coding_attempt_count == 2
    assert completed.attempts[0].base_commit == completed.base_commit
    assert completed.attempts[1].base_commit == completed.base_commit
    assert completed.attempts[0].worktree_path != completed.attempts[1].worktree_path
    assert all(attempt.clean_start_verified for attempt in completed.attempts)
    assert completed.attempts[0].migration_digest == sha256_text(f"{first_sql}\n")
    assert completed.attempts[1].migration_digest == sha256_text("-- PRESERVE_EXISTING\n")
    assert completed.attempts[0].migration_contents == f"{first_sql}\n"
    immutable_path = Path(completed.attempts[0].migration_path or "")
    assert stat.S_IMODE(immutable_path.stat().st_mode) == 0o444
    assert completed.decision_ledger is not None
    assert completed.decision_ledger.state is RunState.COMPLETED

    second_context = json.dumps(second_client.requests)
    assert "PRESERVE_EXISTING" in second_context
    assert "FIRST_MIGRATION_SECRET" not in second_context
    assert reviewer_secret not in second_context
    assert "NOT_EVIDENCED" not in second_context
    first_worktree = Path(completed.attempts[0].worktree_path)
    second_worktree = Path(completed.attempts[1].worktree_path)
    assert list((first_worktree / "examples/share-link-expiration/migrations").glob("*.sql"))
    assert (
        len(list((second_worktree / "examples/share-link-expiration/migrations").glob("*.sql")))
        == 1
    )
    assert "FIRST_MIGRATION_SECRET" not in next(
        (second_worktree / "examples/share-link-expiration/migrations").glob("*.sql")
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("second_sql", ["-- EXPIRE_EXISTING", "-- OTHER"])
def test_second_attempt_mismatch_or_unmodeled_fails_once(
    reference_repo: Path,
    tmp_path: Path,
    second_sql: str,
) -> None:
    first = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedModelClient([submit("-- EXPIRE_EXISTING")]),
        ScriptedModelClient([not_evidenced()]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    Orchestrator(repo_path=reference_repo).answer(
        first.run_id,
        RolloutOption.PRESERVE_EXISTING,
    )
    second_client = ScriptedModelClient([submit(second_sql)])
    reviewer_client = ScriptedModelClient([])
    failed = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        second_client,
        reviewer_client,
        ScriptMarkerProbe(),
    ).resume(first.run_id)
    assert failed.state is RunState.FAILED
    assert failed.coding_attempt_count == 2
    assert failed.owner_answer_count == 1
    assert len(second_client.requests) == 1
    assert reviewer_client.requests == []
    with pytest.raises(GateError, match="AWAITING_OWNER"):
        Orchestrator(repo_path=reference_repo).answer(
            first.run_id,
            RolloutOption.EXPIRE_EXISTING,
        )


def test_tool_step_limit_fails_run(reference_repo: Path, tmp_path: Path) -> None:
    responses = [
        ModelResponse.function_call(
            "read_file",
            {"path": "examples/share-link-expiration/schema.sql"},
            call_id=f"read-{index}",
        )
        for index in range(5)
    ]
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedModelClient(responses),
        ScriptedModelClient([]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert run.state is RunState.FAILED
    assert run.attempts[0].tool_step_count == 4
    assert "Tool-step limit" in (run.error or "")


def test_transport_retry_limit_fails_run(reference_repo: Path, tmp_path: Path) -> None:
    coding_client = ScriptedModelClient(
        [
            ModelTransportError("first transport failure"),
            ModelTransportError("second transport failure"),
        ]
    )
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        coding_client,
        ScriptedModelClient([]),
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert run.state is RunState.FAILED
    assert run.attempts[0].transport_retry_count == 1
    assert len(run.attempts[0].model_requests) == 2
    assert "transport retry limit" in (run.error or "")


def test_unmodeled_first_attempt_fails_without_review(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    reviewer_client = ScriptedModelClient([])
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedModelClient([submit("-- OTHER")]),
        reviewer_client,
        ScriptMarkerProbe(),
    ).start(Path("examples/share-link-expiration/brief.md"))
    assert run.state is RunState.FAILED
    assert reviewer_client.requests == []
    assert run.decision_ledger is None
