"""Disposable PostgreSQL migration execution and behavior normalization."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from implicit_decision_gate.policy import coverage_evidence_digest
from implicit_decision_gate.postgres_surface import (
    DATA_INTEGRITY,
    INDEXING,
    SCHEMA_SHAPE,
    CatalogSnapshot,
    capture_catalog,
    diff_catalogs,
)
from implicit_decision_gate.scenario import (
    CoverageResult,
    CoverageStatus,
    DecisionObservation,
    FactValue,
    InvariantResult,
    InvariantStatus,
    ObservationResult,
    UnknownEffect,
)

EXPECTED_DATA_TYPE = "timestamp with time zone"
EXISTING_LINK_ROLLOUT = "existing_item_sharing_link_rollout"
PRESERVE_EXISTING = "PRESERVE_EXISTING"
EXPIRE_EXISTING = "EXPIRE_EXISTING"
COLUMN_SHAPE_INVARIANT = "share_link_expiration_column_shape"
NEW_LINK_EXPIRATION_INVARIANT = "share_link_new_link_expiration"
ROLLBACK_INVARIANT = "share_link_probe_rollback"
POSTGRES_COLUMN_COVERAGE = "postgres.expiration_column_shape"
POSTGRES_NEW_LINK_COVERAGE = "postgres.new_link_expiration"
POSTGRES_EXISTING_LINK_COVERAGE = "postgres.existing_link_rollout"
POSTGRES_SCHEMA_COVERAGE = "postgres.schema_shape"
POSTGRES_INTEGRITY_COVERAGE = "postgres.data_integrity"
POSTGRES_INDEXING_COVERAGE = "postgres.indexing"
POSTGRES_ROLLBACK_COVERAGE = "postgres.rollback"
POSTGRES_OBSERVER_ID = "postgres_migration_probe"
POSTGRES_OBSERVER_VERSION = "1"
COMPOSE_ADMIN_DSN = "postgresql://idg_admin:idg_admin@127.0.0.1:55432/postgres"
APPROXIMATION_TOLERANCE = timedelta(seconds=10)
TRANSACTION_CONTROL = re.compile(
    r"\b(?:BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\b",
    flags=re.IGNORECASE,
)


class ProbeError(RuntimeError):
    """Raised when a migration cannot be safely probed."""


@dataclass(frozen=True)
class Observation:
    """Raw facts needed to classify the two supported rollout options."""

    data_type: str | None
    nullable: bool | None
    column_default: str | None
    existing_row_found: bool
    existing_expiration: datetime | None
    inserted_row_created: bool
    inserted_expiration: datetime | None
    migration_time: datetime


def _approximately_thirty_days_after(
    value: datetime | None,
    origin: datetime,
) -> bool:
    if value is None:
        return False
    expected = origin + timedelta(days=30)
    return abs(value - expected) <= APPROXIMATION_TOLERANCE


def normalize_observation(observation: Observation) -> ObservationResult:
    """Separate required migration behavior from the rollout decision."""

    existing_label = "missing"
    if observation.existing_row_found:
        if observation.existing_expiration is None:
            existing_label = "null"
        elif _approximately_thirty_days_after(
            observation.existing_expiration,
            observation.migration_time,
        ):
            existing_label = "approximately_migration_time_plus_30_days"
        else:
            existing_label = "other"

    inserted_label = "insert_failed"
    if observation.inserted_row_created:
        if _approximately_thirty_days_after(
            observation.inserted_expiration,
            observation.migration_time,
        ):
            inserted_label = "approximately_now_plus_30_days"
        elif observation.inserted_expiration is None:
            inserted_label = "null"
        else:
            inserted_label = "other"

    column_shape_matches = (
        observation.data_type == EXPECTED_DATA_TYPE
        and observation.nullable is True
        and observation.column_default is not None
    )
    new_link_matches = inserted_label == "approximately_now_plus_30_days"
    facts: dict[str, FactValue] = {
        "data_type": observation.data_type,
        "nullable": observation.nullable,
        "column_default": observation.column_default,
        "insert_without_value": inserted_label,
        "existing_row": existing_label,
        "rollback_verified": False,
    }
    column_evidence = {
        "data_type": observation.data_type,
        "nullable": observation.nullable,
        "column_default": observation.column_default,
    }
    new_link_evidence = {"insert_without_value": inserted_label}
    existing_evidence = {"existing_row": existing_label}
    decisions: list[DecisionObservation] = []
    unknown_effects: list[UnknownEffect] = []
    if existing_label == "null":
        decisions.append(
            DecisionObservation(
                decision_id=EXISTING_LINK_ROLLOUT,
                option_id=PRESERVE_EXISTING,
                evidence=existing_evidence,
            )
        )
    elif existing_label == "approximately_migration_time_plus_30_days":
        decisions.append(
            DecisionObservation(
                decision_id=EXISTING_LINK_ROLLOUT,
                option_id=EXPIRE_EXISTING,
                evidence=existing_evidence,
            )
        )
    else:
        unknown_effects.append(
            UnknownEffect(
                surface_id="postgres_share_links",
                rule_id=POSTGRES_EXISTING_LINK_COVERAGE,
                decision_id=EXISTING_LINK_ROLLOUT,
                description="Existing-link behavior is outside the approved rollout vocabulary.",
                evidence=existing_evidence,
            )
        )

    return ObservationResult(
        invariants=[
            InvariantResult(
                invariant_id=COLUMN_SHAPE_INVARIANT,
                expected=(
                    "expires_at is a nullable timestamp with time zone with a default for new rows."
                ),
                observed=(
                    f"type={observation.data_type}, nullable={observation.nullable}, "
                    f"default={observation.column_default}"
                ),
                status=(
                    InvariantStatus.PASSED if column_shape_matches else InvariantStatus.VIOLATED
                ),
                evidence=column_evidence,
            ),
            InvariantResult(
                invariant_id=NEW_LINK_EXPIRATION_INVARIANT,
                expected="A new link expires approximately 30 days after creation.",
                observed=inserted_label,
                status=(InvariantStatus.PASSED if new_link_matches else InvariantStatus.VIOLATED),
                evidence=new_link_evidence,
            ),
        ],
        decisions=decisions,
        unknown_effects=unknown_effects,
        facts=facts,
        coverage=[
            _coverage_result(POSTGRES_COLUMN_COVERAGE, column_evidence),
            _coverage_result(POSTGRES_NEW_LINK_COVERAGE, new_link_evidence),
            _coverage_result(POSTGRES_EXISTING_LINK_COVERAGE, existing_evidence),
        ],
    )


class PostgresProbe:
    """Probe migrations in fresh databases hosted by the test container."""

    def __init__(self, admin_dsn: str) -> None:
        self.admin_dsn = admin_dsn

    def observe(self, artifact: str, context: str) -> ObservationResult:
        """Execute a migration as a limited role and always discard its transaction."""

        if TRANSACTION_CONTROL.search(artifact):
            raise ProbeError("Migration SQL must not contain transaction-control statements")
        suffix = uuid.uuid4().hex[:12]
        database_name = f"idg_probe_{suffix}"
        role_name = f"idg_role_{suffix}"
        password = secrets.token_urlsafe(24)
        self._create_database(database_name, role_name, password)
        try:
            user_dsn = self._user_dsn(database_name, role_name, password)
            result = self._execute(user_dsn, artifact, context)
        finally:
            self._drop_database(database_name, role_name)
        return result

    def _create_database(self, database_name: str, role_name: str, password: str) -> None:
        try:
            with (
                psycopg.connect(self.admin_dsn, autocommit=True) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION"
                    ).format(sql.Identifier(role_name), sql.Literal(password))
                )
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database_name),
                        sql.Identifier(role_name),
                    )
                )
        except psycopg.Error as error:
            raise ProbeError(f"Could not create disposable probe database: {error}") from error

    def _drop_database(self, database_name: str, role_name: str) -> None:
        try:
            with (
                psycopg.connect(self.admin_dsn, autocommit=True) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (database_name,),
                )
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
                )
                cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))
        except psycopg.Error as error:
            raise ProbeError(f"Could not remove disposable probe database: {error}") from error

    def _user_dsn(self, database_name: str, role_name: str, password: str) -> str:
        return make_conninfo(
            self.admin_dsn,
            dbname=database_name,
            user=role_name,
            password=password,
        )

    def _execute(
        self,
        user_dsn: str,
        migration: str,
        baseline_schema: str,
    ) -> ObservationResult:
        try:
            with psycopg.connect(user_dsn, autocommit=True) as connection:
                connection.execute(baseline_schema)
                connection.execute("BEGIN")
                try:
                    baseline_snapshot = capture_catalog(connection)
                    migration_time_row = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()
                    if migration_time_row is None:
                        raise ProbeError("PostgreSQL did not return the migration time")
                    migration_time = cast(datetime, migration_time_row[0])
                    connection.execute(migration)
                    migrated_snapshot = capture_catalog(connection)
                    observation = self._observe(connection, migration_time)
                    result = normalize_observation(observation)
                    result.effects = diff_catalogs(baseline_snapshot, migrated_snapshot)
                    for rule_id, structural_rule in (
                        (POSTGRES_SCHEMA_COVERAGE, SCHEMA_SHAPE),
                        (POSTGRES_INTEGRITY_COVERAGE, DATA_INTEGRITY),
                        (POSTGRES_INDEXING_COVERAGE, INDEXING),
                    ):
                        result.coverage.append(
                            _coverage_result(
                                rule_id,
                                {
                                    "effects": "\n".join(
                                        effect.model_dump_json()
                                        for effect in result.effects
                                        if effect.rule_id == structural_rule
                                    )
                                },
                            )
                        )
                finally:
                    connection.execute("ROLLBACK")
                rollback_verified = self._rollback_verified(connection, baseline_snapshot)
                result.facts["rollback_verified"] = rollback_verified
                if not rollback_verified:
                    raise ProbeError("Migration transaction rollback could not be verified")
                rollback_evidence = {"rollback_verified": rollback_verified}
                result.invariants.append(
                    InvariantResult(
                        invariant_id=ROLLBACK_INVARIANT,
                        expected="The disposable migration transaction is fully rolled back.",
                        observed=f"rollback_verified={rollback_verified}",
                        status=InvariantStatus.PASSED,
                        evidence=rollback_evidence,
                    )
                )
                result.coverage.append(
                    _coverage_result(POSTGRES_ROLLBACK_COVERAGE, rollback_evidence)
                )
                return result
        except ProbeError:
            raise
        except psycopg.Error as error:
            raise ProbeError(f"Migration probe failed: {error}") from error

    def _observe(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        migration_time: datetime,
    ) -> Observation:
        column_row = connection.execute(
            "SELECT data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'share_links' "
            "AND column_name = 'expires_at'"
        ).fetchone()
        if column_row is None:
            return Observation(
                data_type=None,
                nullable=None,
                column_default=None,
                existing_row_found=False,
                existing_expiration=None,
                inserted_row_created=False,
                inserted_expiration=None,
                migration_time=migration_time,
            )

        data_type = cast(str, column_row[0])
        nullable = column_row[1] == "YES"
        column_default = cast(str | None, column_row[2])
        existing_row = connection.execute(
            "SELECT expires_at FROM public.share_links WHERE token = 'existing-fixture'"
        ).fetchone()
        existing_row_found = existing_row is not None
        existing_expiration = (
            cast(datetime | None, existing_row[0]) if existing_row is not None else None
        )

        inserted_row_created = False
        inserted_expiration: datetime | None = None
        connection.execute("SAVEPOINT idg_insert_probe")
        try:
            inserted_row = connection.execute(
                "INSERT INTO public.share_links (token) VALUES ('new-probe') RETURNING expires_at"
            ).fetchone()
            if inserted_row is not None:
                inserted_row_created = True
                inserted_expiration = cast(datetime | None, inserted_row[0])
        except psycopg.Error:
            connection.execute("ROLLBACK TO SAVEPOINT idg_insert_probe")
        finally:
            connection.execute("RELEASE SAVEPOINT idg_insert_probe")

        return Observation(
            data_type=data_type,
            nullable=nullable,
            column_default=column_default,
            existing_row_found=existing_row_found,
            existing_expiration=existing_expiration,
            inserted_row_created=inserted_row_created,
            inserted_expiration=inserted_expiration,
            migration_time=migration_time,
        )

    def _rollback_verified(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        baseline_snapshot: CatalogSnapshot,
    ) -> bool:
        return capture_catalog(connection) == baseline_snapshot


def _coverage_result(rule_id: str, evidence: dict[str, Any]) -> CoverageResult:
    return CoverageResult(
        rule_id=rule_id,
        status=CoverageStatus.PASSED,
        evidence_digest=coverage_evidence_digest(evidence),
    )
