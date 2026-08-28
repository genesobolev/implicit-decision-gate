"""Deterministic authorization observer tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from implicit_decision_gate.api_probe import (
    ADMINISTRATOR_ACCESS,
    CONTAINER_TIMEOUT_SECONDS,
    CREATE_ANOTHER_EXPORT,
    OWNER_AND_ADMIN,
    OWNER_ONLY,
    PROBE_TIMEOUT_SECONDS,
    REPEAT_REQUEST,
    REUSE_ACTIVE_EXPORT,
    AuthorizationObservation,
    DockerAuthorizationProbe,
    RoleResult,
    normalize_authorization,
)
from implicit_decision_gate.scenario import UNMODELED_OUTCOME

OWNER = RoleResult(status=202, jobs_created=1)
DENIED = RoleResult(status=403, jobs_created=0)
REUSED = RoleResult(status=202, jobs_created=0)
INVALID = RoleResult(status=500, jobs_created=0)


@pytest.mark.parametrize(
    ("observation", "administrator_outcome", "repeat_outcome"),
    [
        (AuthorizationObservation(OWNER, OWNER, DENIED, DENIED), OWNER_ONLY, CREATE_ANOTHER_EXPORT),
        (AuthorizationObservation(OWNER, REUSED, DENIED, DENIED), OWNER_ONLY, REUSE_ACTIVE_EXPORT),
        (
            AuthorizationObservation(OWNER, OWNER, OWNER, DENIED),
            OWNER_AND_ADMIN,
            CREATE_ANOTHER_EXPORT,
        ),
        (
            AuthorizationObservation(OWNER, REUSED, OWNER, DENIED),
            OWNER_AND_ADMIN,
            REUSE_ACTIVE_EXPORT,
        ),
        (
            AuthorizationObservation(OWNER, OWNER, INVALID, DENIED),
            UNMODELED_OUTCOME,
            CREATE_ANOTHER_EXPORT,
        ),
        (
            AuthorizationObservation(OWNER, INVALID, DENIED, DENIED),
            OWNER_ONLY,
            UNMODELED_OUTCOME,
        ),
        (
            AuthorizationObservation(OWNER, OWNER, DENIED, INVALID),
            UNMODELED_OUTCOME,
            CREATE_ANOTHER_EXPORT,
        ),
        (
            AuthorizationObservation(INVALID, OWNER, DENIED, DENIED),
            UNMODELED_OUTCOME,
            UNMODELED_OUTCOME,
        ),
    ],
)
def test_normalize_authorization(
    observation: AuthorizationObservation,
    administrator_outcome: str,
    repeat_outcome: str,
) -> None:
    result = normalize_authorization(observation)

    assert result.outcomes == {
        ADMINISTRATOR_ACCESS: administrator_outcome,
        REPEAT_REQUEST: repeat_outcome,
    }
    assert result.facts == {
        "owner_status": observation.owner.status,
        "owner_jobs_created": observation.owner.jobs_created,
        "repeat_owner_status": observation.repeat_owner.status,
        "repeat_owner_jobs_created": observation.repeat_owner.jobs_created,
        "administrator_status": observation.administrator.status,
        "administrator_jobs_created": observation.administrator.jobs_created,
        "member_status": observation.member.status,
        "member_jobs_created": observation.member.jobs_created,
    }


def test_docker_observer_parses_output_with_execution_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = "def create_export(role: str, export_jobs: list[str]) -> int:\n    return 403\n"
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        mount = command[command.index("--mount") + 1]
        source = Path(mount.split(",")[1].removeprefix("source="))
        assert source.read_text(encoding="utf-8") == artifact
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "owner": {"status": 202, "jobs_created": 1},
                    "repeat_owner": {"status": 202, "jobs_created": 0},
                    "administrator": {"status": 403, "jobs_created": 0},
                    "member": {"status": 403, "jobs_created": 0},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DockerAuthorizationProbe().observe(artifact, "unused context")

    command = captured["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--pids-limit") + 1] == "64"
    assert command[command.index("--memory") + 1] == "128m"
    assert command[command.index("--cpus") + 1] == "1"
    assert command[command.index("--mount") + 1].endswith("readonly")
    assert command[command.index("timeout") : command.index("python")] == [
        "timeout",
        "-k",
        "1",
        str(CONTAINER_TIMEOUT_SECONDS),
    ]
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": PROBE_TIMEOUT_SECONDS,
        "check": False,
    }
    assert result.outcomes == {
        ADMINISTRATOR_ACCESS: OWNER_ONLY,
        REPEAT_REQUEST: REUSE_ACTIVE_EXPORT,
    }
