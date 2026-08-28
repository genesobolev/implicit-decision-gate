"""Persisted run types and pure gate transitions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from implicit_decision_gate.scenario import (
    DecisionSpec,
    ObservationResult,
    decision_by_id,
    option_by_id,
)


class RunState(StrEnum):
    """Allowed persisted run states."""

    STARTED = "STARTED"
    AWAITING_OWNER = "AWAITING_OWNER"
    READY_TO_RESUME = "READY_TO_RESUME"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvidenceClassification(StrEnum):
    """Evidence review classifications."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_EVIDENCED = "NOT_EVIDENCED"
    UNCERTAIN = "UNCERTAIN"


class ModelRole(StrEnum):
    """Purpose of one persisted model invocation."""

    CODING_AGENT = "CODING_AGENT"
    EVIDENCE_REVIEWER = "EVIDENCE_REVIEWER"


def utc_now() -> datetime:
    """Return a timezone-aware current timestamp."""

    return datetime.now(UTC)


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest for UTF-8 text."""

    return hashlib.sha256(value.encode()).hexdigest()


class ReviewerResult(BaseModel):
    """Evidence review result after quote validation."""

    classification: EvidenceClassification
    evidence_quote: str | None = None


class ModelInvocationRecord(BaseModel):
    """Auditable configuration for one model process."""

    role: ModelRole
    attempt_number: int | None = None
    decision_id: str | None = None
    model: str
    reasoning_effort: str
    codex_cli_version: str


class DecisionRecord(BaseModel):
    """One observed decision, its review, and any typed owner answer."""

    decision_id: str
    observed: str
    reviewer_prompt: str
    reviewer_result: ReviewerResult | None = None
    selected: str | None = None
    answered_at: datetime | None = None


class AttemptRecord(BaseModel):
    """Persisted data for one isolated coding attempt."""

    number: int
    worktree_path: str
    clean_start_verified: bool
    coding_prompt: str | None = None
    artifact_digest: str | None = None
    observation: ObservationResult | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class RunRecord(BaseModel):
    """Complete durable state for one gate run."""

    run_id: str
    scenario_id: str
    state: RunState
    original_brief: str
    base_commit: str
    model_invocations: list[ModelInvocationRecord] = Field(default_factory=list)
    attempts: list[AttemptRecord] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GateError(RuntimeError):
    """Raised when a command violates the persisted state machine."""


class RunStore:
    """Load and atomically persist runs inside the target repository."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()
        self.runs_path = self.repo_path / ".idg" / "runs"

    def run_path(self, run_id: str) -> Path:
        """Return the directory for a validated run identifier."""

        if not run_id or any(character not in "0123456789abcdef" for character in run_id):
            raise GateError(f"Invalid run ID: {run_id!r}")
        return self.runs_path / run_id

    def create(self, run: RunRecord) -> None:
        """Create and persist a new run."""

        path = self.run_path(run.run_id)
        path.mkdir(parents=True, exist_ok=False)
        self.save(run)

    @contextmanager
    def lock(self, run_id: str) -> Iterator[None]:
        """Hold the cross-process mutation lock for one existing run."""

        path = self.run_path(run_id)
        if not path.is_dir():
            raise GateError(f"Run does not exist: {run_id}")
        with (path / ".run.lock").open("a", encoding="utf-8") as file_handle:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)

    def save(self, run: RunRecord) -> None:
        """Persist a run using a temporary file and atomic rename."""

        path = self.run_path(run.run_id)
        path.mkdir(parents=True, exist_ok=True)
        run.updated_at = utc_now()
        destination = path / "run.json"
        temporary = path / f".run.json.{os.getpid()}.tmp"
        payload = run.model_dump_json(indent=2)
        try:
            with temporary.open("x", encoding="utf-8") as file_handle:
                file_handle.write(payload)
                file_handle.write("\n")
                file_handle.flush()
                os.fsync(file_handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, run_id: str) -> RunRecord:
        """Load and validate a persisted run."""

        path = self.run_path(run_id) / "run.json"
        try:
            return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise GateError(f"Run does not exist: {run_id}") from error

    def persist_artifact(
        self,
        run_id: str,
        attempt_number: int,
        suffix: str,
        artifact: str,
    ) -> str:
        """Write one immutable artifact copy and return its digest."""

        if attempt_number not in (1, 2):
            raise GateError(f"Invalid attempt number: {attempt_number}")
        path = self.run_path(run_id) / f"attempt-{attempt_number}{suffix}"
        stored_artifact = artifact if artifact.endswith("\n") else f"{artifact}\n"
        try:
            with path.open("x", encoding="utf-8") as file_handle:
                file_handle.write(stored_artifact)
        except FileExistsError as error:
            raise GateError(f"Attempt {attempt_number} artifact is already immutable") from error
        path.chmod(0o444)
        return sha256_text(stored_artifact)


def validate_reviewer_result(brief: str, result: ReviewerResult) -> ReviewerResult:
    """Validate required evidence quotes as literal brief substrings."""

    if result.classification in (
        EvidenceClassification.SUPPORTED,
        EvidenceClassification.CONTRADICTED,
    ) and (not result.evidence_quote or result.evidence_quote not in brief):
        return ReviewerResult(
            classification=EvidenceClassification.UNCERTAIN,
            evidence_quote=None,
        )
    if result.classification in (
        EvidenceClassification.NOT_EVIDENCED,
        EvidenceClassification.UNCERTAIN,
    ):
        return ReviewerResult(
            classification=result.classification,
            evidence_quote=None,
        )
    return result


def state_after_reviews(classifications: Sequence[EvidenceClassification]) -> RunState:
    """Aggregate independent evidence reviews into one run state."""

    if EvidenceClassification.CONTRADICTED in classifications:
        return RunState.FAILED
    if any(
        classification in (EvidenceClassification.NOT_EVIDENCED, EvidenceClassification.UNCERTAIN)
        for classification in classifications
    ):
        return RunState.AWAITING_OWNER
    return RunState.COMPLETED


def decision_requires_owner(decision: DecisionRecord) -> bool:
    """Return whether one reviewed decision needs a human answer."""

    return decision.reviewer_result is not None and decision.reviewer_result.classification in (
        EvidenceClassification.NOT_EVIDENCED,
        EvidenceClassification.UNCERTAIN,
    )


def answer_owner(
    run: RunRecord,
    decision_id: str,
    option_id: str,
    decisions: tuple[DecisionSpec, ...],
) -> None:
    """Record one owner answer and advance after every required answer exists."""

    if run.state is not RunState.AWAITING_OWNER:
        raise GateError(f"answer requires AWAITING_OWNER, found {run.state}")
    specification = decision_by_id(decisions, decision_id)
    if specification is None:
        raise GateError(f"Unknown decision: {decision_id}")
    if option_by_id(specification, option_id) is None:
        raise GateError(f"{option_id} is not an option for {decision_id}")
    record = next(
        (decision for decision in run.decisions if decision.decision_id == decision_id),
        None,
    )
    if record is None or not decision_requires_owner(record):
        raise GateError(f"Decision does not require an owner answer: {decision_id}")
    if record.selected is not None:
        raise GateError(f"Decision was already answered: {decision_id}")
    record.selected = option_id
    record.answered_at = utc_now()
    if all(
        not decision_requires_owner(decision) or decision.selected is not None
        for decision in run.decisions
    ):
        run.state = RunState.READY_TO_RESUME


def decision_request_payloads(
    run: RunRecord,
    decisions: tuple[DecisionSpec, ...],
) -> list[dict[str, Any]]:
    """Build every unanswered owner decision request for a paused run."""

    if run.state is not RunState.AWAITING_OWNER:
        return []
    payloads: list[dict[str, Any]] = []
    for record in run.decisions:
        if not decision_requires_owner(record) or record.selected is not None:
            continue
        specification = decision_by_id(decisions, record.decision_id)
        if specification is None:
            raise GateError(f"Unknown persisted decision: {record.decision_id}")
        observed = option_by_id(specification, record.observed)
        if observed is None:
            raise GateError(f"Observed outcome is not an owner option: {record.observed}")
        payloads.append(
            {
                "id": specification.id,
                "question": specification.question,
                "reason": specification.reason,
                "observed": {
                    "option": observed.id,
                    "behavior": observed.behavior,
                },
                "options": [
                    {
                        "option": option.id,
                        "behavior": option.behavior,
                        "command": (
                            f"uv run idg answer {run.run_id} "
                            f"--decision {specification.id} --option {option.id}"
                        ),
                    }
                    for option in specification.options
                ],
            }
        )
    return payloads


def show_payload(run: RunRecord, decisions: tuple[DecisionSpec, ...]) -> dict[str, Any]:
    """Build the stable CLI summary for a run."""

    observed = (
        run.attempts[-1].observation.outcomes
        if run.attempts and run.attempts[-1].observation
        else {}
    )
    final_worktree_path = None
    if run.state in (RunState.COMPLETED, RunState.FAILED) and run.attempts:
        final_worktree_path = run.attempts[-1].worktree_path
    return {
        "run_id": run.run_id,
        "scenario": run.scenario_id,
        "state": run.state,
        "model_invocations": [
            invocation.model_dump(mode="json") for invocation in run.model_invocations
        ],
        "observed_options": observed,
        "classifications": {
            decision.decision_id: decision.reviewer_result.classification
            for decision in run.decisions
            if decision.reviewer_result is not None
        },
        "decision_requests": decision_request_payloads(run, decisions),
        "owner_options": {
            decision.decision_id: decision.selected
            for decision in run.decisions
            if decision.selected is not None
        },
        "attempt_digests": [attempt.artifact_digest for attempt in run.attempts],
        "final_worktree_path": final_worktree_path,
        "error": run.error,
    }


def render_show(run: RunRecord, decisions: tuple[DecisionSpec, ...]) -> str:
    """Render the stable CLI summary as JSON."""

    return json.dumps(show_payload(run, decisions), indent=2, default=str)
