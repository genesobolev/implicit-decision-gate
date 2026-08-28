"""Durable gate behavior across isolated coding attempts."""

from __future__ import annotations

import stat
import subprocess
import sys
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
from implicit_decision_gate.gate import (
    EvidenceClassification,
    GateError,
    ModelRole,
    ReviewerResult,
    RunState,
    RunStore,
    sha256_text,
)
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import (
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
)
from implicit_decision_gate.scenario import ObservationResult
from implicit_decision_gate.scenarios import (
    WORKSPACE_EXPORT_AUTHORIZATION,
    scenario_registry,
)
from tests.conftest import (
    ScriptedCodingClient,
    ScriptedReviewerClient,
    ScriptMarkerProbe,
    run_git,
    scripted_scenarios,
)

RESUME_SCRIPT = """
import sys
from pathlib import Path

from implicit_decision_gate.gate import GateError, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from tests.conftest import ScriptedCodingClient, ScriptMarkerProbe, scripted_scenarios

try:
    observer = ScriptMarkerProbe()
    run = Orchestrator(
        repo_path=Path(sys.argv[1]),
        scenarios=scripted_scenarios(observer),
        coding_client=ScriptedCodingClient(["-- PRESERVE_EXISTING"]),
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


class FixedOutcomeProbe:
    """Return one exact outcome mapping for boundary tests."""

    def __init__(self, outcomes: dict[str, str]) -> None:
        self.outcomes = outcomes

    def observe(self, artifact: str, context: str) -> ObservationResult:
        del artifact, context
        return ObservationResult(outcomes=self.outcomes)


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
        scenarios=scripted_scenarios(probe),
        coding_client=coding_client,
        reviewer_client=reviewer_client,
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
    assert len(run.decisions) == 1
    assert run.decisions[0].observed == EXPIRE_EXISTING
    assert run.decisions[0].selected is None
    assert run.attempts[0].coding_prompt == coding.prompts[0]
    assert run.decisions[0].reviewer_prompt == reviewer.prompts[0]
    assert run.decisions[0].reviewer_result == not_evidenced()
    assert [invocation.role for invocation in run.model_invocations] == [
        ModelRole.CODING_AGENT,
        ModelRole.EVIDENCE_REVIEWER,
    ]
    assert run.model_invocations[0].attempt_number == 1
    assert run.model_invocations[1].attempt_number is None
    assert run.model_invocations[1].decision_id == EXISTING_LINK_ROLLOUT

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
    observer = ScriptMarkerProbe()
    Orchestrator(
        repo_path=reference_repo,
        scenarios=scripted_scenarios(observer),
    ).answer(
        run.run_id,
        EXISTING_LINK_ROLLOUT,
        PRESERVE_EXISTING,
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

    observer = ScriptMarkerProbe()
    answered = Orchestrator(
        repo_path=reference_repo,
        scenarios=scripted_scenarios(observer),
    ).answer(
        first.run_id,
        EXISTING_LINK_ROLLOUT,
        PRESERVE_EXISTING,
    )
    assert answered.state is RunState.READY_TO_RESUME
    assert answered.decisions[0].selected == PRESERVE_EXISTING
    assert answered.decisions[0].answered_at is not None

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
    assert completed.attempts[0].artifact_digest == sha256_text(f"{first_sql}\n")
    assert completed.attempts[1].artifact_digest == sha256_text("-- PRESERVE_EXISTING\n")
    assert completed.attempts[1].coding_prompt == second_client.prompts[0]
    assert [invocation.role for invocation in completed.model_invocations] == [
        ModelRole.CODING_AGENT,
        ModelRole.EVIDENCE_REVIEWER,
        ModelRole.CODING_AGENT,
    ]
    assert completed.model_invocations[-1].attempt_number == 2

    first_artifact = RunStore(reference_repo).run_path(first.run_id) / "attempt-1.sql"
    assert first_artifact.read_text(encoding="utf-8") == f"{first_sql}\n"
    assert stat.S_IMODE(first_artifact.stat().st_mode) == 0o444

    second_prompt = second_client.prompts[0]
    assert (
        f"Authoritative owner decision for {EXISTING_LINK_ROLLOUT}: PRESERVE_EXISTING"
        in second_prompt
    )
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


def test_two_decisions_are_answered_before_one_clean_retry(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    first_artifact = f"# FIRST_SECRET {OWNER_AND_ADMIN} {CREATE_ANOTHER_EXPORT}"
    second_artifact = f"# {OWNER_ONLY} {REUSE_ACTIVE_EXPORT}"
    coding = ScriptedCodingClient([first_artifact, second_artifact])
    controller = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        coding,
        ScriptedReviewerClient([not_evidenced(), not_evidenced()]),
        ScriptMarkerProbe(),
    )

    run = controller.start(WORKSPACE_EXPORT_AUTHORIZATION)

    assert run.state is RunState.AWAITING_OWNER
    assert [decision.decision_id for decision in run.decisions] == [
        ADMINISTRATOR_ACCESS,
        REPEAT_REQUEST,
    ]
    assert [invocation.decision_id for invocation in run.model_invocations] == [
        None,
        ADMINISTRATOR_ACCESS,
        REPEAT_REQUEST,
    ]

    partially_answered = controller.answer(run.run_id, ADMINISTRATOR_ACCESS, OWNER_ONLY)
    assert partially_answered.state is RunState.AWAITING_OWNER
    with pytest.raises(GateError, match="already answered"):
        controller.answer(run.run_id, ADMINISTRATOR_ACCESS, OWNER_ONLY)
    with pytest.raises(GateError, match="READY_TO_RESUME"):
        controller.resume(run.run_id)

    answered = controller.answer(run.run_id, REPEAT_REQUEST, REUSE_ACTIVE_EXPORT)
    assert answered.state is RunState.READY_TO_RESUME
    completed = controller.resume(run.run_id)

    assert completed.state is RunState.COMPLETED
    assert len(completed.attempts) == 2
    assert [decision.selected for decision in completed.decisions] == [
        OWNER_ONLY,
        REUSE_ACTIVE_EXPORT,
    ]
    second_prompt = coding.prompts[1]
    assert f"Authoritative owner decision for {ADMINISTRATOR_ACCESS}: {OWNER_ONLY}" in second_prompt
    assert (
        f"Authoritative owner decision for {REPEAT_REQUEST}: {REUSE_ACTIVE_EXPORT}" in second_prompt
    )
    assert "FIRST_SECRET" not in second_prompt
    assert completed.decisions[0].reviewer_prompt not in second_prompt
    assert [invocation.role for invocation in completed.model_invocations] == [
        ModelRole.CODING_AGENT,
        ModelRole.EVIDENCE_REVIEWER,
        ModelRole.EVIDENCE_REVIEWER,
        ModelRole.CODING_AGENT,
    ]


@pytest.mark.parametrize(
    ("second_administrator", "expected_state"),
    [
        (OWNER_ONLY, RunState.COMPLETED),
        (OWNER_AND_ADMIN, RunState.FAILED),
    ],
)
def test_retry_verifies_supported_outcome_while_honoring_owner_answer(
    reference_repo: Path,
    tmp_path: Path,
    second_administrator: str,
    expected_state: RunState,
) -> None:
    coding = ScriptedCodingClient(
        [
            f"# {OWNER_ONLY} {CREATE_ANOTHER_EXPORT}",
            f"# {second_administrator} {REUSE_ACTIVE_EXPORT}",
        ]
    )
    controller = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        coding,
        ScriptedReviewerClient(
            [
                ReviewerResult(
                    classification=EvidenceClassification.SUPPORTED,
                    evidence_quote="Add workspace export creation.",
                ),
                not_evidenced(),
            ]
        ),
        ScriptMarkerProbe(),
    )
    run = controller.start(WORKSPACE_EXPORT_AUTHORIZATION)

    assert run.state is RunState.AWAITING_OWNER
    assert run.decisions[0].reviewer_result is not None
    assert run.decisions[0].reviewer_result.classification is EvidenceClassification.SUPPORTED
    answered = controller.answer(run.run_id, REPEAT_REQUEST, REUSE_ACTIVE_EXPORT)
    assert answered.state is RunState.READY_TO_RESUME
    completed = controller.resume(run.run_id)

    assert completed.state is expected_state
    assert completed.decisions[0].selected is None
    assert completed.decisions[1].selected == REUSE_ACTIVE_EXPORT


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
    observer = ScriptMarkerProbe()
    Orchestrator(
        repo_path=reference_repo,
        scenarios=scripted_scenarios(observer),
    ).answer(
        first.run_id,
        EXISTING_LINK_ROLLOUT,
        PRESERVE_EXISTING,
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
        Orchestrator(
            repo_path=reference_repo,
            scenarios=scripted_scenarios(observer),
        ).answer(
            first.run_id,
            EXISTING_LINK_ROLLOUT,
            EXPIRE_EXISTING,
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
    assert run.decisions == []


@pytest.mark.parametrize(
    "outcomes",
    [
        {ADMINISTRATOR_ACCESS: OWNER_ONLY},
        {
            ADMINISTRATOR_ACCESS: OWNER_ONLY,
            REPEAT_REQUEST: CREATE_ANOTHER_EXPORT,
            "undeclared": "OUTCOME",
        },
    ],
)
def test_first_attempt_requires_exact_declared_outcomes_before_review(
    reference_repo: Path,
    tmp_path: Path,
    outcomes: dict[str, str],
) -> None:
    reviewer = ScriptedReviewerClient([])
    observer = FixedOutcomeProbe(outcomes)
    controller = Orchestrator(
        repo_path=reference_repo,
        scenarios=scenario_registry(observer, observer),
        coding_client=ScriptedCodingClient([f"# {OWNER_ONLY} {CREATE_ANOTHER_EXPORT}"]),
        reviewer_client=reviewer,
        worktree_root=tmp_path / "worktrees",
    )

    result = controller.start(WORKSPACE_EXPORT_AUTHORIZATION)

    assert result.state is RunState.FAILED
    assert result.error == "Attempt one did not return exactly the declared decision outcomes"
    assert reviewer.prompts == []
    assert result.decisions == []


def test_failed_model_call_preserves_requested_invocation_provenance(
    reference_repo: Path,
    tmp_path: Path,
) -> None:
    run = orchestrator(
        reference_repo,
        tmp_path / "worktrees",
        ScriptedCodingClient([RuntimeError("model failed")]),
        ScriptedReviewerClient([]),
        ScriptMarkerProbe(),
    ).start()

    assert run.state is RunState.FAILED
    assert [invocation.role for invocation in run.model_invocations] == [ModelRole.CODING_AGENT]
    assert run.model_invocations[0].attempt_number == 1
    assert run.error == "RuntimeError: model failed"
    persisted = RunStore(reference_repo).load(run.run_id)
    assert persisted.model_invocations == run.model_invocations
