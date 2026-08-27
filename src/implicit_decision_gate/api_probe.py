"""Disposable execution and normalization for the authorization scenario."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from implicit_decision_gate.scenario import UNMODELED_OUTCOME, ObservationResult

OWNER_ONLY = "OWNER_ONLY"
OWNER_AND_ADMIN = "OWNER_AND_ADMIN"
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

results = {}
for role in ("owner", "administrator", "member"):
    jobs = []
    with contextlib.redirect_stdout(io.StringIO()):
        status = module.create_export(role, jobs)
    results[role] = {"status": status, "jobs_created": len(jobs)}
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
    administrator: RoleResult
    member: RoleResult


def normalize_authorization(observation: AuthorizationObservation) -> ObservationResult:
    """Map role behavior to one of the two supported authorization policies."""

    outcome = UNMODELED_OUTCOME
    required_behavior_matches = observation.owner == RoleResult(
        status=202, jobs_created=1
    ) and observation.member == RoleResult(status=403, jobs_created=0)
    if required_behavior_matches:
        if observation.administrator == RoleResult(status=403, jobs_created=0):
            outcome = OWNER_ONLY
        elif observation.administrator == RoleResult(status=202, jobs_created=1):
            outcome = OWNER_AND_ADMIN

    return ObservationResult(
        outcome=outcome,
        facts={
            "owner_status": observation.owner.status,
            "owner_jobs_created": observation.owner.jobs_created,
            "administrator_status": observation.administrator.status,
            "administrator_jobs_created": observation.administrator.jobs_created,
            "member_status": observation.member.status,
            "member_jobs_created": observation.member.jobs_created,
        },
    )


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
