"""Deterministic authorization observer tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from implicit_decision_gate.api_probe import (
    CONTAINER_TIMEOUT_SECONDS,
    OWNER_AND_ADMIN,
    OWNER_ONLY,
    PROBE_TIMEOUT_SECONDS,
    AuthorizationObservation,
    DockerAuthorizationProbe,
    RoleResult,
    normalize_authorization,
)
from implicit_decision_gate.scenario import UNMODELED_OUTCOME


@pytest.mark.parametrize(
    ("observation", "expected_outcome"),
    [
        (
            AuthorizationObservation(
                owner=RoleResult(status=202, jobs_created=1),
                administrator=RoleResult(status=403, jobs_created=0),
                member=RoleResult(status=403, jobs_created=0),
            ),
            OWNER_ONLY,
        ),
        (
            AuthorizationObservation(
                owner=RoleResult(status=202, jobs_created=1),
                administrator=RoleResult(status=202, jobs_created=1),
                member=RoleResult(status=403, jobs_created=0),
            ),
            OWNER_AND_ADMIN,
        ),
        (
            AuthorizationObservation(
                owner=RoleResult(status=202, jobs_created=0),
                administrator=RoleResult(status=202, jobs_created=1),
                member=RoleResult(status=403, jobs_created=0),
            ),
            UNMODELED_OUTCOME,
        ),
    ],
)
def test_normalize_authorization(
    observation: AuthorizationObservation,
    expected_outcome: str,
) -> None:
    result = normalize_authorization(observation)

    assert result.outcome == expected_outcome
    assert result.facts == {
        "owner_status": observation.owner.status,
        "owner_jobs_created": observation.owner.jobs_created,
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
    assert result.outcome == OWNER_ONLY
