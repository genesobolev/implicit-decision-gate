"""Shared fixtures for isolated repository orchestration tests."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from implicit_decision_gate.agent import AgentError
from implicit_decision_gate.api_probe import (
    ADMINISTRATOR_ACCESS,
    CREATE_ANOTHER_EXPORT,
    OWNER_AND_ADMIN,
    OWNER_ONLY,
    REPEAT_REQUEST,
    REUSE_ACTIVE_EXPORT,
)
from implicit_decision_gate.gate import (
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)
from implicit_decision_gate.probe import (
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
)
from implicit_decision_gate.scenario import UNMODELED_OUTCOME, ObservationResult, Scenario
from implicit_decision_gate.scenarios import scenario_registry

BRIEF = """Add 30-day expiration support to item-sharing links.

Store expiration in `public.share_links.expires_at` as a nullable timestamp with time
zone. New item-sharing links must expire 30 days after creation.
"""
SCHEMA = """CREATE TABLE public.share_links (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token text NOT NULL UNIQUE,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO public.share_links (token) VALUES ('existing-fixture');
"""
AUTH_BRIEF = """Add workspace export creation.

When no export job exists, workspace owners must receive 202 and create one export job.
Workspace members must be denied with 403 and create no export job.
"""
AUTH_HANDLER = '''"""Baseline contract for workspace export creation."""


def create_export(role: str, export_jobs: list[str]) -> int:
    """Return the result; export_jobs contains the workspace's existing jobs."""

    raise NotImplementedError
'''


class ScriptedCodingClient:
    """Return deterministic artifacts while recording coding context."""

    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Return deterministic provenance for the scripted invocation."""

        return ModelInvocationRecord(
            role=role,
            attempt_number=attempt_number,
            model="scripted-coding-client",
            reasoning_effort="deterministic",
            codex_cli_version="not-applicable",
        )

    def propose_artifact(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AgentError("The scripted coding response queue is empty")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ScriptedReviewerClient:
    """Return deterministic reviews while recording reviewer context."""

    def __init__(self, responses: Sequence[ReviewerResult | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Return deterministic provenance for the scripted invocation."""

        return ModelInvocationRecord(
            role=role,
            attempt_number=attempt_number,
            model="scripted-reviewer-client",
            reasoning_effort="deterministic",
            codex_cli_version="not-applicable",
        )

    def review_evidence(self, prompt: str) -> ReviewerResult:
        self.prompts.append(prompt)
        if not self.responses:
            raise AgentError("The scripted reviewer response queue is empty")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def run_git(repo: Path, *arguments: str) -> str:
    """Run Git in a test repository."""

    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def reference_repo(tmp_path: Path) -> Path:
    """Create the exact supported repository shape with one base commit."""

    repo = tmp_path / "repo"
    example = repo / "examples" / "share-link-expiration"
    migrations = example / "migrations"
    migrations.mkdir(parents=True)
    (example / "brief.md").write_text(BRIEF, encoding="utf-8")
    (example / "schema.sql").write_text(SCHEMA, encoding="utf-8")
    (migrations / ".gitkeep").write_text("", encoding="utf-8")
    authorization = repo / "examples" / "workspace-export-authorization"
    implementations = authorization / "implementations"
    implementations.mkdir(parents=True)
    (authorization / "brief.md").write_text(AUTH_BRIEF, encoding="utf-8")
    (authorization / "handler.py").write_text(AUTH_HANDLER, encoding="utf-8")
    (implementations / ".gitkeep").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text(".idg/\n", encoding="utf-8")
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", ".")
    run_git(
        repo,
        "-c",
        "user.name=IDG Tests",
        "-c",
        "user.email=idg@example.invalid",
        "commit",
        "-m",
        "reference fixture",
    )
    return repo


@dataclass
class ScriptMarkerProbe:
    """Classify explicit artifact markers without external execution."""

    calls: int = 0

    def observe(self, artifact: str, context: str) -> ObservationResult:
        self.calls += 1
        if "create_export" in context:
            administrator = UNMODELED_OUTCOME
            if OWNER_AND_ADMIN in artifact:
                administrator = OWNER_AND_ADMIN
            elif OWNER_ONLY in artifact:
                administrator = OWNER_ONLY
            repeat = UNMODELED_OUTCOME
            if CREATE_ANOTHER_EXPORT in artifact:
                repeat = CREATE_ANOTHER_EXPORT
            elif REUSE_ACTIVE_EXPORT in artifact:
                repeat = REUSE_ACTIVE_EXPORT
            return ObservationResult(
                outcomes={
                    ADMINISTRATOR_ACCESS: administrator,
                    REPEAT_REQUEST: repeat,
                }
            )
        if PRESERVE_EXISTING in artifact:
            assert "share_links" in context
            option = PRESERVE_EXISTING
            existing = "null"
        elif EXPIRE_EXISTING in artifact:
            assert "share_links" in context
            option = EXPIRE_EXISTING
            existing = "approximately_migration_time_plus_30_days"
        else:
            option = UNMODELED_OUTCOME
            existing = "other"
        return ObservationResult(
            outcomes={EXISTING_LINK_ROLLOUT: option},
            facts={
                "data_type": "timestamp with time zone",
                "nullable": True,
                "column_default": "CURRENT_TIMESTAMP + interval '30 days'",
                "insert_without_value": "approximately_now_plus_30_days",
                "existing_row": existing,
                "rollback_verified": True,
            },
        )


def scripted_scenarios(observer: ScriptMarkerProbe) -> dict[str, Scenario]:
    """Build both scenarios around one deterministic observer."""

    return scenario_registry(observer, observer)
