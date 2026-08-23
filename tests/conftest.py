"""Shared fixtures for isolated repository orchestration tests."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from implicit_decision_gate.agent import AgentError
from implicit_decision_gate.gate import ProbeResult, ReviewerResult, RolloutOption

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


class ScriptedCodingClient:
    """Return deterministic migrations while recording coding context."""

    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def propose_migration(self, prompt: str) -> str:
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
    """Classify explicit SQL markers without requiring PostgreSQL."""

    calls: int = 0

    def probe(self, migration: str, baseline_schema: str) -> ProbeResult:
        self.calls += 1
        assert "share_links" in baseline_schema
        if "PRESERVE_EXISTING" in migration:
            option = RolloutOption.PRESERVE_EXISTING
            existing = "null"
        elif "EXPIRE_EXISTING" in migration:
            option = RolloutOption.EXPIRE_EXISTING
            existing = "approximately_migration_time_plus_30_days"
        else:
            option = RolloutOption.UNMODELED
            existing = "other"
        return ProbeResult(
            data_type="timestamp with time zone",
            nullable=True,
            column_default="CURRENT_TIMESTAMP + interval '30 days'",
            insert_without_value="approximately_now_plus_30_days",
            existing_row=existing,
            rollout_option=option,
            rollback_verified=True,
        )
