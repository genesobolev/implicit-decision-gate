"""Evidence reviewer classification and quote-validation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from implicit_decision_gate.agent import (
    EvidenceReviewer,
    ModelResponse,
    ScriptedModelClient,
)
from implicit_decision_gate.gate import (
    EvidenceClassification,
    ReviewerResult,
    RolloutOption,
    RunRecord,
    RunState,
    sha256_text,
    validate_reviewer_result,
)
from tests.conftest import BRIEF


def make_run(brief: str = BRIEF) -> RunRecord:
    """Build the minimal trace target needed by an evidence review."""

    return RunRecord(
        run_id="a" * 32,
        state=RunState.STARTED,
        repo_path=str(Path.cwd()),
        brief_path="examples/share-link-expiration/brief.md",
        original_brief=brief,
        brief_digest=sha256_text(brief),
        base_commit="b" * 40,
        model_name="scripted-model",
    )


@pytest.mark.parametrize(
    "option",
    [RolloutOption.PRESERVE_EXISTING, RolloutOption.EXPIRE_EXISTING],
)
def test_reference_brief_has_no_evidence_for_either_existing_row_option(
    option: RolloutOption,
) -> None:
    client = ScriptedModelClient(
        [
            ModelResponse.text(
                json.dumps(
                    {
                        "classification": "NOT_EVIDENCED",
                        "evidence_quote": None,
                    }
                )
            )
        ]
    )
    run = make_run()
    result = EvidenceReviewer(client, "scripted-model").review(
        brief=BRIEF,
        option=option,
        run=run,
        persist=lambda: None,
    )
    assert result == ReviewerResult(
        classification=EvidenceClassification.NOT_EVIDENCED,
        evidence_quote=None,
    )
    request_text = json.dumps(client.requests[0])
    assert option.value in request_text
    request_input = cast(list[dict[str, str]], client.requests[0]["input"])
    assert BRIEF in request_input[1]["content"]


@pytest.mark.parametrize(
    ("option", "classification"),
    [
        (RolloutOption.PRESERVE_EXISTING, EvidenceClassification.SUPPORTED),
        (RolloutOption.EXPIRE_EXISTING, EvidenceClassification.CONTRADICTED),
    ],
)
def test_brief_addressing_existing_rows_supports_match_and_contradicts_other(
    option: RolloutOption,
    classification: EvidenceClassification,
) -> None:
    brief = f"{BRIEF}Existing share links must remain non-expiring.\n"
    quote = "Existing share links must remain non-expiring."
    client = ScriptedModelClient(
        [
            ModelResponse.text(
                json.dumps(
                    {
                        "classification": classification.value,
                        "evidence_quote": quote,
                    }
                )
            )
        ]
    )
    result = EvidenceReviewer(client, "scripted-model").review(
        brief=brief,
        option=option,
        run=make_run(brief),
        persist=lambda: None,
    )
    assert result.classification is classification
    assert result.evidence_quote == quote


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
