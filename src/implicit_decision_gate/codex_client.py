"""Local Codex CLI adapter for non-interactive model calls."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from implicit_decision_gate.agent import AgentError, ModelResponse, ModelTransportError

DEFAULT_CODEX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class CodexCLIModelClient:
    """Execute normalized model requests through a user's local Codex CLI."""

    executable: str = "codex"
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS

    def complete(
        self,
        request: dict[str, Any],
        *,
        working_directory: Path | None = None,
    ) -> ModelResponse:
        """Run one ephemeral Codex process and normalize its structured output."""

        executable_path = shutil.which(self.executable)
        if executable_path is None:
            raise AgentError(
                "Codex CLI was not found; install and sign in to Codex, "
                "or start a run with --agent scripted"
            )

        schema = _output_schema(request)
        prompt = _render_prompt(request)
        with tempfile.TemporaryDirectory(prefix="idg-codex-") as temporary_value:
            temporary_path = Path(temporary_value)
            schema_path = temporary_path / "output-schema.json"
            schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            command = [
                executable_path,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
            ]
            if working_directory is None:
                command.append("--skip-git-repo-check")
                process_directory = temporary_path
            else:
                command.extend(["-C", str(working_directory)])
                process_directory = working_directory
            command.append("-")
            try:
                completed = subprocess.run(
                    command,
                    cwd=process_directory,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ModelTransportError(
                    f"Codex CLI timed out after {self.timeout_seconds} seconds"
                ) from error
            except OSError as error:
                raise AgentError(f"Could not start Codex CLI: {error}") from error

        if completed.returncode != 0:
            raise AgentError(_codex_failure_message(completed))
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise AgentError("Codex CLI returned invalid structured output") from error
        if not isinstance(payload, dict):
            raise AgentError("Codex CLI structured output must be a JSON object")
        return _normalize_output(request, payload)


def _render_prompt(request: dict[str, Any]) -> str:
    payload = {
        "conversation": request.get("input", []),
        "available_tools": request.get("tools", []),
    }
    if request.get("tools"):
        instruction = (
            "Continue the supplied coding conversation. Do not edit files yourself. "
            "Return exactly one available application tool call. Set tool_name to the "
            "tool name. For read_file set path and leave sql empty. For submit_migration "
            "set sql to the complete migration and leave path empty."
        )
    else:
        instruction = (
            "Perform the supplied evidence review. Return the requested classification. "
            "Use an exact source quote when required; otherwise set evidence_quote to an "
            "empty string."
        )
    return f"{instruction}\n\nRequest:\n{json.dumps(payload, indent=2)}\n"


def _output_schema(request: dict[str, Any]) -> dict[str, Any]:
    tools = request.get("tools")
    if tools:
        tool_names = [
            tool["name"]
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        if not tool_names:
            raise AgentError("The model request did not contain any valid tools")
        return {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "enum": tool_names},
                "path": {"type": "string"},
                "sql": {"type": "string"},
            },
            "required": ["tool_name", "path", "sql"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["SUPPORTED", "CONTRADICTED", "NOT_EVIDENCED", "UNCERTAIN"],
            },
            "evidence_quote": {"type": "string"},
        },
        "required": ["classification", "evidence_quote"],
        "additionalProperties": False,
    }


def _normalize_output(request: dict[str, Any], payload: dict[str, Any]) -> ModelResponse:
    if request.get("tools"):
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str):
            raise AgentError("Codex CLI omitted tool_name")
        if tool_name == "read_file":
            path = payload.get("path")
            if not isinstance(path, str) or not path:
                raise AgentError("Codex CLI returned an invalid read_file path")
            arguments = {"path": path}
        elif tool_name == "submit_migration":
            sql = payload.get("sql")
            if not isinstance(sql, str) or not sql.strip():
                raise AgentError("Codex CLI returned an empty migration")
            arguments = {"sql": sql}
        else:
            raise AgentError(f"Codex CLI returned an unknown tool: {tool_name}")
        return ModelResponse.function_call(
            tool_name,
            arguments,
            call_id=f"codex-{uuid.uuid4().hex}",
        )

    classification = payload.get("classification")
    evidence_quote = payload.get("evidence_quote")
    if not isinstance(classification, str) or not isinstance(evidence_quote, str):
        raise AgentError("Codex CLI returned an invalid evidence result")
    return ModelResponse.text(
        json.dumps(
            {
                "classification": classification,
                "evidence_quote": evidence_quote or None,
            }
        )
    )


def _codex_failure_message(completed: subprocess.CompletedProcess[str]) -> str:
    details = (completed.stderr or completed.stdout).strip()
    normalized = details.lower()
    if any(marker in normalized for marker in ("auth", "login", "logged in", "sign in")):
        return (
            "Codex CLI is not authenticated; sign in with the Codex CLI, "
            "or start a run with --agent scripted"
        )
    if not details:
        details = f"exit status {completed.returncode}"
    return f"Codex CLI failed: {details[-1000:]}"
