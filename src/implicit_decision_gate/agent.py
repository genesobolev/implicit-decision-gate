"""Purpose-specific coding and evidence-review model interfaces."""

from __future__ import annotations

from typing import Protocol

from implicit_decision_gate.gate import (
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)
from implicit_decision_gate.scenario import DecisionOption, Scenario, option_by_id


class AgentError(RuntimeError):
    """Raised for invalid or unsuccessful model behavior."""


class CodingClient(Protocol):
    """Generate one artifact from a complete rendered prompt."""

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Describe the model process before it is invoked."""

    def propose_artifact(self, prompt: str) -> str:
        """Return one complete artifact without writing repository files."""


class ReviewerClient(Protocol):
    """Classify one evidence question from a complete rendered prompt."""

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Describe the model process before it is invoked."""

    def review_evidence(self, prompt: str) -> ReviewerResult:
        """Return a normalized evidence classification."""


def build_coding_prompt(
    *,
    scenario: Scenario,
    brief: str,
    context: str,
    attempt_number: int,
    owner_option: str | None,
) -> str:
    """Render the complete and intentionally narrow coding context."""

    if attempt_number not in (1, 2):
        raise AgentError(f"Unsupported coding attempt: {attempt_number}")
    if attempt_number == 1 and owner_option is not None:
        raise AgentError("Attempt one must not receive an owner decision")
    selected = option_by_id(scenario.decision, owner_option) if owner_option else None
    if attempt_number == 2 and selected is None:
        raise AgentError("Attempt two requires a modeled owner option")

    sections = [
        scenario.coding_instructions,
        f"Original brief:\n{brief}",
        f"{scenario.context_label}:\n{context}",
    ]
    if selected is not None:
        sections.append(
            f"Authoritative owner decision: {selected.id}\n"
            f"Required behavior: {selected.behavior}\n"
            f"Acceptance criteria: {selected.acceptance_criteria}"
        )
    return "\n\n".join(sections)


def build_reviewer_prompt(*, brief: str, option: DecisionOption) -> str:
    """Render the complete evidence-only review context."""

    return (
        "Classify whether the brief explicitly supports the observed behavior.\n"
        "Return SUPPORTED, CONTRADICTED, NOT_EVIDENCED, or UNCERTAIN. SUPPORTED and\n"
        "CONTRADICTED require an exact quote from the brief; otherwise set evidence_quote\n"
        "to an empty string.\n\n"
        f"Original brief:\n{brief}\n\n"
        f"Observed option: {option.id}\n"
        f"Observed behavior: {option.behavior}"
    )
