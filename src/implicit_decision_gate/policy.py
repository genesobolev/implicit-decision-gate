"""Pure coverage-manifest and effect-policy evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from implicit_decision_gate.postgres_surface import SCHEMA_SHAPE
from implicit_decision_gate.scenario import (
    CoverageResult,
    CoverageRuleSnapshot,
    CoverageRuleSpec,
    CoverageStatus,
    EffectClassifier,
    EffectDisposition,
    EffectDispositionStatus,
    ObservedEffect,
)


class PolicyError(RuntimeError):
    """Raised when an observer or policy violates its declared contract."""


class CoverageManifest(BaseModel):
    """Required and executed coverage for one attempt."""

    policy_id: str
    policy_version: str
    policy_digest: str
    requirements: list[CoverageRuleSnapshot]
    results: list[CoverageResult]


def coverage_evidence_digest(evidence: Mapping[str, Any]) -> str:
    """Return a stable digest for normalized coverage evidence."""

    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def build_coverage_manifest(
    *,
    scenario_id: str,
    policy_version: str,
    policy_digest: str,
    requirements: tuple[CoverageRuleSpec, ...],
    reported: list[CoverageResult],
) -> CoverageManifest:
    """Match observer attestations against every declared coverage rule."""

    requirement_by_id = _unique_by_id(requirements, "coverage requirement")
    reported_by_id = _unique_by_id(reported, "coverage result")
    unknown = sorted(set(reported_by_id) - set(requirement_by_id))
    if unknown:
        raise PolicyError(f"Observer returned undeclared coverage rules: {', '.join(unknown)}")

    results: list[CoverageResult] = []
    for requirement in requirements:
        result = reported_by_id.get(requirement.id)
        if result is None:
            results.append(
                CoverageResult(
                    rule_id=requirement.id,
                    status=(
                        CoverageStatus.MISSING
                        if requirement.required
                        else CoverageStatus.NOT_APPLICABLE
                    ),
                )
            )
            continue
        if requirement.required and result.status is CoverageStatus.NOT_APPLICABLE:
            results.append(
                CoverageResult(
                    rule_id=requirement.id,
                    status=CoverageStatus.MISSING,
                )
            )
            continue
        if result.status is CoverageStatus.PASSED and result.evidence_digest is None:
            raise PolicyError(f"Passed coverage rule has no evidence digest: {result.rule_id}")
        results.append(result)

    return CoverageManifest(
        policy_id=scenario_id,
        policy_version=policy_version,
        policy_digest=policy_digest,
        requirements=[
            CoverageRuleSnapshot(
                id=requirement.id,
                surface_id=requirement.surface_id,
                observer_id=requirement.observer_id,
                observer_version=requirement.observer_version,
                owner=requirement.owner,
                description=requirement.description,
                required=requirement.required,
            )
            for requirement in requirements
        ],
        results=results,
    )


def classify_effects(
    effects: list[ObservedEffect],
    classifiers: tuple[EffectClassifier, ...],
    decisions: dict[str, str],
) -> list[EffectDisposition]:
    """Return exactly one disposition for every observed effect."""

    dispositions: list[EffectDisposition] = []
    for effect in effects:
        claims = [
            (classifier, claimed)
            for classifier in classifiers
            if (claimed := classifier.classify(effect, decisions)) is not None
        ]
        if len(claims) > 1:
            classifier_ids = ", ".join(classifier.id for classifier, _ in claims)
            raise PolicyError(
                f"Effect {effect_identity(effect)} received conflicting policies: {classifier_ids}"
            )
        effect_id = effect_digest(effect)
        if not claims:
            dispositions.append(
                EffectDisposition(
                    effect_id=effect_id,
                    effect=effect,
                    status=EffectDispositionStatus.UNCLASSIFIED,
                    reason="No approved effect policy classified this observed change.",
                )
            )
            continue
        classifier, (status, reason) = claims[0]
        dispositions.append(
            EffectDisposition(
                effect_id=effect_id,
                effect=effect,
                status=status,
                policy_id=classifier.id,
                policy_version=classifier.version,
                reason=reason,
            )
        )
    return dispositions


def effect_digest(effect: ObservedEffect) -> str:
    """Return a stable identifier for an observed effect."""

    payload = json.dumps(effect.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def effect_identity(effect: ObservedEffect) -> str:
    """Return a compact human-readable effect identity."""

    return f"{effect.rule_id}:{effect.change}:{effect.identity}:{effect.attribute}"


@dataclass(frozen=True)
class ShareLinkExpirationEffectClassifier:
    """Authorize only the requested expiration column and forbid removals."""

    id: str = "share_link_expiration_effect_policy"
    version: str = "1"

    def classify(
        self,
        effect: ObservedEffect,
        decisions: dict[str, str],
    ) -> tuple[EffectDispositionStatus, str] | None:
        del decisions
        if (
            effect.rule_id == SCHEMA_SHAPE
            and effect.object_kind == "column"
            and effect.identity == "public.share_links.expires_at"
            and effect.change == "ADDED"
        ):
            return (
                EffectDispositionStatus.EXPECTED,
                "The brief requires the public.share_links.expires_at column.",
            )
        if effect.change == "REMOVED":
            return (
                EffectDispositionStatus.FORBIDDEN,
                "The expiration change isn't authorized to remove existing database structure.",
            )
        return None


def _unique_by_id(values: tuple[Any, ...] | list[Any], label: str) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for value in values:
        value_id = str(value.id if hasattr(value, "id") else value.rule_id)
        if value_id in indexed:
            raise PolicyError(f"Duplicate {label}: {value_id}")
        indexed[value_id] = value
    return indexed
