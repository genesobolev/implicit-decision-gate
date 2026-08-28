"""Run orchestration across model, worktree, observer, review, and gate components."""

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
    AttemptRecord,
    CoverageGapRecord,
    DecisionRecord,
    EvidenceClassification,
    GateError,
    ModelRole,
    RunRecord,
    RunState,
    RunStore,
    answer_owner,
    render_show,
    state_after_reviews,
    utc_now,
    validate_reviewer_result,
)
from implicit_decision_gate.scenario import (
    UNMODELED_OUTCOME,
    DecisionOption,
    DecisionSpec,
    Scenario,
    option_by_id,
)
from implicit_decision_gate.scenarios import SHARE_LINK_EXPIRATION
from implicit_decision_gate.worktree import WorktreeManager


class Orchestrator:
    """Persisted state-machine controller for all four CLI operations."""

    def __init__(
        self,
        *,
        repo_path: Path,
        scenarios: dict[str, Scenario],
        coding_client: CodingClient | None = None,
        reviewer_client: ReviewerClient | None = None,
        worktree_root: Path | None = None,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.store = RunStore(self.repo_path)
        self.scenarios = scenarios
        self.coding_client = coding_client
        self.reviewer_client = reviewer_client
        root = worktree_root or (self.repo_path.parent / f".{self.repo_path.name}-idg-worktrees")
        self.worktrees = WorktreeManager(self.repo_path, root)

    def start(self, scenario_id: str = SHARE_LINK_EXPIRATION) -> RunRecord:
        """Start one scenario and execute its first attempt."""

        scenario = self._scenario(scenario_id)
        base_commit = self.worktrees.current_commit()
        brief = self.worktrees.read_file_at_commit(base_commit, scenario.brief_path)
        run = RunRecord(
            run_id=uuid.uuid4().hex,
            scenario_id=scenario.id,
            state=RunState.STARTED,
            original_brief=brief,
            base_commit=base_commit,
        )
        self.store.create(run)
        return self._execute_or_fail(run, attempt_number=1)

    def answer(self, run_id: str, decision_id: str, option: str) -> RunRecord:
        """Persist one typed owner answer without invoking a model."""

        with self.store.lock(run_id):
            run = self.store.load(run_id)
            answer_owner(
                run,
                decision_id,
                option,
                self._scenario(run.scenario_id).decisions,
            )
            self.store.save(run)
            return run

    def resume(self, run_id: str) -> RunRecord:
        """Execute attempt two from a ready persisted run."""

        with self.store.lock(run_id):
            run = self.store.load(run_id)
            if run.state is not RunState.READY_TO_RESUME:
                raise GateError(f"resume requires READY_TO_RESUME, found {run.state}")
            return self._execute_or_fail(run, attempt_number=2)

    def show(self, run_id: str) -> str:
        """Render the persisted run summary without model execution."""

        run = self.store.load(run_id)
        return render_show(run, self._scenario(run.scenario_id).decisions)

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

        scenario = self._scenario(run.scenario_id)
        worktree = self.worktrees.create(run.run_id, attempt_number, run.base_commit)
        attempt = AttemptRecord(
            number=attempt_number,
            worktree_path=str(worktree.path),
            clean_start_verified=worktree.clean_start_verified,
        )
        run.attempts.append(attempt)
        self.store.save(run)

        context_path = worktree.path / scenario.context_path
        try:
            context = context_path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise GateError(f"Scenario context does not exist: {context_path}") from error

        selected = {
            decision.decision_id: decision.selected
            for decision in run.decisions
            if decision.selected is not None
        }
        coding_prompt = build_coding_prompt(
            scenario=scenario,
            brief=run.original_brief,
            context=context,
            attempt_number=attempt_number,
            owner_options=selected if attempt_number == 2 else None,
        )
        attempt.coding_prompt = coding_prompt
        self.store.save(run)
        coding_client = self._coding_client()
        run.model_invocations.append(
            coding_client.invocation_record(
                role=ModelRole.CODING_AGENT,
                attempt_number=attempt_number,
            )
        )
        self.store.save(run)
        artifact = coding_client.propose_artifact(coding_prompt)
        if not artifact.strip():
            raise AgentError("The coding model returned an empty artifact")
        self._write_worktree_artifact(
            worktree.path,
            scenario,
            run.run_id,
            attempt_number,
            artifact,
        )
        attempt.artifact_digest = self.store.persist_artifact(
            run.run_id,
            attempt_number,
            scenario.artifact_suffix,
            artifact,
        )
        self.store.save(run)
        attempt.observation = scenario.observer.observe(artifact, context)
        attempt.completed_at = utc_now()
        self.store.save(run)

        if attempt_number == 1:
            self._finish_first_attempt(run, scenario)
        else:
            self._finish_second_attempt(run, scenario)
        self.store.save(run)

    def _finish_first_attempt(self, run: RunRecord, scenario: Scenario) -> None:
        observation = run.attempts[0].observation
        if observation is None:
            raise GateError("Attempt one has no observation")
        expected_ids = {decision.id for decision in scenario.decisions}
        if set(observation.outcomes) != expected_ids:
            run.state = RunState.FAILED
            run.error = "Attempt one did not return exactly the declared decision outcomes"
            return

        modeled: list[tuple[DecisionSpec, DecisionOption]] = []
        for decision in scenario.decisions:
            outcome = observation.outcomes[decision.id]
            option = option_by_id(decision, outcome)
            if outcome == UNMODELED_OUTCOME:
                run.coverage_gaps.append(
                    CoverageGapRecord(
                        decision_id=decision.id,
                        observed=outcome,
                        attempt_number=1,
                    )
                )
                continue
            if option is None:
                run.state = RunState.FAILED
                run.error = (
                    f"Attempt one returned an undeclared outcome for {decision.id}: {outcome}"
                )
                return
            modeled.append((decision, option))

        if run.coverage_gaps:
            run.state = RunState.COVERAGE_GAP
            run.error = None
            return

        classifications = []
        reviewer_client = self._reviewer_client()
        for decision, option in modeled:
            reviewer_prompt = build_reviewer_prompt(
                brief=run.original_brief,
                option=option,
            )
            record = DecisionRecord(
                decision_id=decision.id,
                observed=option.id,
                reviewer_prompt=reviewer_prompt,
            )
            run.decisions.append(record)
            self.store.save(run)
            invocation = reviewer_client.invocation_record(
                role=ModelRole.EVIDENCE_REVIEWER,
                attempt_number=None,
            )
            invocation.decision_id = decision.id
            run.model_invocations.append(invocation)
            self.store.save(run)
            record.reviewer_result = validate_reviewer_result(
                run.original_brief,
                reviewer_client.review_evidence(reviewer_prompt),
            )
            classifications.append(record.reviewer_result.classification)
            self.store.save(run)

        run.state = state_after_reviews(classifications)
        if run.state is RunState.FAILED:
            contradicted = [
                decision.decision_id
                for decision in run.decisions
                if decision.reviewer_result is not None
                and decision.reviewer_result.classification is EvidenceClassification.CONTRADICTED
            ]
            run.error = f"Observed behavior was contradicted for: {', '.join(contradicted)}"

    @staticmethod
    def _finish_second_attempt(run: RunRecord, scenario: Scenario) -> None:
        observation = run.attempts[1].observation
        if observation is None:
            raise GateError("Attempt two has no observation")
        expected: dict[str, str] = {}
        records = {decision.decision_id: decision for decision in run.decisions}
        for specification in scenario.decisions:
            record = records.get(specification.id)
            if record is None or record.reviewer_result is None:
                raise GateError(f"Attempt two has no reviewed decision: {specification.id}")
            if record.selected is not None:
                expected[specification.id] = record.selected
            elif record.reviewer_result.classification is EvidenceClassification.SUPPORTED:
                expected[specification.id] = record.observed
            else:
                raise GateError(f"Attempt two has no owner answer: {specification.id}")

        mismatches = [
            f"{decision_id}: expected {option}, observed "
            f"{observation.outcomes.get(decision_id, 'MISSING')}"
            for decision_id, option in expected.items()
            if observation.outcomes.get(decision_id) != option
        ]
        for decision_id in expected:
            observed = observation.outcomes.get(decision_id)
            if observed == UNMODELED_OUTCOME:
                run.coverage_gaps.append(
                    CoverageGapRecord(
                        decision_id=decision_id,
                        observed=observed,
                        attempt_number=2,
                    )
                )
        extra = sorted(set(observation.outcomes) - set(expected))
        mismatches.extend(f"{decision_id}: unexpected outcome" for decision_id in extra)
        if not mismatches:
            run.state = RunState.COMPLETED
            run.error = None
        else:
            run.state = RunState.FAILED
            run.error = f"Attempt two decision mismatch: {'; '.join(mismatches)}"

    @staticmethod
    def _write_worktree_artifact(
        worktree_path: Path,
        scenario: Scenario,
        run_id: str,
        attempt_number: int,
        artifact: str,
    ) -> None:
        directory = worktree_path / scenario.artifact_directory
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / (
            f"idg-{run_id}-attempt-{attempt_number}{scenario.artifact_suffix}"
        )
        try:
            with destination.open("x", encoding="utf-8") as file_handle:
                file_handle.write(artifact)
                if not artifact.endswith("\n"):
                    file_handle.write("\n")
        except FileExistsError as error:
            raise GateError("An artifact was already written for this attempt") from error

    def _scenario(self, scenario_id: str) -> Scenario:
        try:
            return self.scenarios[scenario_id]
        except KeyError as error:
            raise GateError(f"Unknown scenario: {scenario_id}") from error

    def _coding_client(self) -> CodingClient:
        if self.coding_client is None:
            raise GateError("A coding model client is required for model execution")
        return self.coding_client

    def _reviewer_client(self) -> ReviewerClient:
        if self.reviewer_client is None:
            raise GateError("An evidence-review model client is required for attempt one")
        return self.reviewer_client
