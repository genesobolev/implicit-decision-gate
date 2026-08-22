"""Run orchestration across model, worktree, probe, review, and gate components."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from implicit_decision_gate.agent import (
    CodingAgent,
    EvidenceReviewer,
    ModelClient,
)
from implicit_decision_gate.gate import (
    MAX_CODING_ATTEMPTS,
    AttemptRecord,
    DecisionLedgerRecord,
    GateError,
    RolloutOption,
    RunRecord,
    RunState,
    RunStore,
    answer_owner,
    render_show,
    sha256_text,
    state_after_first_attempt,
    utc_now,
)
from implicit_decision_gate.probe import MigrationProbe
from implicit_decision_gate.worktree import WorktreeManager

REFERENCE_BRIEF = Path("examples/share-link-expiration/brief.md")
REFERENCE_SCHEMA = Path("examples/share-link-expiration/schema.sql")


class Orchestrator:
    """Persisted state-machine controller for all four CLI operations."""

    def __init__(
        self,
        *,
        repo_path: Path,
        model_name: str | None = None,
        coding_client: ModelClient | None = None,
        reviewer_client: ModelClient | None = None,
        probe: MigrationProbe | None = None,
        worktree_root: Path | None = None,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.store = RunStore(self.repo_path)
        self.model_name = model_name
        self.coding_client = coding_client
        self.reviewer_client = reviewer_client
        self.probe = probe
        root = worktree_root or (self.repo_path.parent / f".{self.repo_path.name}-idg-worktrees")
        self.worktrees = WorktreeManager(self.repo_path, root)

    def start(self, brief_path: Path) -> RunRecord:
        """Start and execute attempt one through a terminal or paused state."""

        self._require_execution_dependencies()
        resolved_brief = (
            brief_path.resolve()
            if brief_path.is_absolute()
            else (self.repo_path / brief_path).resolve()
        )
        expected_brief = (self.repo_path / REFERENCE_BRIEF).resolve()
        if resolved_brief != expected_brief:
            raise GateError(f"Only the reference brief shape is supported: {REFERENCE_BRIEF}")
        try:
            brief = resolved_brief.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise GateError(f"Brief does not exist: {resolved_brief}") from error
        base_commit = self.worktrees.current_commit()
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            state=RunState.STARTED,
            repo_path=str(self.repo_path),
            brief_path=str(REFERENCE_BRIEF),
            original_brief=brief,
            brief_digest=sha256_text(brief),
            base_commit=base_commit,
            model_name=self._model_name(),
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
            self._require_execution_dependencies()
            if self._model_name() != run.model_name:
                raise GateError(f"IDG_MODEL must remain {run.model_name!r} when resuming this run")
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
        if attempt_number == 1 and run.state is not RunState.STARTED:
            raise GateError(f"Attempt one requires STARTED, found {run.state}")
        if attempt_number == 2 and run.state is not RunState.READY_TO_RESUME:
            raise GateError(f"Attempt two requires READY_TO_RESUME, found {run.state}")
        if run.coding_attempt_count >= MAX_CODING_ATTEMPTS:
            raise GateError(f"Coding-attempt limit of {MAX_CODING_ATTEMPTS} reached")
        if attempt_number != run.coding_attempt_count + 1:
            raise GateError("Coding attempts must be sequential")

        worktree = self.worktrees.create(run.run_id, attempt_number, run.base_commit)
        if any(attempt.worktree_path == str(worktree.path) for attempt in run.attempts):
            raise GateError("Each coding attempt must use a distinct worktree")
        attempt = AttemptRecord(
            number=attempt_number,
            worktree_path=str(worktree.path),
            base_commit=worktree.base_commit,
            clean_start_verified=worktree.clean_start_verified,
            model_name=run.model_name,
        )
        run.attempts.append(attempt)
        run.coding_attempt_count += 1
        self.store.save(run)

        def persist() -> None:
            self.store.save(run)

        coding_agent = CodingAgent(self._coding_client(), run.model_name)
        proposal = coding_agent.propose(
            brief=run.original_brief,
            attempt=attempt,
            worktree_path=worktree.path,
            run_id=run.run_id,
            owner_option=run.owner_option if attempt_number == 2 else None,
            persist=persist,
        )
        digest = self.store.persist_migration(
            run.run_id,
            attempt_number,
            proposal.migration,
        )
        immutable_path = self.store.run_path(run.run_id) / f"attempt-{attempt_number}.sql"
        attempt.migration_path = str(immutable_path)
        attempt.migration_contents = immutable_path.read_text(encoding="utf-8")
        attempt.migration_digest = digest
        attempt.proposal_submitted_at = utc_now()
        self.store.save(run)

        schema_path = worktree.path / REFERENCE_SCHEMA
        try:
            baseline_schema = schema_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise GateError(f"Baseline schema does not exist: {schema_path}") from error
        attempt.probe_result = self._probe().probe(proposal.migration, baseline_schema)
        attempt.completed_at = utc_now()
        self.store.save(run)

        if attempt_number == 1:
            self._finish_first_attempt(run, persist)
        else:
            self._finish_second_attempt(run)
        self.store.save(run)

    def _finish_first_attempt(
        self,
        run: RunRecord,
        persist: Callable[[], None],
    ) -> None:
        probe_result = run.attempts[0].probe_result
        if probe_result is None:
            raise GateError("Attempt one has no probe result")
        if probe_result.rollout_option is RolloutOption.UNMODELED:
            run.state = RunState.FAILED
            run.error = "Attempt one produced an UNMODELED rollout behavior"
            return

        reviewer = EvidenceReviewer(self._reviewer_client(), run.model_name)
        reviewer_result = reviewer.review(
            brief=run.original_brief,
            option=probe_result.rollout_option,
            run=run,
            persist=persist,
        )
        run.reviewer_result = reviewer_result
        run.validated_evidence_quote = reviewer_result.evidence_quote
        run.reviewed_at = utc_now()
        run.state = state_after_first_attempt(
            probe_result.rollout_option,
            reviewer_result.classification,
        )
        run.decision_ledger = DecisionLedgerRecord(
            observed=probe_result.rollout_option,
            classification=reviewer_result.classification,
            evidence_quote=reviewer_result.evidence_quote,
            state=run.state,
        )
        if run.state is RunState.FAILED:
            run.error = f"Observed rollout was {reviewer_result.classification.value} by the brief"

    def _finish_second_attempt(self, run: RunRecord) -> None:
        if run.owner_option is None:
            raise GateError("Attempt two has no owner option")
        probe_result = run.attempts[1].probe_result
        if probe_result is None:
            raise GateError("Attempt two has no probe result")
        if probe_result.rollout_option == run.owner_option:
            run.state = RunState.COMPLETED
            run.error = None
        else:
            run.state = RunState.FAILED
            run.error = (
                f"Attempt two produced {probe_result.rollout_option.value}; "
                f"owner selected {run.owner_option.value}"
            )
        if run.decision_ledger is not None:
            run.decision_ledger.state = run.state

    def _require_execution_dependencies(self) -> None:
        if not self.model_name:
            raise GateError("IDG_MODEL is required for model execution")
        if self.coding_client is None:
            raise GateError("A coding model client is required for model execution")
        if self.reviewer_client is None:
            raise GateError("An evidence-review model client is required for model execution")
        if self.probe is None:
            raise GateError("A PostgreSQL probe is required for model execution")

    def _model_name(self) -> str:
        if self.model_name is None:
            raise GateError("IDG_MODEL is required for model execution")
        return self.model_name

    def _coding_client(self) -> ModelClient:
        if self.coding_client is None:
            raise GateError("A coding model client is required for model execution")
        return self.coding_client

    def _reviewer_client(self) -> ModelClient:
        if self.reviewer_client is None:
            raise GateError("An evidence-review model client is required for model execution")
        return self.reviewer_client

    def _probe(self) -> MigrationProbe:
        if self.probe is None:
            raise GateError("A PostgreSQL probe is required for model execution")
        return self.probe
