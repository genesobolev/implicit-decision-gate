"""Disposable execution and normalization for the authorization scenario."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from implicit_decision_gate.policy import coverage_evidence_digest
from implicit_decision_gate.scenario import (
    CoverageResult,
    CoverageStatus,
    DecisionObservation,
    FactValue,
    InvariantResult,
    InvariantStatus,
    ObservationResult,
    UnknownEffect,
)

OWNER_ONLY = "OWNER_ONLY"
OWNER_AND_ADMIN = "OWNER_AND_ADMIN"
CREATE_ANOTHER_EXPORT = "CREATE_ANOTHER_EXPORT"
REUSE_ACTIVE_EXPORT = "REUSE_ACTIVE_EXPORT"
ADMINISTRATOR_ACCESS = "workspace_export_administrator_access"
REPEAT_REQUEST = "workspace_export_repeat_request"
OWNER_FIRST_REQUEST_INVARIANT = "workspace_export_owner_first_request"
MEMBER_DENIAL_INVARIANT = "workspace_export_member_denial"
API_OWNER_COVERAGE = "api.owner_first_request"
API_MEMBER_COVERAGE = "api.member_denial"
API_ADMINISTRATOR_COVERAGE = "api.administrator_access"
API_REPEAT_COVERAGE = "api.owner_repeat_request"
API_OBSERVER_ID = "docker_authorization_probe"
API_OBSERVER_VERSION = "1"
PYTHON_IMAGE = "python:3.12-alpine"
PROBE_TIMEOUT_SECONDS = 60
CONTAINER_TIMEOUT_SECONDS = 30

RUNNER = """
import contextlib
import importlib.util
import io
import json

spec = importlib.util.spec_from_file_location("generated_handler", "/probe/artifact.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load generated handler")
module = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(module)

def call(role, jobs):
    before = len(jobs)
    with contextlib.redirect_stdout(io.StringIO()):
        status = module.create_export(role, jobs)
    return {"status": status, "jobs_created": len(jobs) - before}

owner_jobs = []
results = {
    "owner": call("owner", owner_jobs),
    "repeat_owner": call("owner", owner_jobs),
    "administrator": call("administrator", []),
    "member": call("member", []),
}
print(json.dumps(results))
"""


class ApiProbeError(RuntimeError):
    """Raised when the generated authorization handler cannot be observed."""


@dataclass(frozen=True)
class RoleResult:
    """Status and side effect observed for one caller role."""

    status: int
    jobs_created: int


@dataclass(frozen=True)
class AuthorizationObservation:
    """Observed behavior for all three modeled caller roles."""

    owner: RoleResult
    repeat_owner: RoleResult
    administrator: RoleResult
    member: RoleResult


def normalize_authorization(observation: AuthorizationObservation) -> ObservationResult:
    """Separate required behavior, modeled choices, and unknown effects."""

    first_owner_matches = observation.owner == RoleResult(status=202, jobs_created=1)
    member_matches = observation.member == RoleResult(status=403, jobs_created=0)
    facts: dict[str, FactValue] = {
        "owner_status": observation.owner.status,
        "owner_jobs_created": observation.owner.jobs_created,
        "repeat_owner_status": observation.repeat_owner.status,
        "repeat_owner_jobs_created": observation.repeat_owner.jobs_created,
        "administrator_status": observation.administrator.status,
        "administrator_jobs_created": observation.administrator.jobs_created,
        "member_status": observation.member.status,
        "member_jobs_created": observation.member.jobs_created,
    }
    owner_evidence = {
        "status": observation.owner.status,
        "jobs_created": observation.owner.jobs_created,
    }
    member_evidence = {
        "status": observation.member.status,
        "jobs_created": observation.member.jobs_created,
    }
    administrator_evidence = {
        "status": observation.administrator.status,
        "jobs_created": observation.administrator.jobs_created,
    }
    repeat_evidence = {
        "status": observation.repeat_owner.status,
        "jobs_created": observation.repeat_owner.jobs_created,
    }
    decisions: list[DecisionObservation] = []
    unknown_effects: list[UnknownEffect] = []
    if observation.administrator == RoleResult(status=403, jobs_created=0):
        decisions.append(
            DecisionObservation(
                decision_id=ADMINISTRATOR_ACCESS,
                option_id=OWNER_ONLY,
                evidence=administrator_evidence,
            )
        )
    elif observation.administrator == RoleResult(status=202, jobs_created=1):
        decisions.append(
            DecisionObservation(
                decision_id=ADMINISTRATOR_ACCESS,
                option_id=OWNER_AND_ADMIN,
                evidence=administrator_evidence,
            )
        )
    else:
        unknown_effects.append(
            UnknownEffect(
                surface_id="workspace_export_api",
                rule_id=API_ADMINISTRATOR_COVERAGE,
                decision_id=ADMINISTRATOR_ACCESS,
                description="Administrator behavior is outside the approved decision vocabulary.",
                evidence=administrator_evidence,
            )
        )

    if observation.repeat_owner == RoleResult(status=202, jobs_created=1):
        decisions.append(
            DecisionObservation(
                decision_id=REPEAT_REQUEST,
                option_id=CREATE_ANOTHER_EXPORT,
                evidence=repeat_evidence,
            )
        )
    elif observation.repeat_owner == RoleResult(status=202, jobs_created=0):
        decisions.append(
            DecisionObservation(
                decision_id=REPEAT_REQUEST,
                option_id=REUSE_ACTIVE_EXPORT,
                evidence=repeat_evidence,
            )
        )
    else:
        unknown_effects.append(
            UnknownEffect(
                surface_id="workspace_export_api",
                rule_id=API_REPEAT_COVERAGE,
                decision_id=REPEAT_REQUEST,
                description="Repeated-owner behavior is outside the approved decision vocabulary.",
                evidence=repeat_evidence,
            )
        )

    return ObservationResult(
        invariants=[
            InvariantResult(
                invariant_id=OWNER_FIRST_REQUEST_INVARIANT,
                expected="Return 202 and create exactly one export job.",
                observed=_role_description(observation.owner),
                status=InvariantStatus.PASSED if first_owner_matches else InvariantStatus.VIOLATED,
                evidence=owner_evidence,
            ),
            InvariantResult(
                invariant_id=MEMBER_DENIAL_INVARIANT,
                expected="Return 403 and create no export job.",
                observed=_role_description(observation.member),
                status=InvariantStatus.PASSED if member_matches else InvariantStatus.VIOLATED,
                evidence=member_evidence,
            ),
        ],
        decisions=decisions,
        unknown_effects=unknown_effects,
        facts=facts,
        coverage=[
            _coverage_result(API_OWNER_COVERAGE, owner_evidence),
            _coverage_result(API_MEMBER_COVERAGE, member_evidence),
            _coverage_result(API_ADMINISTRATOR_COVERAGE, administrator_evidence),
            _coverage_result(API_REPEAT_COVERAGE, repeat_evidence),
        ],
    )


def _coverage_result(rule_id: str, evidence: Mapping[str, FactValue]) -> CoverageResult:
    return CoverageResult(
        rule_id=rule_id,
        status=CoverageStatus.PASSED,
        evidence_digest=coverage_evidence_digest(evidence),
    )


def _role_description(result: RoleResult) -> str:
    return f"Returned {result.status} and created {result.jobs_created} export jobs."


class DockerAuthorizationProbe:
    """Execute one generated handler in a disposable network-disabled container."""

    def observe(self, artifact: str, context: str) -> ObservationResult:
        """Run the handler for each modeled role and normalize its effects."""

        del context
        with tempfile.TemporaryDirectory(prefix="idg-api-probe-") as temporary_value:
            artifact_path = Path(temporary_value) / "artifact.py"
            artifact_path.write_text(artifact, encoding="utf-8")
            artifact_path.chmod(0o444)
            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--pids-limit",
                "64",
                "--memory",
                "128m",
                "--cpus",
                "1",
                "--mount",
                f"type=bind,source={artifact_path},target=/probe/artifact.py,readonly",
                PYTHON_IMAGE,
                "timeout",
                "-k",
                "1",
                str(CONTAINER_TIMEOUT_SECONDS),
                "python",
                "-c",
                RUNNER,
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ApiProbeError(
                    f"Authorization probe timed out after {PROBE_TIMEOUT_SECONDS} seconds"
                ) from error
            except OSError as error:
                raise ApiProbeError(f"Could not start authorization probe: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ApiProbeError(f"Authorization probe failed: {detail[-1000:]}")
        return normalize_authorization(_parse_observation(completed.stdout))


def _parse_observation(payload: str) -> AuthorizationObservation:
    try:
        decoded = json.loads(payload)
        return AuthorizationObservation(
            owner=_parse_role(decoded, "owner"),
            repeat_owner=_parse_role(decoded, "repeat_owner"),
            administrator=_parse_role(decoded, "administrator"),
            member=_parse_role(decoded, "member"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ApiProbeError("Authorization probe returned invalid JSON") from error


def _parse_role(payload: Any, role: str) -> RoleResult:
    if not isinstance(payload, dict):
        raise TypeError("Probe payload must be an object")
    role_payload = payload[role]
    if not isinstance(role_payload, dict):
        raise TypeError("Role result must be an object")
    status = role_payload["status"]
    jobs_created = role_payload["jobs_created"]
    if type(status) is not int or type(jobs_created) is not int:
        raise TypeError("Role status and job count must be integers")
    return RoleResult(status=status, jobs_created=jobs_created)
