"""Command-line interface for implicit-decision-gate."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from implicit_decision_gate.api_probe import DockerAuthorizationProbe
from implicit_decision_gate.codex_client import CodexCLIModelClient
from implicit_decision_gate.gate import GateError, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import COMPOSE_ADMIN_DSN, PostgresProbe
from implicit_decision_gate.scenarios import (
    SHARE_LINK_EXPIRATION,
    WORKSPACE_EXPORT_AUTHORIZATION,
    scenario_registry,
)
from implicit_decision_gate.worktree import WorktreeError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idg")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a new gate run")
    start.add_argument(
        "--scenario",
        choices=[SHARE_LINK_EXPIRATION, WORKSPACE_EXPORT_AUTHORIZATION],
        default=SHARE_LINK_EXPIRATION,
    )

    show = subparsers.add_parser("show", help="Show a persisted run")
    show.add_argument("run_id")

    answer = subparsers.add_parser("answer", help="Record the owner decision")
    answer.add_argument("run_id")
    answer.add_argument("--decision", required=True)
    answer.add_argument("--option", required=True)

    resume = subparsers.add_parser("resume", help="Execute the second attempt")
    resume.add_argument("run_id")
    return parser


def _execution_orchestrator(repo_path: Path) -> Orchestrator:
    worktree_value = os.environ.get("IDG_WORKTREE_DIR")
    worktree_root = Path(worktree_value).resolve() if worktree_value else None
    client = CodexCLIModelClient()
    return Orchestrator(
        repo_path=repo_path,
        scenarios=scenario_registry(
            PostgresProbe(COMPOSE_ADMIN_DSN),
            DockerAuthorizationProbe(),
        ),
        coding_client=client,
        reviewer_client=client,
        worktree_root=worktree_root,
    )


def _state_orchestrator(repo_path: Path) -> Orchestrator:
    return Orchestrator(
        repo_path=repo_path,
        scenarios=scenario_registry(
            PostgresProbe(COMPOSE_ADMIN_DSN),
            DockerAuthorizationProbe(),
        ),
    )


def _render(orchestrator: Orchestrator, run_id: str) -> str:
    return orchestrator.show(run_id)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI command and return its process status."""

    arguments = _parser().parse_args(argv)
    try:
        repo_path = Path.cwd()
        if arguments.command == "start":
            orchestrator = _execution_orchestrator(repo_path)
            run = orchestrator.start(arguments.scenario)
            print(_render(orchestrator, run.run_id))
            return 1 if run.state is RunState.FAILED else 0

        if arguments.command == "show":
            print(_state_orchestrator(repo_path).show(arguments.run_id))
            return 0
        if arguments.command == "answer":
            orchestrator = _state_orchestrator(repo_path)
            run = orchestrator.answer(
                arguments.run_id,
                arguments.decision,
                arguments.option,
            )
            print(_render(orchestrator, run.run_id))
            return 0
        if arguments.command == "resume":
            orchestrator = _execution_orchestrator(repo_path)
            run = orchestrator.resume(arguments.run_id)
            print(_render(orchestrator, run.run_id))
            return 1 if run.state is RunState.FAILED else 0
        raise GateError(f"Unknown command: {arguments.command}")
    except (GateError, WorktreeError) as error:
        print(f"idg: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
