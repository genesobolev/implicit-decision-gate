"""Restricted coding-agent tools and isolated evidence review."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import ValidationError

from implicit_decision_gate.gate import (
    MAX_TOOL_STEPS_PER_ATTEMPT,
    MAX_TRANSPORT_RETRIES_PER_CALL,
    ROLLOUT_DESCRIPTIONS,
    AttemptRecord,
    EvidenceClassification,
    ReviewerResult,
    RolloutOption,
    RunRecord,
    validate_reviewer_result,
)

REFERENCE_ROOT = PurePosixPath("examples/share-link-expiration")


class AgentError(RuntimeError):
    """Raised for invalid or unsuccessful model behavior."""


class AgentLimitError(AgentError):
    """Raised when a hard model-execution limit is reached."""


class ModelTransportError(AgentError):
    """A retryable model transport failure."""


@dataclass(frozen=True)
class ModelToolCall:
    """A normalized model tool call."""

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelResponse:
    """Model output independent of a concrete backend."""

    output_text: str = ""
    tool_calls: list[ModelToolCall] = field(default_factory=list)
    output_items: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def function_call(
        cls,
        name: str,
        arguments: dict[str, Any],
        *,
        call_id: str = "call-1",
    ) -> ModelResponse:
        """Build one scripted function-call response."""

        encoded_arguments = json.dumps(arguments)
        item: dict[str, Any] = {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": encoded_arguments,
        }
        return cls(
            tool_calls=[
                ModelToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=encoded_arguments,
                )
            ],
            output_items=[item],
            raw={"output": [item]},
        )

    @classmethod
    def text(cls, value: str) -> ModelResponse:
        """Build one scripted text response."""

        return cls(output_text=value, raw={"output_text": value})


class ModelClient(Protocol):
    """Minimal client interface shared by live and scripted calls."""

    def complete(
        self,
        request: dict[str, Any],
        *,
        working_directory: Path | None = None,
    ) -> ModelResponse:
        """Execute one model request."""


class ScriptedModelClient:
    """Deterministic model client used by tests and local demonstrations."""

    def __init__(self, responses: Sequence[ModelResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def complete(
        self,
        request: dict[str, Any],
        *,
        working_directory: Path | None = None,
    ) -> ModelResponse:
        """Return the next scripted response or exception."""

        del working_directory
        self.requests.append(copy.deepcopy(request))
        if not self.responses:
            raise AgentError("The scripted model response queue is empty")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


PRESERVE_EXISTING_MIGRATION = """\
-- PRESERVE_EXISTING
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone;

ALTER TABLE public.share_links
    ALTER COLUMN expires_at
    SET DEFAULT (CURRENT_TIMESTAMP + interval '30 days');
"""

EXPIRE_EXISTING_MIGRATION = """\
-- EXPIRE_EXISTING
ALTER TABLE public.share_links
    ADD COLUMN expires_at timestamp with time zone;

UPDATE public.share_links
SET expires_at = CURRENT_TIMESTAMP + interval '30 days';

ALTER TABLE public.share_links
    ALTER COLUMN expires_at
    SET DEFAULT (CURRENT_TIMESTAMP + interval '30 days');
"""


class DemoScriptedModelClient:
    """Deterministic public demo backend that exercises the real gate workflow."""

    def complete(
        self,
        request: dict[str, Any],
        *,
        working_directory: Path | None = None,
    ) -> ModelResponse:
        """Return a stable migration or evidence result for the reference scenario."""

        del working_directory
        if request.get("tools"):
            owner_option = request.get("owner_option")
            migration = (
                PRESERVE_EXISTING_MIGRATION
                if owner_option == RolloutOption.PRESERVE_EXISTING.value
                else EXPIRE_EXISTING_MIGRATION
            )
            return ModelResponse.function_call("submit_migration", {"sql": migration})
        return ModelResponse.text(
            json.dumps(
                {
                    "classification": "NOT_EVIDENCED",
                    "evidence_quote": None,
                }
            )
        )


@dataclass(frozen=True)
class CodingProposal:
    """One accepted migration proposal."""

    migration: str
    worktree_path: Path


CODING_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "read_file",
        "description": (
            "Read one file below examples/share-link-expiration in the current worktree."
        ),
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "submit_migration",
        "description": "Submit the complete SQL migration for this attempt.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _coding_input(
    brief: str,
    attempt_number: int,
    owner_option: RolloutOption | None,
) -> list[dict[str, Any]]:
    system = (
        "You create exactly one PostgreSQL migration. You have only read_file and "
        "submit_migration. Read only the allowlisted example files. Submit SQL without "
        "transaction-control statements. The target expires_at column must be a nullable "
        "timestamp with time zone and new rows must default to approximately 30 days from "
        "creation."
    )
    user_parts = [f"Original brief:\n{brief}"]
    if attempt_number == 2:
        if owner_option not in (
            RolloutOption.PRESERVE_EXISTING,
            RolloutOption.EXPIRE_EXISTING,
        ):
            raise AgentError("Attempt two requires a modeled owner option")
        user_parts.append(
            f"Owner decision: {owner_option.value}\n"
            f"Required behavior: {ROLLOUT_DESCRIPTIONS[owner_option]}"
        )
    user_parts.append(
        "Read examples/share-link-expiration/schema.sql as needed, then submit one migration."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


class CodingAgent:
    """Run a coding model through the two allowlisted tools."""

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def propose(
        self,
        *,
        brief: str,
        attempt: AttemptRecord,
        worktree_path: Path,
        run_id: str,
        owner_option: RolloutOption | None,
        persist: Callable[[], None],
    ) -> CodingProposal:
        """Collect one proposal while enforcing tool and transport limits."""

        input_items = _coding_input(brief, attempt.number, owner_option)
        submitted: CodingProposal | None = None
        while submitted is None:
            request: dict[str, Any] = {
                "input": copy.deepcopy(input_items),
                "tools": CODING_TOOLS,
                "tool_choice": "required",
                "parallel_tool_calls": False,
                "attempt_number": attempt.number,
                "owner_option": owner_option.value if owner_option is not None else None,
            }
            response = self._complete_with_retry(
                request,
                attempt,
                persist,
                working_directory=worktree_path,
            )
            input_items.extend(copy.deepcopy(response.output_items))
            if not response.tool_calls:
                raise AgentError("The coding model stopped without submitting a migration")
            submit_count = sum(
                tool_call.name == "submit_migration" for tool_call in response.tool_calls
            )
            if submit_count > 1:
                raise AgentError("The coding model submitted more than one migration")
            for tool_call in response.tool_calls:
                if attempt.tool_step_count >= MAX_TOOL_STEPS_PER_ATTEMPT:
                    persist()
                    raise AgentLimitError(
                        f"Tool-step limit of {MAX_TOOL_STEPS_PER_ATTEMPT} exceeded"
                    )
                attempt.tool_step_count += 1
                output, proposal = self._execute_tool(
                    tool_call,
                    worktree_path=worktree_path,
                    run_id=run_id,
                    attempt_number=attempt.number,
                )
                attempt.tool_calls.append(
                    {
                        "call_id": tool_call.call_id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "output": output,
                    }
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": output,
                    }
                )
                persist()
                if proposal is not None:
                    if submitted is not None:
                        raise AgentError("The coding model submitted more than one migration")
                    submitted = proposal
        return submitted

    def _complete_with_retry(
        self,
        request: dict[str, Any],
        attempt: AttemptRecord,
        persist: Callable[[], None],
        *,
        working_directory: Path,
    ) -> ModelResponse:
        for transport_attempt in range(MAX_TRANSPORT_RETRIES_PER_CALL + 1):
            traced_request = copy.deepcopy(request)
            traced_request["transport_attempt"] = transport_attempt + 1
            attempt.model_requests.append(traced_request)
            persist()
            try:
                response = self.client.complete(
                    request,
                    working_directory=working_directory,
                )
            except ModelTransportError as error:
                if transport_attempt >= MAX_TRANSPORT_RETRIES_PER_CALL:
                    raise AgentLimitError("Model transport retry limit exceeded") from error
                attempt.transport_retry_count += 1
                persist()
                continue
            attempt.model_responses.append(copy.deepcopy(response.raw))
            persist()
            return response
        raise AgentLimitError("Model transport retry limit exceeded")

    def _execute_tool(
        self,
        tool_call: ModelToolCall,
        *,
        worktree_path: Path,
        run_id: str,
        attempt_number: int,
    ) -> tuple[str, CodingProposal | None]:
        try:
            arguments = json.loads(tool_call.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
        except (json.JSONDecodeError, ValueError) as error:
            return json.dumps({"error": str(error)}), None

        if tool_call.name == "read_file":
            path_value = arguments.get("path")
            if not isinstance(path_value, str):
                return json.dumps({"error": "path must be a string"}), None
            try:
                contents = _read_allowlisted_file(worktree_path, path_value)
            except (OSError, ValueError) as error:
                return json.dumps({"error": str(error)}), None
            return json.dumps({"contents": contents}), None

        if tool_call.name == "submit_migration":
            sql_value = arguments.get("sql")
            if not isinstance(sql_value, str) or not sql_value.strip():
                return json.dumps({"error": "sql must be a non-empty string"}), None
            migration_directory = (worktree_path / REFERENCE_ROOT / "migrations").resolve()
            allowed_root = (worktree_path / REFERENCE_ROOT).resolve()
            if not migration_directory.is_relative_to(allowed_root):
                raise AgentError("Migration output escaped the allowlisted directory")
            migration_directory.mkdir(parents=True, exist_ok=True)
            filename = f"idg-{run_id}-attempt-{attempt_number}.sql"
            destination = migration_directory / filename
            try:
                with destination.open("x", encoding="utf-8") as file_handle:
                    file_handle.write(sql_value)
                    if not sql_value.endswith("\n"):
                        file_handle.write("\n")
            except FileExistsError as error:
                raise AgentError("A migration was already written for this attempt") from error
            output = json.dumps({"proposal_path": str(destination.relative_to(worktree_path))})
            return output, CodingProposal(migration=sql_value, worktree_path=destination)

        return json.dumps({"error": f"unknown tool: {tool_call.name}"}), None


def _read_allowlisted_file(worktree_path: Path, requested_path: str) -> str:
    relative = PurePosixPath(requested_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("read_file path must be a relative allowlisted path")
    if not relative.is_relative_to(REFERENCE_ROOT):
        raise ValueError(f"read_file path must be below {REFERENCE_ROOT}")
    allowed_root = (worktree_path / REFERENCE_ROOT).resolve()
    candidate = (worktree_path / Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(allowed_root):
        raise ValueError("read_file path escaped the allowlisted directory")
    if not candidate.is_file():
        raise ValueError(f"read_file path is not a file: {requested_path}")
    return candidate.read_text(encoding="utf-8")


def _reviewer_input(brief: str, option: RolloutOption) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Classify whether the brief explicitly supports the observed existing-row "
                "behavior. Return only JSON with classification and evidence_quote. "
                "classification must be SUPPORTED, CONTRADICTED, NOT_EVIDENCED, or "
                "UNCERTAIN. SUPPORTED and CONTRADICTED require an exact brief quote; the "
                "other classifications require null."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original brief:\n{brief}\n\n"
                f"Observed rollout option: {option.value}\n"
                f"Observed behavior: {ROLLOUT_DESCRIPTIONS[option]}"
            ),
        },
    ]


class EvidenceReviewer:
    """Run a fresh evidence-only model context and validate its quote."""

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def review(
        self,
        *,
        brief: str,
        option: RolloutOption,
        run: RunRecord,
        persist: Callable[[], None],
    ) -> ReviewerResult:
        """Review one modeled rollout without exposing migration material."""

        request: dict[str, Any] = {
            "input": _reviewer_input(brief, option),
        }
        run.reviewer_request = copy.deepcopy(request)
        persist()
        response: ModelResponse | None = None
        for transport_attempt in range(MAX_TRANSPORT_RETRIES_PER_CALL + 1):
            try:
                response = self.client.complete(request)
            except ModelTransportError as error:
                if transport_attempt >= MAX_TRANSPORT_RETRIES_PER_CALL:
                    raise AgentLimitError("Reviewer transport retry limit exceeded") from error
                run.reviewer_transport_retry_count += 1
                persist()
                continue
            break
        if response is None:
            raise AgentLimitError("Reviewer transport retry limit exceeded")
        run.reviewer_response = copy.deepcopy(response.raw)
        persist()
        parsed = _parse_reviewer_result(response.output_text)
        return validate_reviewer_result(brief, parsed)


def _parse_reviewer_result(value: str) -> ReviewerResult:
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end < start:
        return ReviewerResult(
            classification=EvidenceClassification.UNCERTAIN,
            evidence_quote=None,
        )
    try:
        payload = json.loads(value[start : end + 1])
        return ReviewerResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return ReviewerResult(
            classification=EvidenceClassification.UNCERTAIN,
            evidence_quote=None,
        )
