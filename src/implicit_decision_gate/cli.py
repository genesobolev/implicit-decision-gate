"""Command-line interface for implicit-decision-gate."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from implicit_decision_gate.agent import OpenAIModelClient
from implicit_decision_gate.gate import GateError, RolloutOption, RunState, render_show
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import PostgresProbe
from implicit_decision_gate.worktree import WorktreeError

DEFAULT_ADMIN_DSN = "postgresql://idg_admin:idg_admin@localhost:55432/postgres"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idg")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a new gate run")
    start.add_argument("--repo", type=Path, required=True)
    start.add_argument("--brief", type=Path, required=True)

    show = subparsers.add_parser("show", help="Show a persisted run")
    show.add_argument("run_id")

    answer = subparsers.add_parser("answer", help="Record the owner decision")
    answer.add_argument("run_id")
    answer.add_argument(
        "--option",
        choices=[
            RolloutOption.PRESERVE_EXISTING.value,
            RolloutOption.EXPIRE_EXISTING.value,
        ],
        required=True,
    )

    resume = subparsers.add_parser("resume", help="Execute the second attempt")
    resume.add_argument("run_id")
    return parser


def _execution_orchestrator(repo_path: Path) -> Orchestrator:
    model_name = os.environ.get("IDG_MODEL")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not model_name:
        raise GateError("IDG_MODEL is required")
    if not api_key:
        raise GateError("OPENAI_API_KEY is required")
    worktree_value = os.environ.get("IDG_WORKTREE_DIR")
    worktree_root = Path(worktree_value).resolve() if worktree_value else None
    admin_dsn = os.environ.get("IDG_POSTGRES_ADMIN_DSN", DEFAULT_ADMIN_DSN)
    return Orchestrator(
        repo_path=repo_path,
        model_name=model_name,
        coding_client=OpenAIModelClient(api_key),
        reviewer_client=OpenAIModelClient(api_key),
        probe=PostgresProbe(admin_dsn),
        worktree_root=worktree_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI command and return its process status."""

    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "start":
            orchestrator = _execution_orchestrator(arguments.repo)
            run = orchestrator.start(arguments.brief)
            print(render_show(run))
            return 1 if run.state is RunState.FAILED else 0

        repo_path = Path.cwd()
        if arguments.command == "show":
            print(Orchestrator(repo_path=repo_path).show(arguments.run_id))
            return 0
        if arguments.command == "answer":
            option = RolloutOption(arguments.option)
            run = Orchestrator(repo_path=repo_path).answer(arguments.run_id, option)
            print(render_show(run))
            return 0
        if arguments.command == "resume":
            run = _execution_orchestrator(repo_path).resume(arguments.run_id)
            print(render_show(run))
            return 1 if run.state is RunState.FAILED else 0
        raise GateError(f"Unknown command: {arguments.command}")
    except (GateError, WorktreeError) as error:
        print(f"idg: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
