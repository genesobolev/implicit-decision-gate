"""Coding-context isolation tests."""

from __future__ import annotations

from implicit_decision_gate.agent import (
    build_coding_prompt,
    build_reviewer_prompt,
)
from implicit_decision_gate.api_probe import DockerAuthorizationProbe
from implicit_decision_gate.probe import (
    COMPOSE_ADMIN_DSN,
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
    PostgresProbe,
)
from implicit_decision_gate.scenario import DecisionOption
from implicit_decision_gate.scenarios import (
    SHARE_LINK_EXPIRATION,
    scenario_registry,
)

SHARE_LINK_SCENARIO = scenario_registry(
    PostgresProbe(COMPOSE_ADMIN_DSN),
    DockerAuthorizationProbe(),
)[SHARE_LINK_EXPIRATION]


def rollout_option(option_id: str) -> DecisionOption:
    """Return one share-link rollout option."""

    return next(
        option for option in SHARE_LINK_SCENARIO.decisions[0].options if option.id == option_id
    )


def test_first_coding_prompt_contains_only_declared_inputs() -> None:
    prompt = build_coding_prompt(
        scenario=SHARE_LINK_SCENARIO,
        brief="ORIGINAL_BRIEF",
        context="CREATE TABLE public.share_links (id bigint);",
        attempt_number=1,
        owner_options=None,
    )

    assert "ORIGINAL_BRIEF" in prompt
    assert "CREATE TABLE public.share_links" in prompt
    assert "owner decision" not in prompt.lower()


def test_coding_prompt_envelope_does_not_repeat_product_requirements() -> None:
    prompt = build_coding_prompt(
        scenario=SHARE_LINK_SCENARIO,
        brief="AUTHORITATIVE_PRODUCT_REQUIREMENTS",
        context="BASELINE_SCHEMA",
        attempt_number=1,
        owner_options=None,
    )
    envelope = prompt.split("Original brief:", maxsplit=1)[0]

    assert "expires_at" not in envelope
    assert "30 days" not in envelope


def test_attempt_two_prompt_contains_only_allowed_fresh_context() -> None:
    reviewer_prompt = build_reviewer_prompt(
        brief="ORIGINAL_BRIEF",
        option=rollout_option(PRESERVE_EXISTING),
    )
    prompt = build_coding_prompt(
        scenario=SHARE_LINK_SCENARIO,
        brief="ORIGINAL_BRIEF",
        context="BASELINE_SCHEMA",
        attempt_number=2,
        owner_options={EXISTING_LINK_ROLLOUT: EXPIRE_EXISTING},
    )

    assert "ORIGINAL_BRIEF" in prompt
    assert "BASELINE_SCHEMA" in prompt
    assert f"Authoritative owner decision for {EXISTING_LINK_ROLLOUT}: EXPIRE_EXISTING" in prompt
    assert "approximately 30 days after migration time" in prompt
    assert reviewer_prompt not in prompt
    assert "first migration" not in prompt.lower()
    assert "reviewer" not in prompt.lower()


def test_preserve_decision_explains_postgres_default_semantics() -> None:
    prompt = build_coding_prompt(
        scenario=SHARE_LINK_SCENARIO,
        brief="ORIGINAL_BRIEF",
        context="BASELINE_SCHEMA",
        attempt_number=2,
        owner_options={EXISTING_LINK_ROLLOUT: PRESERVE_EXISTING},
    )

    assert "seeded pre-existing row must read expires_at IS NULL" in prompt
    assert "add the nullable column without a default" in prompt
