"""Coding-context isolation tests."""

from __future__ import annotations

from implicit_decision_gate.agent import (
    build_coding_prompt,
    build_reviewer_prompt,
)
from implicit_decision_gate.gate import (
    RolloutOption,
)


def test_first_coding_prompt_contains_only_declared_inputs() -> None:
    prompt = build_coding_prompt(
        brief="ORIGINAL_BRIEF",
        schema="CREATE TABLE public.share_links (id bigint);",
        attempt_number=1,
        owner_option=None,
    )

    assert "ORIGINAL_BRIEF" in prompt
    assert "CREATE TABLE public.share_links" in prompt
    assert "Owner decision" not in prompt


def test_attempt_two_prompt_contains_only_allowed_fresh_context() -> None:
    reviewer_prompt = build_reviewer_prompt(
        brief="ORIGINAL_BRIEF",
        option=RolloutOption.PRESERVE_EXISTING,
    )
    prompt = build_coding_prompt(
        brief="ORIGINAL_BRIEF",
        schema="BASELINE_SCHEMA",
        attempt_number=2,
        owner_option=RolloutOption.EXPIRE_EXISTING,
    )

    assert "ORIGINAL_BRIEF" in prompt
    assert "BASELINE_SCHEMA" in prompt
    assert "Owner decision: EXPIRE_EXISTING" in prompt
    assert reviewer_prompt not in prompt
    assert "first migration" not in prompt.lower()
    assert "reviewer" not in prompt.lower()
