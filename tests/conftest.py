"""Shared fixtures for isolated repository orchestration tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from implicit_decision_gate.gate import ProbeResult, RolloutOption

BRIEF = (
    "Add expiration support to share links.\n"
    "Store it in public.share_links.expires_at as a nullable timestamp with time zone.\n"
    "New share links should expire 30 days after creation.\n"
)
SCHEMA = """CREATE TABLE public.share_links (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token text NOT NULL UNIQUE,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO public.share_links (token) VALUES ('existing-fixture');
"""


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
