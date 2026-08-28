"""PostgreSQL observation and integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from implicit_decision_gate.probe import (
    COMPOSE_ADMIN_DSN,
    EXISTING_LINK_ROLLOUT,
    EXPIRE_EXISTING,
    PRESERVE_EXISTING,
    Observation,
    PostgresProbe,
    normalize_observation,
)
from tests.conftest import SCHEMA

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
        with psycopg.connect(COMPOSE_ADMIN_DSN, connect_timeout=1):
            return True
    except psycopg.Error:
        return False


@pytest.mark.parametrize(
    ("existing_expiration", "expected"),
    [
        (None, PRESERVE_EXISTING),
        (datetime(2026, 2, 1, tzinfo=UTC), EXPIRE_EXISTING),
    ],
)
def test_normalize_maps_both_reference_behaviors(
    existing_expiration: datetime | None,
    expected: str,
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
    assert result.outcomes == {EXISTING_LINK_ROLLOUT: expected}


@pytest.mark.skipif(not postgres_available(), reason="PostgreSQL 17 probe container is not running")
@pytest.mark.parametrize(
    ("migration", "expected"),
    [
        (PRESERVE_MIGRATION, PRESERVE_EXISTING),
        (EXPIRE_MIGRATION, EXPIRE_EXISTING),
    ],
)
def test_postgres_probe_maps_reference_migrations(
    migration: str,
    expected: str,
) -> None:
    result = PostgresProbe(COMPOSE_ADMIN_DSN).observe(migration, SCHEMA)
    assert result.outcomes == {EXISTING_LINK_ROLLOUT: expected}
    assert result.facts["rollback_verified"] is True
    assert result.facts["insert_without_value"] == "approximately_now_plus_30_days"
    assert {
        (effect.rule_id, effect.change, effect.identity, effect.attribute)
        for effect in result.effects
    } == {
        ("schema_shape", "ADDED", "public.share_links.expires_at", "data_type"),
        ("schema_shape", "ADDED", "public.share_links.expires_at", "default"),
        ("schema_shape", "ADDED", "public.share_links.expires_at", "nullable"),
    }
