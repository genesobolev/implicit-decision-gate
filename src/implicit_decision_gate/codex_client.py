"""Local Codex CLI adapter for one-shot structured model calls."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from implicit_decision_gate.agent import AgentError
from implicit_decision_gate.gate import (
    ModelInvocationRecord,
    ModelRole,
    ReviewerResult,
)

DEFAULT_CODEX_TIMEOUT_SECONDS = 300
CODEX_MODEL = "gpt-5.6-terra"
CODEX_REASONING_EFFORT = "xhigh"

CODING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"artifact": {"type": "string"}},
    "required": ["artifact"],
    "additionalProperties": False,
}

REVIEWER_SCHEMA: dict[str, Any] = {
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


@dataclass(frozen=True)
class CodexCLIModelClient:
    """Execute each request through a fresh ephemeral Codex CLI process."""

    executable: str = "codex"
    timeout_seconds: int = DEFAULT_CODEX_TIMEOUT_SECONDS

    def invocation_record(
        self,
        *,
        role: ModelRole,
        attempt_number: int | None,
    ) -> ModelInvocationRecord:
        """Return the pinned model configuration and installed CLI version."""

        executable_path = self._executable_path()
        try:
            completed = subprocess.run(
                [executable_path, "--version"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentError(
                f"Codex CLI version check timed out after {self.timeout_seconds} seconds"
            ) from error
        except OSError as error:
            raise AgentError(f"Could not start Codex CLI: {error}") from error
        if completed.returncode != 0:
            raise AgentError(_codex_failure_message(completed))
        version = (completed.stdout or completed.stderr).strip()
        if not version:
            raise AgentError("Codex CLI returned an empty version")
        return ModelInvocationRecord(
            role=role,
            attempt_number=attempt_number,
            model=CODEX_MODEL,
            reasoning_effort=CODEX_REASONING_EFFORT,
            codex_cli_version=version,
        )

    def propose_artifact(self, prompt: str) -> str:
        """Return one structured artifact from an isolated process."""

        payload = self._execute(
            prompt,
            schema=CODING_SCHEMA,
        )
        artifact = payload.get("artifact")
        if not isinstance(artifact, str) or not artifact.strip():
            raise AgentError("Codex CLI returned an empty artifact")
        return artifact

    def review_evidence(self, prompt: str) -> ReviewerResult:
        """Return one structured result from a fresh non-repository process."""

        payload = self._execute(
            prompt,
            schema=REVIEWER_SCHEMA,
        )
        classification = payload.get("classification")
        evidence_quote = payload.get("evidence_quote")
        if not isinstance(classification, str) or not isinstance(evidence_quote, str):
            raise AgentError("Codex CLI returned an invalid evidence result")
        try:
            return ReviewerResult.model_validate(
                {
                    "classification": classification,
                    "evidence_quote": evidence_quote or None,
                }
            )
        except ValidationError as error:
            raise AgentError("Codex CLI returned an invalid evidence result") from error

    def _execute(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        executable_path = self._executable_path()

        with tempfile.TemporaryDirectory(prefix="idg-codex-") as temporary_value:
            temporary_path = Path(temporary_value)
            schema_path = temporary_path / "output-schema.json"
            schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            command = [
                executable_path,
                "exec",
                "--model",
                CODEX_MODEL,
                "--config",
                f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
                "--strict-config",
                "--ephemeral",
                "--ignore-user-config",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
            ]
            command.append("--skip-git-repo-check")
            command.append("-")
            try:
                completed = subprocess.run(
                    command,
                    cwd=temporary_path,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise AgentError(
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
        return payload

    def _executable_path(self) -> str:
        executable_path = shutil.which(self.executable)
        if executable_path is None:
            raise AgentError("Codex CLI was not found; install and sign in to Codex")
        return executable_path


def _codex_failure_message(completed: subprocess.CompletedProcess[str]) -> str:
    details = (completed.stderr or completed.stdout).strip()
    normalized = details.lower()
    if any(marker in normalized for marker in ("auth", "login", "logged in", "sign in")):
        return "Codex CLI is not authenticated; sign in with the Codex CLI"
    if not details:
        details = f"exit status {completed.returncode}"
    return f"Codex CLI failed: {details[-1000:]}"
