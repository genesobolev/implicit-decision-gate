"""Execution and display helpers for the guided notebook."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import psycopg
from IPython.display import Markdown, display

from implicit_decision_gate.api_probe import (
    ADMINISTRATOR_ACCESS,
    CREATE_ANOTHER_EXPORT,
    OWNER_AND_ADMIN,
    OWNER_ONLY,
    REPEAT_REQUEST,
    REUSE_ACTIVE_EXPORT,
    DockerAuthorizationProbe,
)
from implicit_decision_gate.gate import ModelInvocationRecord, ModelRole, RunRecord, RunState
from implicit_decision_gate.orchestrator import Orchestrator
from implicit_decision_gate.postgres_surface import (
    DATA_INTEGRITY,
    INDEXING,
    SCHEMA_SHAPE,
    capture_catalog,
    diff_catalogs,
)
from implicit_decision_gate.probe import (
    COMPOSE_ADMIN_DSN,
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
    PostgresProbe,
)
from implicit_decision_gate.scenario import (
    EffectChange,
    ObservationResult,
    ObservedEffect,
)
from implicit_decision_gate.scenarios import (
    WORKSPACE_EXPORT_AUTHORIZATION,
    scenario_registry,
)
from implicit_decision_gate.web_export import DemoDataset

WORKSPACE_EXPORT_BRIEF_PATH = "examples/workspace-export-authorization/brief.md"
SHARE_LINK_SCHEMA_PATH = "examples/share-link-expiration/schema.sql"
DECISION_ORDER = (ADMINISTRATOR_ACCESS, REPEAT_REQUEST)
DECISION_NAMES = {
    ADMINISTRATOR_ACCESS: "Administrator access",
    REPEAT_REQUEST: "Repeated owner request",
}
ADMINISTRATOR_LABELS = {
    OWNER_ONLY: "Owners only",
    OWNER_AND_ADMIN: "Owners and administrators",
}
REPEAT_LABELS = {
    CREATE_ANOTHER_EXPORT: "Create another export",
    REUSE_ACTIVE_EXPORT: "Reuse active export",
}

PRESERVE_MIGRATION = """
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone;
ALTER TABLE public.share_links
    ALTER COLUMN expires_at
    SET DEFAULT (CURRENT_TIMESTAMP + INTERVAL '30 days');
"""
EXPIRE_MIGRATION = """
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone
    DEFAULT (CURRENT_TIMESTAMP + INTERVAL '30 days');
"""
STRUCTURAL_BASELINE = """
CREATE TABLE public.records (
    old_column text,
    value integer,
    email text,
    score integer,
    legacy_score integer,
    CONSTRAINT score_check CHECK (score > 0),
    CONSTRAINT legacy_check CHECK (legacy_score > 0)
);
CREATE INDEX old_idx ON public.records (old_column);
CREATE INDEX changed_idx ON public.records (email);
"""
STRUCTURAL_MIGRATION = """
ALTER TABLE public.records ADD COLUMN new_column timestamp with time zone;
ALTER TABLE public.records DROP COLUMN old_column;
ALTER TABLE public.records ALTER COLUMN value TYPE bigint;
ALTER TABLE public.records ADD CONSTRAINT email_key UNIQUE (email);
ALTER TABLE public.records DROP CONSTRAINT legacy_check;
ALTER TABLE public.records DROP CONSTRAINT score_check;
ALTER TABLE public.records ADD CONSTRAINT score_check CHECK (score >= 0);
CREATE INDEX new_idx ON public.records (value);
DROP INDEX public.changed_idx;
CREATE UNIQUE INDEX changed_idx ON public.records (email);
"""

type JsonObject = dict[str, Any]
type TableRows = list[tuple[str, ...]]

_markdown = cast(Callable[[str], object], Markdown)
_display = cast(Callable[[object], None], display)


class _FixedArtifactClient:
    def __init__(self, artifact: str) -> None:
        self.artifact = artifact

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        return ModelInvocationRecord(
            role=role,
            attempt_number=attempt_number,
            model="fixed-notebook-artifact",
            reasoning_effort="deterministic",
            codex_cli_version="not-applicable",
        )

    def propose_artifact(self, prompt: str) -> str:
        del prompt
        return self.artifact


def create_context(start: Path) -> Path:
    """Find the repository containing the notebook."""

    for candidate in (start, *start.parents):
        if (candidate / WORKSPACE_EXPORT_BRIEF_PATH).is_file():
            return candidate.resolve()
    raise RuntimeError("Open this notebook from inside the repository")


def run_idg(repo_root: Path, *arguments: str) -> JsonObject:
    """Run one CLI command and return its JSON payload."""

    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    completed = subprocess.run(
        ["uv", "run", "idg", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if not completed.stdout:
        raise RuntimeError(completed.stderr.strip() or "idg returned no JSON")
    payload = json.loads(completed.stdout)
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip() or str(payload))
    return cast(JsonObject, payload)


def read_at_head(repo_root: Path, path: str) -> str:
    """Read one file from the exact commit used by the gate."""

    return subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def load_run(repo_root: Path, run_id: str) -> RunRecord:
    """Load one persisted run snapshot."""

    path = repo_root / ".idg" / "runs" / run_id / "run.json"
    return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))


def show_markdown(value: str) -> None:
    """Display Markdown in a notebook cell."""

    _display(_markdown(value))


def show_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """Display a Markdown table."""

    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    show_markdown("\n".join([header, divider, *body]))


def start_live_workspace_export(repo_root: Path) -> JsonObject:
    """Start the live scenario and display its first gate state."""

    brief = read_at_head(repo_root, WORKSPACE_EXPORT_BRIEF_PATH).strip()
    show_markdown(f"```text\n{brief}\n```")
    run = run_idg(repo_root, "start", "--scenario", WORKSPACE_EXPORT_AUTHORIZATION)
    state = run["state"]
    product_flow = state == RunState.AWAITING_OWNER
    requests = {
        str(request["id"]): request for request in cast(list[JsonObject], run["decision_requests"])
    }
    show_markdown(f"Run state: `{state}`")
    if state == RunState.COVERAGE_GAP:
        gaps = cast(list[JsonObject], run["coverage_gaps"])
        if not gaps:
            raise RuntimeError("COVERAGE_GAP returned without a persisted event")
        show_table(
            ("Coverage gap", "Rule", "Normalized facts"),
            [
                (
                    str(gap["description"]),
                    f"`{gap['rule_id']}`",
                    _format_facts(cast(JsonObject, gap["facts"])),
                )
                for gap in gaps
            ],
        )
        show_markdown(
            "The event is persisted for later platform engineering review. "
            "No product decision or retry was started."
        )
    elif not product_flow:
        raise RuntimeError(f"Expected AWAITING_OWNER or COVERAGE_GAP, found {state}")
    run["_product_flow"] = product_flow
    run["_requests"] = requests
    return run


def show_live_decision_requests(run: JsonObject) -> None:
    """Display every product question produced by the live attempt."""

    if not run["_product_flow"]:
        show_markdown("No product questions were created for this coverage event.")
        return
    requests = cast(dict[str, JsonObject], run["_requests"])
    if set(requests) != set(DECISION_ORDER):
        raise RuntimeError("The live run didn't produce both expected decision requests")
    classifications = cast(JsonObject, run["classifications"])
    rows: TableRows = []
    for decision_id in DECISION_ORDER:
        request = requests[decision_id]
        observed = cast(JsonObject, request["observed"])
        options = cast(list[JsonObject], request["options"])
        rows.append(
            (
                str(request["question"]),
                f"{observed['behavior']}<br>`{observed['option']}`",
                f"`{classifications[decision_id]}`",
                "<br>".join(f"{option['behavior']} (`{option['option']}`)" for option in options),
            )
        )
    show_table(
        ("Missing question", "Observed behavior", "Evidence review", "Available choices"),
        rows,
    )


def answer_live_decisions(
    repo_root: Path,
    run: JsonObject,
    selections: Mapping[str, str],
) -> None:
    """Record all human selections for the live run."""

    if not run["_product_flow"]:
        show_markdown("No product answers were requested or recorded.")
        return
    if set(selections) != set(DECISION_ORDER):
        raise ValueError("Provide exactly one answer for each displayed decision")
    requests = cast(dict[str, JsonObject], run["_requests"])
    rows: TableRows = []
    state = ""
    for decision_id in DECISION_ORDER:
        option_id = selections[decision_id]
        option = _option(requests[decision_id], option_id)
        summary = run_idg(
            repo_root,
            "answer",
            str(run["run_id"]),
            "--decision",
            decision_id,
            "--option",
            option_id,
        )
        state = str(summary["state"])
        rows.append(
            (
                DECISION_NAMES[decision_id],
                f"{option['behavior']}<br>`{option_id}`",
                f"`{state}`",
            )
        )
    show_table(("Answer recorded", "Selected behavior", "Run state"), rows)
    if state != RunState.READY_TO_RESUME:
        raise RuntimeError(f"Expected READY_TO_RESUME, found {state}")


def resume_live_workspace_export(repo_root: Path, run: JsonObject) -> None:
    """Run the clean retry and display direct verification."""

    if not run["_product_flow"]:
        show_markdown("No retry was started because this run requires platform coverage review.")
        return
    summary = run_idg(repo_root, "resume", str(run["run_id"]))
    if summary["state"] != RunState.COMPLETED:
        raise RuntimeError(str(summary["error"] or "Verification failed"))
    snapshot = load_run(repo_root, str(run["run_id"]))
    attempts = snapshot.attempts
    if len(attempts) != 2 or any(attempt.observation is None for attempt in attempts):
        raise RuntimeError("Completed run doesn't contain two observations")
    first = _decision_map(cast(ObservationResult, attempts[0].observation))
    second = _decision_map(cast(ObservationResult, attempts[1].observation))
    selected = {
        item.decision_id: item.selected for item in snapshot.decisions if item.selected is not None
    }
    requests = cast(dict[str, JsonObject], run["_requests"])
    rows: TableRows = []
    for decision_id in DECISION_ORDER:
        rows.append(
            (
                DECISION_NAMES[decision_id],
                _option_label(requests[decision_id], str(first[decision_id])),
                _option_label(requests[decision_id], selected[decision_id]),
                _option_label(requests[decision_id], str(second[decision_id])),
                "Verified" if selected[decision_id] == second[decision_id] else "Mismatch",
            )
        )
    show_table(
        ("Decision", "First attempt", "Owner selected", "Second attempt", "Result"),
        rows,
    )
    clean_retry = attempts[1].clean_start_verified and (
        attempts[0].worktree_path != attempts[1].worktree_path
    )
    show_table(
        ("Measure", "Result"),
        [
            ("Missing decisions detected", str(len(requests))),
            ("Human answers recorded", str(len(selected))),
            ("Clean retries performed", "1" if clean_retry else "0"),
            (
                "Verified decisions",
                f"{sum(selected[key] == second[key] for key in DECISION_ORDER)} of 2",
            ),
            ("Final state", f"`{summary['state']}`"),
        ],
    )


def workspace_export_examples() -> TableRows:
    """Observe every supported API policy combination with the real probe."""

    probe = DockerAuthorizationProbe()
    combinations = (
        (OWNER_ONLY, CREATE_ANOTHER_EXPORT),
        (OWNER_ONLY, REUSE_ACTIVE_EXPORT),
        (OWNER_AND_ADMIN, CREATE_ANOTHER_EXPORT),
        (OWNER_AND_ADMIN, REUSE_ACTIVE_EXPORT),
    )
    rows: TableRows = []
    for administrator, repeat in combinations:
        observation = probe.observe(_workspace_export_artifact(administrator, repeat), "")
        expected = {ADMINISTRATOR_ACCESS: administrator, REPEAT_REQUEST: repeat}
        observed = _decision_map(observation)
        if observed != expected:
            raise RuntimeError(f"API observer returned {observed}, expected {expected}")
        rows.append(
            (
                ADMINISTRATOR_LABELS[administrator],
                REPEAT_LABELS[repeat],
                _api_facts(observation.facts),
                f"`{administrator}`<br>`{repeat}`",
            )
        )
    return rows


def workspace_export_coverage_gap(repo_root: Path) -> TableRows:
    """Run one fixed artifact through the real gate's coverage-gap route."""

    artifact = """
def create_export(role: str, export_jobs: list[str]) -> int:
    if role != "owner":
        return 403
    if export_jobs:
        return 200
    export_jobs.append("queued")
    return 202
"""
    controller = Orchestrator(
        repo_path=repo_root,
        scenarios=scenario_registry(
            PostgresProbe(COMPOSE_ADMIN_DSN),
            DockerAuthorizationProbe(),
        ),
        coding_client=_FixedArtifactClient(artifact),
    )
    run = controller.start(WORKSPACE_EXPORT_AUTHORIZATION)
    if run.state is not RunState.COVERAGE_GAP:
        raise RuntimeError(f"Expected COVERAGE_GAP, found {run.state}: {run.error}")
    if [gap.decision_id for gap in run.coverage_gaps] != [REPEAT_REQUEST]:
        raise RuntimeError("Coverage-gap route persisted the wrong decision")
    observation = run.attempts[0].observation
    if observation is None:
        raise RuntimeError("Coverage-gap attempt has no observation")
    reviews = sum(
        invocation.role is ModelRole.EVIDENCE_REVIEWER for invocation in run.model_invocations
    )
    observed = _decision_map(observation)
    unknown = next(
        (effect for effect in observation.unknown_effects if effect.decision_id == REPEAT_REQUEST),
        None,
    )
    if unknown is None:
        raise RuntimeError("Coverage-gap route didn't persist its unknown effect")
    return [
        (
            "Administrator access",
            f"Covered as owners only (`{observed[ADMINISTRATOR_ACCESS]}`)",
        ),
        (
            "Repeated owner request",
            f"Unknown effect: {unknown.description} (`{unknown.rule_id}`)",
        ),
        ("Gate state", f"`{run.state}`"),
        ("Persisted platform events", str(len(run.coverage_gaps))),
        (
            "Downstream product work",
            f"{reviews} reviews, {len(run.decisions)} decisions, {len(run.attempts) - 1} retries",
        ),
    ]


def postgres_behavior_examples(repo_root: Path) -> TableRows:
    """Observe both supported data-rollout policies with the real probe."""

    schema = read_at_head(repo_root, SHARE_LINK_SCHEMA_PATH)
    examples = (
        ("Preserve existing links", "Remain non-expiring", PRESERVE_MIGRATION, PRESERVE_EXISTING),
        (
            "Expire existing links",
            "Receive an expiration about 30 days after migration",
            EXPIRE_MIGRATION,
            EXPIRE_EXISTING,
        ),
    )
    rows: TableRows = []
    signatures: list[list[str]] = []
    for policy, existing, migration, expected in examples:
        observation = PostgresProbe(COMPOSE_ADMIN_DSN).observe(migration, schema)
        if _decision_map(observation) != {EXISTING_LINK_ROLLOUT: expected}:
            raise RuntimeError(f"PostgreSQL observer didn't report {expected}")
        if not observation.facts["rollback_verified"]:
            raise RuntimeError("PostgreSQL observer didn't verify rollback")
        signatures.append([effect.model_dump_json() for effect in observation.effects])
        rows.append(
            (
                policy,
                existing,
                "Expire about 30 days after creation",
                "Same type, nullability, and default",
                f"`{expected}`",
            )
        )
    if signatures[0] != signatures[1]:
        raise RuntimeError("Reference migrations didn't produce the same final column surface")
    return rows


def postgres_structure_examples() -> TableRows:
    """Capture a three-rule by three-change matrix from one real migration."""

    with psycopg.connect(COMPOSE_ADMIN_DSN, autocommit=True) as connection:
        connection.execute("BEGIN")
        try:
            connection.execute(STRUCTURAL_BASELINE)
            before = capture_catalog(connection)
            connection.execute(STRUCTURAL_MIGRATION)
            after = capture_catalog(connection)
        finally:
            connection.execute("ROLLBACK")
    effects = diff_catalogs(before, after)
    requested: dict[tuple[str, EffectChange], tuple[str, str]] = {
        (SCHEMA_SHAPE, "ADDED"): ("public.records.new_column", "data_type"),
        (SCHEMA_SHAPE, "REMOVED"): ("public.records.old_column", "data_type"),
        (SCHEMA_SHAPE, "CHANGED"): ("public.records.value", "data_type"),
        (DATA_INTEGRITY, "ADDED"): ("public.records.email_key", "constraint_type"),
        (DATA_INTEGRITY, "REMOVED"): ("public.records.legacy_check", "constraint_type"),
        (DATA_INTEGRITY, "CHANGED"): ("public.records.score_check", "definition"),
        (INDEXING, "ADDED"): ("public.records.new_idx", "unique"),
        (INDEXING, "REMOVED"): ("public.records.old_idx", "unique"),
        (INDEXING, "CHANGED"): ("public.records.changed_idx", "unique"),
    }
    indexed = {
        (effect.rule_id, effect.change, effect.identity, effect.attribute): effect
        for effect in effects
    }
    selected = {
        key: indexed[(key[0], key[1], identity, attribute)]
        for key, (identity, attribute) in requested.items()
    }
    return [
        (
            f"Schema shape<br>`{SCHEMA_SHAPE}`",
            _effect_label(selected[(SCHEMA_SHAPE, "ADDED")]),
            _effect_label(selected[(SCHEMA_SHAPE, "REMOVED")]),
            _effect_label(selected[(SCHEMA_SHAPE, "CHANGED")]),
        ),
        (
            f"Data integrity<br>`{DATA_INTEGRITY}`",
            _effect_label(selected[(DATA_INTEGRITY, "ADDED")]),
            _effect_label(selected[(DATA_INTEGRITY, "REMOVED")]),
            _effect_label(selected[(DATA_INTEGRITY, "CHANGED")]),
        ),
        (
            f"Indexing<br>`{INDEXING}`",
            _effect_label(selected[(INDEXING, "ADDED")]),
            _effect_label(selected[(INDEXING, "REMOVED")]),
            _effect_label(selected[(INDEXING, "CHANGED")]),
        ),
    ]


def adversarial_route_examples(repo_root: Path) -> TableRows:
    """Load the web replay fixture through the shared typed presentation contract."""

    path = repo_root / "web" / "public" / "demo-runs.json"
    dataset = DemoDataset.model_validate_json(path.read_text(encoding="utf-8"))
    rows: TableRows = []
    for run in dataset.runs:
        if run.id in {"api-owner-decision", "api-supported", "db-owner-decision"}:
            continue
        terminal = (
            run.failure.category
            if run.failure is not None
            else run.coverage_gaps[0].category
            if run.coverage_gaps
            else run.state
        )
        rows.append((run.label, str(terminal), f"`{run.state}`", run.summary))
    return rows


def _format_facts(facts: Mapping[str, Any]) -> str:
    return "<br>".join(f"`{key}={json.dumps(value)}`" for key, value in facts.items())


def observation_assessment(observation: ObservationResult) -> TableRows:
    """Summarize the four gate surfaces from one typed observation."""

    decisions = (
        ", ".join(f"`{item.decision_id}={item.option_id}`" for item in observation.decisions)
        or "None"
    )
    unknowns = ", ".join(f"`{item.rule_id}`" for item in observation.unknown_effects) or "None"
    return [
        (
            "Authoritative invariants",
            "<br>".join(f"`{item.invariant_id}`: {item.status}" for item in observation.invariants),
        ),
        ("Owner-selectable decisions", decisions),
        ("Unknown effects", unknowns),
        (
            "Coverage attestations",
            "<br>".join(f"`{item.rule_id}`: {item.status}" for item in observation.coverage),
        ),
    ]


def _decision_map(observation: ObservationResult) -> dict[str, str]:
    return {item.decision_id: item.option_id for item in observation.decisions}


def _option(request: JsonObject, option_id: str) -> JsonObject:
    options = cast(list[JsonObject], request["options"])
    for option in options:
        if option["option"] == option_id:
            return option
    raise ValueError(f"{option_id} isn't valid for {request['id']}")


def _option_label(request: JsonObject, option_id: str) -> str:
    option = _option(request, option_id)
    return f"{option['behavior']}<br>`{option_id}`"


def _workspace_export_artifact(administrator: str, repeat: str) -> str:
    administrator_allowed = administrator == OWNER_AND_ADMIN
    reuse_active = repeat == REUSE_ACTIVE_EXPORT
    return f"""def create_export(role: str, export_jobs: list[str]) -> int:
    if role == "member":
        return 403
    if role == "administrator":
        if not {administrator_allowed!r}:
            return 403
        export_jobs.append("queued")
        return 202
    if role != "owner":
        return 403
    if export_jobs and {reuse_active!r}:
        return 202
    export_jobs.append("queued")
    return 202
"""


def _api_facts(facts: Mapping[str, Any]) -> str:
    return "<br>".join(
        (
            f"First owner: {_http_effect(facts['owner_status'], facts['owner_jobs_created'])}",
            "Repeat owner: "
            f"{_http_effect(facts['repeat_owner_status'], facts['repeat_owner_jobs_created'])}",
            "Administrator: "
            f"{_http_effect(facts['administrator_status'], facts['administrator_jobs_created'])}",
            f"Member: {_http_effect(facts['member_status'], facts['member_jobs_created'])}",
        )
    )


def _http_effect(status: Any, jobs_created: Any) -> str:
    result = "Accepted" if status == 202 else "Denied" if status == 403 else "Other"
    jobs = "no job" if jobs_created == 0 else f"{jobs_created} job"
    return f"{result} (`{status}`), {jobs}"


def _effect_label(effect: ObservedEffect) -> str:
    label = f"{effect.object_kind.title()} `{effect.identity}`"
    if effect.change == "CHANGED":
        label += f"<br>`{effect.attribute}`: `{effect.before}` → `{effect.after}`"
    return label
