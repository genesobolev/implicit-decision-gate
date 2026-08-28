"""Evidence-review and quote-validation tests."""

from __future__ import annotations

import pytest

from implicit_decision_gate.agent import build_reviewer_prompt
from implicit_decision_gate.api_probe import DockerAuthorizationProbe
from implicit_decision_gate.gate import (
    EvidenceClassification,
    ReviewerResult,
    RunState,
    state_after_reviews,
    validate_reviewer_result,
)
from implicit_decision_gate.probe import COMPOSE_ADMIN_DSN, PostgresProbe
from implicit_decision_gate.scenario import DecisionOption
from implicit_decision_gate.scenarios import (
    SHARE_LINK_EXPIRATION,
    WORKSPACE_EXPORT_AUTHORIZATION,
    scenario_registry,
)
from tests.conftest import BRIEF

SCENARIOS = scenario_registry(
    PostgresProbe(COMPOSE_ADMIN_DSN),
    DockerAuthorizationProbe(),
)
SHARE_LINK_SCENARIO = SCENARIOS[SHARE_LINK_EXPIRATION]
AUTHORIZATION_SCENARIO = SCENARIOS[WORKSPACE_EXPORT_AUTHORIZATION]


@pytest.mark.parametrize(
    "option",
    SHARE_LINK_SCENARIO.decisions[0].options,
)
def test_reviewer_prompt_contains_brief_and_observed_policy(
    option: DecisionOption,
) -> None:
    prompt = build_reviewer_prompt(brief=BRIEF, option=option)

    assert BRIEF in prompt
    assert option.id in prompt
    assert option.behavior in prompt


def test_reviewer_options_describe_only_the_missing_decision() -> None:
    share_link_behavior = " ".join(
        option.behavior for option in SHARE_LINK_SCENARIO.decisions[0].options
    )
    administrator_behavior = " ".join(
        option.behavior for option in AUTHORIZATION_SCENARIO.decisions[0].options
    )
    repeat_behavior = " ".join(
        option.behavior for option in AUTHORIZATION_SCENARIO.decisions[1].options
    )

    assert "new links" not in share_link_behavior
    assert "owners" not in administrator_behavior.lower()
    assert "members" not in administrator_behavior.lower()
    assert "administrator" not in repeat_behavior.lower()


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
    assert state_after_reviews([classification]) is expected_state


def test_review_classifications_are_aggregated() -> None:
    assert (
        state_after_reviews(
            [EvidenceClassification.SUPPORTED, EvidenceClassification.NOT_EVIDENCED]
        )
        is RunState.AWAITING_OWNER
    )
    assert (
        state_after_reviews(
            [EvidenceClassification.NOT_EVIDENCED, EvidenceClassification.CONTRADICTED]
        )
        is RunState.FAILED
    )


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
