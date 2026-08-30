"""Effect-policy and coverage-manifest tests."""

import pytest

from implicit_decision_gate.policy import (
    PolicyError,
    ShareLinkExpirationEffectClassifier,
    build_coverage_manifest,
    classify_effects,
    coverage_evidence_digest,
)
from implicit_decision_gate.scenario import (
    CoverageResult,
    CoverageRuleSpec,
    CoverageStatus,
    EffectDispositionStatus,
    ObservedEffect,
)


def test_every_effect_receives_a_policy_disposition() -> None:
    effects = [
        ObservedEffect(
            rule_id="schema_shape",
            change="ADDED",
            object_kind="column",
            identity="public.share_links.expires_at",
            attribute="data_type",
            after="timestamp with time zone",
        ),
        ObservedEffect(
            rule_id="data_integrity",
            change="REMOVED",
            object_kind="constraint",
            identity="public.share_links.share_links_token_key",
            attribute="definition",
            before="UNIQUE (token)",
        ),
        ObservedEffect(
            rule_id="indexing",
            change="ADDED",
            object_kind="index",
            identity="public.share_links.unrelated_idx",
            attribute="definition",
            after="CREATE INDEX unrelated_idx ON public.share_links (created_at)",
        ),
    ]

    dispositions = classify_effects(
        effects,
        (ShareLinkExpirationEffectClassifier(),),
        {},
    )

    assert [item.status for item in dispositions] == [
        EffectDispositionStatus.EXPECTED,
        EffectDispositionStatus.FORBIDDEN,
        EffectDispositionStatus.UNCLASSIFIED,
    ]
    assert len({item.effect_id for item in dispositions}) == len(effects)


def test_missing_required_coverage_is_explicit() -> None:
    requirements = (
        CoverageRuleSpec(
            id="api.owner",
            surface_id="api",
            observer_id="observer",
            observer_version="1",
            owner="platform",
            description="Observe the owner request.",
        ),
        CoverageRuleSpec(
            id="api.member",
            surface_id="api",
            observer_id="observer",
            observer_version="1",
            owner="platform",
            description="Observe the member request.",
        ),
    )
    manifest = build_coverage_manifest(
        scenario_id="authorization",
        policy_version="1",
        policy_digest="policy-digest",
        requirements=requirements,
        reported=[
            CoverageResult(
                rule_id="api.owner",
                status=CoverageStatus.PASSED,
                evidence_digest=coverage_evidence_digest({"status": 202}),
            )
        ],
    )

    assert [result.status for result in manifest.results] == [
        CoverageStatus.PASSED,
        CoverageStatus.MISSING,
    ]


def test_required_coverage_cannot_claim_not_applicable() -> None:
    requirement = CoverageRuleSpec(
        id="required",
        surface_id="surface",
        observer_id="observer",
        observer_version="1",
        owner="platform",
        description="Required evidence",
    )

    manifest = build_coverage_manifest(
        scenario_id="scenario",
        policy_version="1",
        policy_digest="digest",
        requirements=(requirement,),
        reported=[CoverageResult(rule_id="required", status=CoverageStatus.NOT_APPLICABLE)],
    )

    assert manifest.results == [CoverageResult(rule_id="required", status=CoverageStatus.MISSING)]


def test_conflicting_effect_classifiers_are_a_policy_error() -> None:
    effect = ObservedEffect(
        rule_id="schema_shape",
        change="ADDED",
        object_kind="column",
        identity="public.share_links.expires_at",
        attribute="data_type",
        after="timestamp with time zone",
    )
    classifier = ShareLinkExpirationEffectClassifier()

    with pytest.raises(PolicyError, match="conflicting policies"):
        classify_effects([effect], (classifier, classifier), {})
