"""Creation of clean detached Git worktrees."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    """Raised when Git cannot create an isolated attempt checkout."""


@dataclass(frozen=True)
class Worktree:
    """A verified detached worktree."""

    path: Path
    base_commit: str
    clean_start_verified: bool


def _git(repo_path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise WorktreeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


class WorktreeManager:
    """Manage worktrees below a configurable path outside the checkout."""

    def __init__(self, repo_path: Path, worktree_root: Path) -> None:
        self.repo_path = repo_path.resolve()
        self.worktree_root = worktree_root.resolve()
        if self.worktree_root == self.repo_path or self.worktree_root.is_relative_to(
            self.repo_path
        ):
            raise WorktreeError("The worktree directory must be outside the primary checkout")

    def current_commit(self) -> str:
        """Resolve the repository's current commit."""

        return _git(self.repo_path, "rev-parse", "HEAD^{commit}")

    def create(self, run_id: str, attempt_number: int, base_commit: str) -> Worktree:
        """Create a new detached checkout of the exact base commit."""

        parent = self.worktree_root / run_id
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / f"attempt-{attempt_number}"
        if path.exists():
            raise WorktreeError(f"Worktree path already exists: {path}")
        _git(
            self.repo_path,
            "worktree",
            "add",
            "--detach",
            str(path),
            base_commit,
        )
        actual_commit = _git(path, "rev-parse", "HEAD^{commit}")
        if actual_commit != base_commit:
            raise WorktreeError(
                f"Worktree commit {actual_commit} did not match base commit {base_commit}"
            )
        status = _git(path, "status", "--porcelain", "--untracked-files=all")
        clean = status == ""
        if not clean:
            raise WorktreeError(f"New worktree was not clean: {status}")
        return Worktree(path=path, base_commit=actual_commit, clean_start_verified=True)
