"""The two fixed demonstration scenarios."""

from __future__ import annotations

from pathlib import Path

from implicit_decision_gate.api_probe import (
    ADMINISTRATOR_ACCESS,
    API_ADMINISTRATOR_COVERAGE,
    API_MEMBER_COVERAGE,
    API_OBSERVER_ID,
    API_OBSERVER_VERSION,
    API_OWNER_COVERAGE,
    API_REPEAT_COVERAGE,
    CREATE_ANOTHER_EXPORT,
    MEMBER_DENIAL_INVARIANT,
    OWNER_AND_ADMIN,
    OWNER_FIRST_REQUEST_INVARIANT,
    OWNER_ONLY,
    REPEAT_REQUEST,
    REUSE_ACTIVE_EXPORT,
)
from implicit_decision_gate.policy import ShareLinkExpirationEffectClassifier
from implicit_decision_gate.probe import (
    COLUMN_SHAPE_INVARIANT,
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    NEW_LINK_EXPIRATION_INVARIANT,
    POSTGRES_COLUMN_COVERAGE,
    POSTGRES_EXISTING_LINK_COVERAGE,
    POSTGRES_INDEXING_COVERAGE,
    POSTGRES_INTEGRITY_COVERAGE,
    POSTGRES_NEW_LINK_COVERAGE,
    POSTGRES_OBSERVER_ID,
    POSTGRES_OBSERVER_VERSION,
    POSTGRES_ROLLBACK_COVERAGE,
    POSTGRES_SCHEMA_COVERAGE,
    PRESERVE_EXISTING,
    ROLLBACK_INVARIANT,
)
from implicit_decision_gate.scenario import (
    CoverageRuleSpec,
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
        decisions=(
            DecisionSpec(
                id=EXISTING_LINK_ROLLOUT,
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
                            "NULL. In PostgreSQL, adding the column with its non-NULL default in "
                            "one statement would make existing rows read that default, so add the "
                            "nullable column without a default before setting the default for "
                            "future inserts."
                        ),
                    ),
                    DecisionOption(
                        id=EXPIRE_EXISTING,
                        behavior=(
                            "Existing item-sharing links receive an expiration approximately 30 "
                            "days from migration."
                        ),
                        acceptance_criteria=(
                            "After migration, the seeded pre-existing row must read an expires_at "
                            "value approximately 30 days after migration time."
                        ),
                    ),
                ),
            ),
        ),
        invariant_ids=(
            COLUMN_SHAPE_INVARIANT,
            NEW_LINK_EXPIRATION_INVARIANT,
            ROLLBACK_INVARIANT,
        ),
        coverage_rules=(
            CoverageRuleSpec(
                id=POSTGRES_COLUMN_COVERAGE,
                surface_id="postgres_share_links",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Observe the expires_at type, nullability, and default.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_NEW_LINK_COVERAGE,
                surface_id="postgres_share_links",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Insert a new link and observe its expiration.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_EXISTING_LINK_COVERAGE,
                surface_id="postgres_share_links",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Observe the expiration of a seeded existing link.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_SCHEMA_COVERAGE,
                surface_id="postgres_public_schema",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Diff tables and column shape in the public schema.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_INTEGRITY_COVERAGE,
                surface_id="postgres_public_schema",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Diff primary, unique, check, and foreign-key constraints.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_INDEXING_COVERAGE,
                surface_id="postgres_public_schema",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Diff standalone indexes in the public schema.",
            ),
            CoverageRuleSpec(
                id=POSTGRES_ROLLBACK_COVERAGE,
                surface_id="postgres_probe_runtime",
                observer_id=POSTGRES_OBSERVER_ID,
                observer_version=POSTGRES_OBSERVER_VERSION,
                owner="database-platform",
                description="Verify the disposable migration transaction rolls back.",
            ),
        ),
        effect_classifiers=(ShareLinkExpirationEffectClassifier(),),
        observer=postgres_observer,
        policy_version="2",
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
        decisions=(
            DecisionSpec(
                id=ADMINISTRATOR_ACCESS,
                question="Should workspace administrators be allowed to create exports?",
                reason=(
                    "The gate could not establish from the brief whether administrators may "
                    "create workspace exports."
                ),
                options=(
                    DecisionOption(
                        id=OWNER_ONLY,
                        behavior="Administrators create no export job and receive 403.",
                        acceptance_criteria=(
                            "create_export must return 202 and append one job for the first owner "
                            "request; it must return 403 and append no job for administrator or "
                            "member."
                        ),
                    ),
                    DecisionOption(
                        id=OWNER_AND_ADMIN,
                        behavior="Administrators create one export job and receive 202.",
                        acceptance_criteria=(
                            "create_export must return 202 and append one job for the first owner "
                            "request or an administrator; it must return 403 and append no job "
                            "for a member."
                        ),
                    ),
                ),
            ),
            DecisionSpec(
                id=REPEAT_REQUEST,
                question=(
                    "What should happen when an owner requests an export while one already exists?"
                ),
                reason=(
                    "The gate could not establish from the brief whether a repeated owner request "
                    "should create another export job."
                ),
                options=(
                    DecisionOption(
                        id=CREATE_ANOTHER_EXPORT,
                        behavior="A repeated owner request creates another export job.",
                        acceptance_criteria=(
                            "Two consecutive owner calls sharing one initially empty export_jobs "
                            "list must both return 202 and append one job, leaving two jobs."
                        ),
                    ),
                    DecisionOption(
                        id=REUSE_ACTIVE_EXPORT,
                        behavior=(
                            "A repeated owner request receives 202 without creating another "
                            "export job."
                        ),
                        acceptance_criteria=(
                            "Two consecutive owner calls sharing one initially empty export_jobs "
                            "list must both return 202; the first appends one job and the second "
                            "appends none, leaving one job."
                        ),
                    ),
                ),
            ),
        ),
        invariant_ids=(OWNER_FIRST_REQUEST_INVARIANT, MEMBER_DENIAL_INVARIANT),
        coverage_rules=(
            CoverageRuleSpec(
                id=API_OWNER_COVERAGE,
                surface_id="workspace_export_api",
                observer_id=API_OBSERVER_ID,
                observer_version=API_OBSERVER_VERSION,
                owner="workspace-platform",
                description="Call the first owner request and observe status and job creation.",
            ),
            CoverageRuleSpec(
                id=API_MEMBER_COVERAGE,
                surface_id="workspace_export_api",
                observer_id=API_OBSERVER_ID,
                observer_version=API_OBSERVER_VERSION,
                owner="workspace-platform",
                description="Call a member request and observe denial and job creation.",
            ),
            CoverageRuleSpec(
                id=API_ADMINISTRATOR_COVERAGE,
                surface_id="workspace_export_api",
                observer_id=API_OBSERVER_ID,
                observer_version=API_OBSERVER_VERSION,
                owner="workspace-platform",
                description="Call an administrator request and classify the access policy.",
            ),
            CoverageRuleSpec(
                id=API_REPEAT_COVERAGE,
                surface_id="workspace_export_api",
                observer_id=API_OBSERVER_ID,
                observer_version=API_OBSERVER_VERSION,
                owner="workspace-platform",
                description="Repeat an owner request with shared state and classify its behavior.",
            ),
        ),
        effect_classifiers=(),
        observer=authorization_observer,
        policy_version="2",
    )
    return {postgres.id: postgres, authorization.id: authorization}
