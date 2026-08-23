"""Persisted run types and pure gate transitions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RunState(StrEnum):
    """Allowed persisted run states."""

    STARTED = "STARTED"
    AWAITING_OWNER = "AWAITING_OWNER"
    READY_TO_RESUME = "READY_TO_RESUME"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RolloutOption(StrEnum):
    """Modeled existing-row rollout behaviors."""

    PRESERVE_EXISTING = "PRESERVE_EXISTING"
    EXPIRE_EXISTING = "EXPIRE_EXISTING"
    UNMODELED = "UNMODELED"


class EvidenceClassification(StrEnum):
    """Evidence review classifications."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_EVIDENCED = "NOT_EVIDENCED"
    UNCERTAIN = "UNCERTAIN"


ROLLOUT_DESCRIPTIONS: dict[RolloutOption, str] = {
    RolloutOption.PRESERVE_EXISTING: (
        "Existing item-sharing links remain non-expiring with NULL; new links default "
        "to approximately 30 days after creation; expires_at remains nullable."
    ),
    RolloutOption.EXPIRE_EXISTING: (
        "Existing item-sharing links receive an expiration approximately 30 days from "
        "migration; new links default to approximately 30 days after creation; expires_at "
        "remains nullable."
    ),
    RolloutOption.UNMODELED: "The migration does not match either supported rollout behavior.",
}

OWNER_ROLLOUT_OPTIONS = (
    RolloutOption.PRESERVE_EXISTING,
    RolloutOption.EXPIRE_EXISTING,
)


def utc_now() -> datetime:
    """Return a timezone-aware current timestamp."""

    return datetime.now(UTC)


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest for UTF-8 text."""

    return hashlib.sha256(value.encode()).hexdigest()


class ProbeResult(BaseModel):
    """Normalized observable migration behavior."""

    data_type: str | None = None
    nullable: bool | None = None
    column_default: str | None = None
    insert_without_value: str = "unavailable"
    existing_row: str = "unavailable"
    rollout_option: RolloutOption
    rollback_verified: bool = False


class ReviewerResult(BaseModel):
    """Evidence review result after quote validation."""

    classification: EvidenceClassification
    evidence_quote: str | None = None


class DecisionRecord(BaseModel):
    """The single typed owner decision in a run."""

    decision_id: str = "existing_item_sharing_link_rollout"
    observed: RolloutOption
    selected: RolloutOption | None = None
    answered_at: datetime | None = None


class AttemptRecord(BaseModel):
    """Persisted data for one isolated coding attempt."""

    number: int
    worktree_path: str
    clean_start_verified: bool
    coding_prompt: str | None = None
    migration_digest: str | None = None
    probe_result: ProbeResult | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class RunRecord(BaseModel):
    """Complete durable state for one gate run."""

    run_id: str
    state: RunState
    original_brief: str
    base_commit: str
    attempts: list[AttemptRecord] = Field(default_factory=list)
    reviewer_prompt: str | None = None
    reviewer_result: ReviewerResult | None = None
    decision: DecisionRecord | None = None
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

    def persist_migration(self, run_id: str, attempt_number: int, migration: str) -> str:
        """Write the immutable migration copy and return its digest."""

        if attempt_number not in (1, 2):
            raise GateError(f"Invalid attempt number: {attempt_number}")
        path = self.run_path(run_id) / f"attempt-{attempt_number}.sql"
        stored_migration = migration if migration.endswith("\n") else f"{migration}\n"
        try:
            with path.open("x", encoding="utf-8") as file_handle:
                file_handle.write(stored_migration)
        except FileExistsError as error:
            raise GateError(f"Attempt {attempt_number} migration is already immutable") from error
        path.chmod(0o444)
        return sha256_text(stored_migration)


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


def state_after_review(classification: EvidenceClassification) -> RunState:
    """Return the required terminal or paused state after evidence review."""

    if classification is EvidenceClassification.SUPPORTED:
        return RunState.COMPLETED
    if classification in (
        EvidenceClassification.NOT_EVIDENCED,
        EvidenceClassification.UNCERTAIN,
    ):
        return RunState.AWAITING_OWNER
    if classification is EvidenceClassification.CONTRADICTED:
        return RunState.FAILED
    raise AssertionError(f"Unhandled evidence classification: {classification}")


def answer_owner(run: RunRecord, option: RolloutOption) -> None:
    """Record the only owner answer and advance a paused run."""

    if run.state is not RunState.AWAITING_OWNER:
        raise GateError(f"answer requires AWAITING_OWNER, found {run.state}")
    if option not in OWNER_ROLLOUT_OPTIONS:
        raise GateError(f"{option.value} is not an owner option")
    if run.decision is None:
        raise GateError("The paused run has no decision to answer")
    run.decision.selected = option
    run.decision.answered_at = utc_now()
    run.state = RunState.READY_TO_RESUME


def decision_request_payload(run: RunRecord) -> dict[str, Any] | None:
    """Build the actionable owner decision request for a paused run."""

    if run.state is not RunState.AWAITING_OWNER:
        return None
    if run.decision is None:
        raise GateError("The paused run has no decision to present")

    observed = run.decision.observed
    return {
        "id": run.decision.decision_id,
        "question": "What should happen to existing item-sharing links?",
        "reason": (
            "The gate could not establish from the brief whether the 30-day expiration "
            "should apply to existing item-sharing links."
        ),
        "observed": {
            "option": observed,
            "behavior": ROLLOUT_DESCRIPTIONS[observed],
        },
        "options": [
            {
                "option": option,
                "behavior": ROLLOUT_DESCRIPTIONS[option],
                "command": f"uv run idg answer {run.run_id} --option {option.value}",
            }
            for option in OWNER_ROLLOUT_OPTIONS
        ],
    }


def show_payload(run: RunRecord) -> dict[str, Any]:
    """Build the stable CLI summary for a run."""

    observed = (
        run.attempts[-1].probe_result.rollout_option
        if run.attempts and run.attempts[-1].probe_result
        else None
    )
    classification = run.reviewer_result.classification if run.reviewer_result else None
    final_worktree_path = None
    if run.state in (RunState.COMPLETED, RunState.FAILED) and run.attempts:
        final_worktree_path = run.attempts[-1].worktree_path
    return {
        "run_id": run.run_id,
        "state": run.state,
        "observed_option": observed,
        "classification": classification,
        "decision_request": decision_request_payload(run),
        "owner_option": run.decision.selected if run.decision else None,
        "attempt_digests": [attempt.migration_digest for attempt in run.attempts],
        "final_worktree_path": final_worktree_path,
        "error": run.error,
    }


def render_show(run: RunRecord) -> str:
    """Render the stable CLI summary as JSON."""

    return json.dumps(show_payload(run), indent=2, default=str)
