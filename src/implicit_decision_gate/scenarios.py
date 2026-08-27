"""The two fixed demonstration scenarios."""

from __future__ import annotations

from pathlib import Path

from implicit_decision_gate.api_probe import OWNER_AND_ADMIN, OWNER_ONLY
from implicit_decision_gate.probe import EXPIRE_EXISTING, PRESERVE_EXISTING
from implicit_decision_gate.scenario import (
    DecisionOption,
    DecisionSpec,
    EffectObserver,
    Scenario,
)

SHARE_LINK_EXPIRATION = "share-link-expiration"
WORKSPACE_EXPORT_AUTHORIZATION = "workspace-export-authorization"


def scenario_registry(
    postgres_observer: EffectObserver,
    authorization_observer: EffectObserver,
) -> dict[str, Scenario]:
    """Build the fixed scenario registry with supplied observers."""

    postgres = Scenario(
        id=SHARE_LINK_EXPIRATION,
        brief_path=Path("examples/share-link-expiration/brief.md"),
        context_path=Path("examples/share-link-expiration/schema.sql"),
        context_label="Baseline schema",
        artifact_directory=Path("examples/share-link-expiration/migrations"),
        artifact_suffix=".sql",
        coding_instructions=(
            "You create exactly one PostgreSQL migration.\n"
            "Use only the supplied brief and baseline schema. Do not inspect or edit "
            "repository files.\n"
            "Return the complete migration as the structured artifact, without "
            "transaction-control statements."
        ),
        decision=DecisionSpec(
            id="existing_item_sharing_link_rollout",
            question="What should happen to existing item-sharing links?",
            reason=(
                "The gate could not establish from the brief whether the 30-day expiration "
                "should apply to existing item-sharing links."
            ),
            options=(
                DecisionOption(
                    id=PRESERVE_EXISTING,
                    behavior=("Existing item-sharing links remain non-expiring with NULL."),
                    acceptance_criteria=(
                        "After migration, the seeded pre-existing row must read expires_at IS "
                        "NULL. In PostgreSQL, adding the column with its non-NULL default in one "
                        "statement would make existing rows read that default, so add the "
                        "nullable column without a default before setting the default for future "
                        "inserts."
                    ),
                ),
                DecisionOption(
                    id=EXPIRE_EXISTING,
                    behavior=(
                        "Existing item-sharing links receive an expiration approximately 30 days "
                        "from migration."
                    ),
                    acceptance_criteria=(
                        "After migration, the seeded pre-existing row must read an expires_at "
                        "value approximately 30 days after migration time."
                    ),
                ),
            ),
        ),
        observer=postgres_observer,
    )
    authorization = Scenario(
        id=WORKSPACE_EXPORT_AUTHORIZATION,
        brief_path=Path("examples/workspace-export-authorization/brief.md"),
        context_path=Path("examples/workspace-export-authorization/handler.py"),
        context_label="Baseline handler module",
        artifact_directory=Path("examples/workspace-export-authorization/implementations"),
        artifact_suffix=".py",
        coding_instructions=(
            "You create exactly one Python module implementing the supplied handler contract.\n"
            "Use only the supplied brief and baseline module. Do not inspect or edit repository "
            "files.\n"
            "Return the complete Python module as the structured artifact."
        ),
        decision=DecisionSpec(
            id="workspace_export_administrator_access",
            question="Should workspace administrators be allowed to create exports?",
            reason=(
                "The gate could not establish from the brief whether administrators may create "
                "workspace exports."
            ),
            options=(
                DecisionOption(
                    id=OWNER_ONLY,
                    behavior="Administrators create no export job and receive 403.",
                    acceptance_criteria=(
                        "create_export must return 202 and append one job for owner; it must "
                        "return 403 and append no job for administrator or member."
                    ),
                ),
                DecisionOption(
                    id=OWNER_AND_ADMIN,
                    behavior="Administrators create one export job and receive 202.",
                    acceptance_criteria=(
                        "create_export must return 202 and append one job for owner or "
                        "administrator; it must return 403 and append no job for member."
                    ),
                ),
            ),
        ),
        observer=authorization_observer,
    )
    return {postgres.id: postgres, authorization.id: authorization}
