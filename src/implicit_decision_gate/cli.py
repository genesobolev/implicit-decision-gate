"""Command-line interface for implicit-decision-gate."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from implicit_decision_gate.agent import ScriptedModelClient
from implicit_decision_gate.codex_client import CodexCLIModelClient
from implicit_decision_gate.gate import (
    AgentBackend,
    GateError,
    RolloutOption,
    RunState,
    RunStore,
    render_show,
)
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.probe import PostgresProbe
from implicit_decision_gate.worktree import WorktreeError

DEFAULT_ADMIN_DSN = "postgresql://idg_admin:idg_admin@localhost:55432/postgres"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idg")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a new gate run")
    start.add_argument(
        "--agent",
        choices=[backend.value for backend in AgentBackend],
        default=AgentBackend.SCRIPTED.value,
        help="Model backend (default: scripted)",
    )

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


def _execution_orchestrator(repo_path: Path, agent_backend: AgentBackend) -> Orchestrator:
    worktree_value = os.environ.get("IDG_WORKTREE_DIR")
    worktree_root = Path(worktree_value).resolve() if worktree_value else None
    admin_dsn = os.environ.get("IDG_POSTGRES_ADMIN_DSN", DEFAULT_ADMIN_DSN)
    client: ScriptedModelClient | CodexCLIModelClient
    if agent_backend is AgentBackend.SCRIPTED:
        client = ScriptedModelClient()
    else:
        client = CodexCLIModelClient()
    return Orchestrator(
        repo_path=repo_path,
        agent_backend=agent_backend,
        coding_client=client,
        reviewer_client=client,
        probe=PostgresProbe(admin_dsn),
        worktree_root=worktree_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one CLI command and return its process status."""

    arguments = _parser().parse_args(argv)
    try:
        repo_path = Path.cwd()
        if arguments.command == "start":
            agent_backend = AgentBackend(arguments.agent)
            orchestrator = _execution_orchestrator(repo_path, agent_backend)
            run = orchestrator.start()
            print(render_show(run))
            return 1 if run.state is RunState.FAILED else 0

        if arguments.command == "show":
            print(Orchestrator(repo_path=repo_path).show(arguments.run_id))
            return 0
        if arguments.command == "answer":
            option = RolloutOption(arguments.option)
            run = Orchestrator(repo_path=repo_path).answer(arguments.run_id, option)
            print(render_show(run))
            return 0
        if arguments.command == "resume":
            stored_run = RunStore(repo_path).load(arguments.run_id)
            run = _execution_orchestrator(repo_path, stored_run.agent_backend).resume(
                arguments.run_id
            )
            print(render_show(run))
            return 1 if run.state is RunState.FAILED else 0
        raise GateError(f"Unknown command: {arguments.command}")
    except (GateError, WorktreeError) as error:
        print(f"idg: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
