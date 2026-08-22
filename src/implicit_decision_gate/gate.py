"""Persisted run types and pure gate transitions."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MAX_CODING_ATTEMPTS = 2
MAX_TOOL_STEPS_PER_ATTEMPT = 4
MAX_TRANSPORT_RETRIES_PER_CALL = 1
MAX_OWNER_ANSWERS = 1
PROMPT_VERSION = "2026-08-22.1"


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
        "Existing share links remain non-expiring with NULL; new share links default "
        "to approximately 30 days after creation; expires_at remains nullable."
    ),
    RolloutOption.EXPIRE_EXISTING: (
        "Existing share links receive an expiration approximately 30 days from migration; "
        "new share links default to approximately 30 days after creation; expires_at remains "
        "nullable."
    ),
    RolloutOption.UNMODELED: "The migration does not match either supported rollout behavior.",
}


def utc_now() -> datetime:
    """Return a timezone-aware current timestamp."""

    return datetime.now(UTC)


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest for UTF-8 text."""

    return hashlib.sha256(value.encode()).hexdigest()


class ProbeResult(BaseModel):
    """Normalized observable migration behavior."""

    table: str = "public.share_links"
    column: str = "expires_at"
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


class DecisionLedgerRecord(BaseModel):
    """The single typed owner decision in a run."""

    decision_id: str = "existing_share_link_rollout"
    impact: str = "HIGH"
    observed: RolloutOption
    classification: EvidenceClassification
    evidence_quote: str | None
    state: RunState
    options: list[RolloutOption] = Field(
        default_factory=lambda: [
            RolloutOption.PRESERVE_EXISTING,
            RolloutOption.EXPIRE_EXISTING,
        ]
    )


class AttemptRecord(BaseModel):
    """Persisted data for one isolated coding attempt."""

    number: int
    worktree_path: str
    base_commit: str
    clean_start_verified: bool
    model_name: str
    prompt_version: str = PROMPT_VERSION
    model_requests: list[dict[str, Any]] = Field(default_factory=list)
    model_responses: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_step_count: int = 0
    transport_retry_count: int = 0
    migration_path: str | None = None
    migration_contents: str | None = None
    migration_digest: str | None = None
    probe_result: ProbeResult | None = None
    started_at: datetime = Field(default_factory=utc_now)
    proposal_submitted_at: datetime | None = None
    completed_at: datetime | None = None


class RunRecord(BaseModel):
    """Complete durable state for one gate run."""

    run_id: str
    state: RunState
    repo_path: str
    brief_path: str
    original_brief: str
    brief_digest: str
    base_commit: str
    model_name: str
    prompt_version: str = PROMPT_VERSION
    attempts: list[AttemptRecord] = Field(default_factory=list)
    coding_attempt_count: int = 0
    reviewer_request: dict[str, Any] | None = None
    reviewer_response: dict[str, Any] | None = None
    reviewer_transport_retry_count: int = 0
    reviewer_result: ReviewerResult | None = None
    validated_evidence_quote: str | None = None
    reviewed_at: datetime | None = None
    decision_ledger: DecisionLedgerRecord | None = None
    owner_option: RolloutOption | None = None
    owner_answer_count: int = 0
    owner_answered_at: datetime | None = None
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


def state_after_first_attempt(
    rollout_option: RolloutOption,
    classification: EvidenceClassification | None,
) -> RunState:
    """Return the required terminal or paused state after attempt one."""

    if rollout_option is RolloutOption.UNMODELED:
        return RunState.FAILED
    if classification is EvidenceClassification.SUPPORTED:
        return RunState.COMPLETED
    if classification in (
        EvidenceClassification.NOT_EVIDENCED,
        EvidenceClassification.UNCERTAIN,
    ):
        return RunState.AWAITING_OWNER
    if classification is EvidenceClassification.CONTRADICTED:
        return RunState.FAILED
    raise GateError("A modeled rollout requires an evidence classification")


def answer_owner(run: RunRecord, option: RolloutOption) -> None:
    """Record the only owner answer and advance a paused run."""

    if run.state is not RunState.AWAITING_OWNER:
        raise GateError(f"answer requires AWAITING_OWNER, found {run.state}")
    if option is RolloutOption.UNMODELED:
        raise GateError("UNMODELED is not an owner option")
    if run.owner_answer_count >= MAX_OWNER_ANSWERS:
        raise GateError("The owner answer limit has been reached")
    run.owner_option = option
    run.owner_answer_count += 1
    run.owner_answered_at = utc_now()
    run.state = RunState.READY_TO_RESUME
    if run.decision_ledger is not None:
        run.decision_ledger.state = RunState.READY_TO_RESUME


def show_payload(run: RunRecord) -> dict[str, Any]:
    """Build the stable CLI summary for a run."""

    observed = (
        run.attempts[-1].probe_result.rollout_option
        if run.attempts and run.attempts[-1].probe_result
        else None
    )
    classification = run.reviewer_result.classification if run.reviewer_result else None
    pending_question = None
    if run.state is RunState.AWAITING_OWNER:
        pending_question = "How should existing share links be handled?"
    final_worktree_path = None
    if run.state in (RunState.COMPLETED, RunState.FAILED) and run.attempts:
        final_worktree_path = run.attempts[-1].worktree_path
    return {
        "run_id": run.run_id,
        "state": run.state,
        "observed_option": observed,
        "classification": classification,
        "pending_question": pending_question,
        "owner_option": run.owner_option,
        "attempt_digests": [attempt.migration_digest for attempt in run.attempts],
        "final_worktree_path": final_worktree_path,
        "error": run.error,
    }


def render_show(run: RunRecord) -> str:
    """Render the stable CLI summary as JSON."""

    return json.dumps(show_payload(run), indent=2, default=str)
