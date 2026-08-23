"""Run orchestration across model, worktree, probe, review, and gate components."""

from __future__ import annotations

import uuid
from pathlib import Path

from implicit_decision_gate.agent import (
    AgentError,
    CodingClient,
    ReviewerClient,
    build_coding_prompt,
    build_reviewer_prompt,
)
from implicit_decision_gate.gate import (
    AgentBackend,
    AttemptRecord,
    DecisionRecord,
    GateError,
    RolloutOption,
    RunRecord,
    RunState,
    RunStore,
    answer_owner,
    render_show,
    state_after_review,
    utc_now,
    validate_reviewer_result,
)
from implicit_decision_gate.probe import MigrationProbe
from implicit_decision_gate.worktree import WorktreeManager

REFERENCE_BRIEF = Path("examples/share-link-expiration/brief.md")
REFERENCE_SCHEMA = Path("examples/share-link-expiration/schema.sql")
REFERENCE_MIGRATIONS = Path("examples/share-link-expiration/migrations")


class Orchestrator:
    """Persisted state-machine controller for all four CLI operations."""

    def __init__(
        self,
        *,
        repo_path: Path,
        agent_backend: AgentBackend | None = None,
        coding_client: CodingClient | None = None,
        reviewer_client: ReviewerClient | None = None,
        probe: MigrationProbe | None = None,
        worktree_root: Path | None = None,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.store = RunStore(self.repo_path)
        self.agent_backend = agent_backend
        self.coding_client = coding_client
        self.reviewer_client = reviewer_client
        self.probe = probe
        root = worktree_root or (self.repo_path.parent / f".{self.repo_path.name}-idg-worktrees")
        self.worktrees = WorktreeManager(self.repo_path, root)

    def start(self) -> RunRecord:
        """Start the item-sharing expiration run and its first attempt."""

        base_commit = self.worktrees.current_commit()
        brief = self.worktrees.read_file_at_commit(base_commit, REFERENCE_BRIEF)
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            state=RunState.STARTED,
            original_brief=brief,
            base_commit=base_commit,
            agent_backend=self._agent_backend(),
        )
        self.store.create(run)
        return self._execute_or_fail(run, attempt_number=1)

    def answer(self, run_id: str, option: RolloutOption) -> RunRecord:
        """Persist the one typed owner answer without invoking a model."""

        with self.store.lock(run_id):
            run = self.store.load(run_id)
            answer_owner(run, option)
            self.store.save(run)
            return run

    def resume(self, run_id: str) -> RunRecord:
        """Execute attempt two from a ready persisted run."""

        with self.store.lock(run_id):
            run = self.store.load(run_id)
            if run.state is not RunState.READY_TO_RESUME:
                raise GateError(f"resume requires READY_TO_RESUME, found {run.state}")
            if self._agent_backend() is not run.agent_backend:
                raise GateError(
                    f"Agent backend must remain {run.agent_backend.value!r} when resuming this run"
                )
            return self._execute_or_fail(run, attempt_number=2)

    def show(self, run_id: str) -> str:
        """Render the persisted run summary without model execution."""

        return render_show(self.store.load(run_id))

    def _execute_or_fail(self, run: RunRecord, *, attempt_number: int) -> RunRecord:
        try:
            self._execute_attempt(run, attempt_number=attempt_number)
        except Exception as error:
            run.state = RunState.FAILED
            run.error = f"{type(error).__name__}: {error}"
            if run.attempts and run.attempts[-1].completed_at is None:
                run.attempts[-1].completed_at = utc_now()
            self.store.save(run)
        return run

    def _execute_attempt(self, run: RunRecord, *, attempt_number: int) -> None:
        expected_state = RunState.STARTED if attempt_number == 1 else RunState.READY_TO_RESUME
        if run.state is not expected_state:
            raise GateError(
                f"Attempt {attempt_number} requires {expected_state}, found {run.state}"
            )
        if attempt_number != len(run.attempts) + 1:
            raise GateError("Coding attempts must be sequential")

        worktree = self.worktrees.create(run.run_id, attempt_number, run.base_commit)
        attempt = AttemptRecord(
            number=attempt_number,
            worktree_path=str(worktree.path),
            clean_start_verified=worktree.clean_start_verified,
        )
        run.attempts.append(attempt)
        self.store.save(run)

        schema_path = worktree.path / REFERENCE_SCHEMA
        try:
            baseline_schema = schema_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise GateError(f"Baseline schema does not exist: {schema_path}") from error

        selected = run.decision.selected if run.decision is not None else None
        coding_prompt = build_coding_prompt(
            brief=run.original_brief,
            schema=baseline_schema,
            attempt_number=attempt_number,
            owner_option=selected if attempt_number == 2 else None,
        )
        attempt.coding_prompt = coding_prompt
        self.store.save(run)
        migration = self._coding_client().propose_migration(coding_prompt)
        if not migration.strip():
            raise AgentError("The coding model returned an empty migration")
        self._write_worktree_migration(
            worktree.path,
            run.run_id,
            attempt_number,
            migration,
        )
        attempt.migration_digest = self.store.persist_migration(
            run.run_id,
            attempt_number,
            migration,
        )
        self.store.save(run)
        attempt.probe_result = self._probe().probe(migration, baseline_schema)
        attempt.completed_at = utc_now()
        self.store.save(run)

        if attempt_number == 1:
            self._finish_first_attempt(run)
        else:
            self._finish_second_attempt(run)
        self.store.save(run)

    def _finish_first_attempt(self, run: RunRecord) -> None:
        probe_result = run.attempts[0].probe_result
        if probe_result is None:
            raise GateError("Attempt one has no probe result")
        if probe_result.rollout_option is RolloutOption.UNMODELED:
            run.state = RunState.FAILED
            run.error = "Attempt one produced an UNMODELED rollout behavior"
            return

        reviewer_prompt = build_reviewer_prompt(
            brief=run.original_brief,
            option=probe_result.rollout_option,
        )
        run.reviewer_prompt = reviewer_prompt
        self.store.save(run)
        run.reviewer_result = validate_reviewer_result(
            run.original_brief,
            self._reviewer_client().review_evidence(reviewer_prompt),
        )
        run.state = state_after_review(run.reviewer_result.classification)
        run.decision = DecisionRecord(observed=probe_result.rollout_option)
        if run.state is RunState.FAILED:
            run.error = (
                f"Observed rollout was {run.reviewer_result.classification.value} by the brief"
            )

    def _finish_second_attempt(self, run: RunRecord) -> None:
        if run.decision is None or run.decision.selected is None:
            raise GateError("Attempt two has no owner decision")
        probe_result = run.attempts[1].probe_result
        if probe_result is None:
            raise GateError("Attempt two has no probe result")
        if probe_result.rollout_option == run.decision.selected:
            run.state = RunState.COMPLETED
            run.error = None
        else:
            run.state = RunState.FAILED
            run.error = (
                f"Attempt two produced {probe_result.rollout_option.value}; "
                f"owner selected {run.decision.selected.value}"
            )

    @staticmethod
    def _write_worktree_migration(
        worktree_path: Path,
        run_id: str,
        attempt_number: int,
        migration: str,
    ) -> None:
        directory = worktree_path / REFERENCE_MIGRATIONS
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"idg-{run_id}-attempt-{attempt_number}.sql"
        try:
            with destination.open("x", encoding="utf-8") as file_handle:
                file_handle.write(migration)
                if not migration.endswith("\n"):
                    file_handle.write("\n")
        except FileExistsError as error:
            raise GateError("A migration was already written for this attempt") from error

    def _agent_backend(self) -> AgentBackend:
        if self.agent_backend is None:
            raise GateError("An agent backend is required for model execution")
        return self.agent_backend

    def _coding_client(self) -> CodingClient:
        if self.coding_client is None:
            raise GateError("A coding model client is required for model execution")
        return self.coding_client

    def _reviewer_client(self) -> ReviewerClient:
        if self.reviewer_client is None:
            raise GateError("An evidence-review model client is required for attempt one")
        return self.reviewer_client

    def _probe(self) -> MigrationProbe:
        if self.probe is None:
            raise GateError("A PostgreSQL probe is required for model execution")
        return self.probe
