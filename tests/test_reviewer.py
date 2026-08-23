"""Evidence-review and quote-validation tests."""

from __future__ import annotations

import pytest

from implicit_decision_gate.agent import build_reviewer_prompt
from implicit_decision_gate.gate import (
    EvidenceClassification,
    ReviewerResult,
    RolloutOption,
    RunState,
    state_after_review,
    validate_reviewer_result,
)
from tests.conftest import BRIEF


@pytest.mark.parametrize(
    "option",
    [RolloutOption.PRESERVE_EXISTING, RolloutOption.EXPIRE_EXISTING],
)
def test_reviewer_prompt_contains_brief_and_observed_policy(
    option: RolloutOption,
) -> None:
    prompt = build_reviewer_prompt(brief=BRIEF, option=option)

    assert BRIEF in prompt
    assert option.value in prompt


@pytest.mark.parametrize(
    ("classification", "expected_state"),
    [
        (EvidenceClassification.SUPPORTED, RunState.COMPLETED),
        (EvidenceClassification.NOT_EVIDENCED, RunState.AWAITING_OWNER),
        (EvidenceClassification.UNCERTAIN, RunState.AWAITING_OWNER),
        (EvidenceClassification.CONTRADICTED, RunState.FAILED),
    ],
)
def test_review_classification_drives_gate_state(
    classification: EvidenceClassification,
    expected_state: RunState,
) -> None:
    assert state_after_review(classification) is expected_state


def test_fabricated_evidence_quote_becomes_uncertain() -> None:
    result = validate_reviewer_result(
        BRIEF,
        ReviewerResult(
            classification=EvidenceClassification.SUPPORTED,
            evidence_quote="Existing links explicitly remain forever.",
        ),
    )

    assert result == ReviewerResult(
        classification=EvidenceClassification.UNCERTAIN,
        evidence_quote=None,
    )
