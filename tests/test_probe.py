"""PostgreSQL observation and integration tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from implicit_decision_gate.gate import RolloutOption
from implicit_decision_gate.probe import Observation, PostgresProbe, normalize_observation
from tests.conftest import SCHEMA

ADMIN_DSN = os.environ.get(
    "IDG_POSTGRES_ADMIN_DSN",
    "postgresql://idg_admin:idg_admin@localhost:55432/postgres",
)
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


def postgres_available() -> bool:
    """Return whether the disposable PostgreSQL container is reachable."""

    try:
        with psycopg.connect(ADMIN_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


@pytest.mark.parametrize(
    ("existing_expiration", "expected"),
    [
        (None, RolloutOption.PRESERVE_EXISTING),
        (datetime(2026, 2, 1, tzinfo=UTC), RolloutOption.EXPIRE_EXISTING),
    ],
)
def test_normalize_maps_both_reference_behaviors(
    existing_expiration: datetime | None,
    expected: RolloutOption,
) -> None:
    migration_time = datetime(2026, 1, 2, tzinfo=UTC)
    if existing_expiration is not None:
        existing_expiration = migration_time + timedelta(days=30)
    result = normalize_observation(
        Observation(
            data_type="timestamp with time zone",
            nullable=True,
            column_default="CURRENT_TIMESTAMP + interval '30 days'",
            existing_row_found=True,
            existing_expiration=existing_expiration,
            inserted_row_created=True,
            inserted_expiration=migration_time + timedelta(days=30),
            migration_time=migration_time,
        )
    )
    assert result.rollout_option is expected


@pytest.mark.skipif(not postgres_available(), reason="PostgreSQL 17 probe container is not running")
@pytest.mark.parametrize(
    ("migration", "expected"),
    [
        (PRESERVE_MIGRATION, RolloutOption.PRESERVE_EXISTING),
        (EXPIRE_MIGRATION, RolloutOption.EXPIRE_EXISTING),
    ],
)
def test_postgres_probe_maps_reference_migrations(
    migration: str,
    expected: RolloutOption,
) -> None:
    result = PostgresProbe(ADMIN_DSN).probe(migration, SCHEMA)
    assert result.rollout_option is expected
    assert result.rollback_verified is True
    assert result.insert_without_value == "approximately_now_plus_30_days"
