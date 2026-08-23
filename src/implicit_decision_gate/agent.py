"""Purpose-specific coding and evidence-review model interfaces."""

from __future__ import annotations

from typing import Protocol

from implicit_decision_gate.gate import (
    ROLLOUT_DESCRIPTIONS,
    EvidenceClassification,
    ReviewerResult,
    RolloutOption,
)


class AgentError(RuntimeError):
    """Raised for invalid or unsuccessful model behavior."""


class CodingClient(Protocol):
    """Generate one migration from a complete rendered prompt."""

    def propose_migration(self, prompt: str) -> str:
        """Return complete migration SQL without writing repository files."""


class ReviewerClient(Protocol):
    """Classify one evidence question from a complete rendered prompt."""

    def review_evidence(self, prompt: str) -> ReviewerResult:
        """Return a normalized evidence classification."""


PRESERVE_EXISTING_MIGRATION = """\
-- PRESERVE_EXISTING
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone;

ALTER TABLE public.share_links
    ALTER COLUMN expires_at
    SET DEFAULT (CURRENT_TIMESTAMP + interval '30 days');
"""

EXPIRE_EXISTING_MIGRATION = """\
-- EXPIRE_EXISTING
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone;

UPDATE public.share_links
SET expires_at = CURRENT_TIMESTAMP + interval '30 days';

ALTER TABLE public.share_links
    ALTER COLUMN expires_at
    SET DEFAULT (CURRENT_TIMESTAMP + interval '30 days');
"""


class ScriptedModelClient:
    """Deterministic backend for the supported migration workflow."""

    def propose_migration(self, prompt: str) -> str:
        """Return a stable migration selected from the rendered owner context."""

        if "Owner decision: PRESERVE_EXISTING" in prompt:
            return PRESERVE_EXISTING_MIGRATION
        return EXPIRE_EXISTING_MIGRATION

    def review_evidence(self, prompt: str) -> ReviewerResult:
        """Report that the deliberately incomplete reference brief lacks evidence."""

        del prompt
        return ReviewerResult(
            classification=EvidenceClassification.NOT_EVIDENCED,
            evidence_quote=None,
        )


def build_coding_prompt(
    *,
    brief: str,
    schema: str,
    attempt_number: int,
    owner_option: RolloutOption | None,
) -> str:
    """Render the complete and intentionally narrow coding context."""

    if attempt_number not in (1, 2):
        raise AgentError(f"Unsupported coding attempt: {attempt_number}")
    if attempt_number == 1 and owner_option is not None:
        raise AgentError("Attempt one must not receive an owner decision")
    if attempt_number == 2 and owner_option not in (
        RolloutOption.PRESERVE_EXISTING,
        RolloutOption.EXPIRE_EXISTING,
    ):
        raise AgentError("Attempt two requires a modeled owner option")

    sections = [
        """You create exactly one PostgreSQL migration.
Use only the supplied brief and baseline schema. Do not inspect or edit repository files.
Return the complete migration as structured SQL, without transaction-control statements.
The expires_at column must be a nullable timestamp with time zone. New rows must default
to approximately 30 days from creation.""",
        f"Original brief:\n{brief}",
        f"Baseline schema:\n{schema}",
    ]
    if attempt_number == 2:
        assert owner_option is not None
        sections.append(
            f"Owner decision: {owner_option.value}\n"
            f"Required behavior: {ROLLOUT_DESCRIPTIONS[owner_option]}"
        )
    return "\n\n".join(sections)


def build_reviewer_prompt(*, brief: str, option: RolloutOption) -> str:
    """Render the complete evidence-only review context."""

    if option not in (
        RolloutOption.PRESERVE_EXISTING,
        RolloutOption.EXPIRE_EXISTING,
    ):
        raise AgentError("Evidence review requires a modeled rollout option")
    return (
        "Classify whether the brief explicitly supports the observed existing-row behavior.\n"
        "Return SUPPORTED, CONTRADICTED, NOT_EVIDENCED, or UNCERTAIN. SUPPORTED and\n"
        "CONTRADICTED require an exact quote from the brief; otherwise set evidence_quote\n"
        "to an empty string.\n\n"
        f"Original brief:\n{brief}\n\n"
        f"Observed rollout option: {option.value}\n"
        f"Observed behavior: {ROLLOUT_DESCRIPTIONS[option]}"
    )
