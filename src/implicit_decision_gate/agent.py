"""Purpose-specific coding and evidence-review model interfaces."""

from __future__ import annotations

from typing import Protocol

from implicit_decision_gate.gate import (
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)
from implicit_decision_gate.scenario import (
    DecisionOption,
    Scenario,
    option_by_id,
)


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
    owner_options: dict[str, str] | None,
) -> str:
    """Render the complete and intentionally narrow coding context."""

    if attempt_number not in (1, 2):
        raise AgentError(f"Unsupported coding attempt: {attempt_number}")
    if attempt_number == 1 and owner_options is not None:
        raise AgentError("Attempt one must not receive owner decisions")
    if attempt_number == 2 and not owner_options:
        raise AgentError("Attempt two requires modeled owner decisions")

    sections = [
        scenario.coding_instructions,
        f"Original brief:\n{brief}",
        f"{scenario.context_label}:\n{context}",
    ]
    for decision in scenario.decisions:
        option_id = owner_options.get(decision.id) if owner_options else None
        if option_id is None:
            continue
        selected = option_by_id(decision, option_id)
        if selected is None:
            raise AgentError(f"{option_id} is not an option for {decision.id}")
        sections.append(
            f"Authoritative owner decision for {decision.id}: {selected.id}\n"
            f"Required behavior: {selected.behavior}\n"
            f"Acceptance criteria: {selected.acceptance_criteria}"
        )
    if owner_options:
        unknown = set(owner_options) - {decision.id for decision in scenario.decisions}
        if unknown:
            decision_id = sorted(unknown)[0]
            raise AgentError(f"Unknown owner decision: {decision_id}")
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
