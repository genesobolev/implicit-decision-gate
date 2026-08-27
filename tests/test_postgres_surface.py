"""Tests for the reusable PostgreSQL structural surface."""

from __future__ import annotations

import psycopg
import pytest

from implicit_decision_gate.postgres_surface import (
    DATA_INTEGRITY,
    INDEXING,
    SCHEMA_SHAPE,
    CatalogFact,
    CatalogSnapshot,
    capture_catalog,
    diff_catalogs,
)
from implicit_decision_gate.probe import COMPOSE_ADMIN_DSN
from implicit_decision_gate.scenario import ObservedEffect
from tests.test_probe import postgres_available


def _effect_lines(effects: list[ObservedEffect]) -> list[str]:
    return [
        "|".join(
            (
                effect.rule_id,
                effect.change,
                effect.object_kind,
                effect.identity,
                effect.attribute,
                repr(effect.before),
                repr(effect.after),
            )
        )
        for effect in effects
    ]


def _observe_effects(baseline: str, migration: str) -> list[ObservedEffect]:
    with psycopg.connect(COMPOSE_ADMIN_DSN, autocommit=True) as connection:
        connection.execute("BEGIN")
        try:
            connection.execute(baseline)
            before = capture_catalog(connection)
            connection.execute(migration)
            after = capture_catalog(connection)
        finally:
            connection.execute("ROLLBACK")
    return diff_catalogs(before, after)


def test_diff_catalogs_is_exact_and_deterministic() -> None:
    column = CatalogFact(SCHEMA_SHAPE, "column", "public.records.email", "nullable")
    old_index = CatalogFact(INDEXING, "index", "public.records.old_idx", "definition")
    new_constraint = CatalogFact(
        DATA_INTEGRITY,
        "constraint",
        "public.records.records_email_key",
        "definition",
    )
    unchanged = CatalogFact(SCHEMA_SHAPE, "table", "public.records", "exists")
    before: CatalogSnapshot = {
        old_index: "CREATE INDEX old_idx ON public.records USING btree (email)",
        unchanged: True,
        column: True,
    }
    after: CatalogSnapshot = {
        new_constraint: "UNIQUE (email)",
        column: False,
        unchanged: True,
    }

    assert _effect_lines(diff_catalogs(before, after)) == [
        "data_integrity|ADDED|constraint|public.records.records_email_key|definition|"
        "None|'UNIQUE (email)'",
        "indexing|REMOVED|index|public.records.old_idx|definition|"
        "'CREATE INDEX old_idx ON public.records USING btree (email)'|None",
        "schema_shape|CHANGED|column|public.records.email|nullable|True|False",
    ]


@pytest.mark.skipif(not postgres_available(), reason="PostgreSQL 17 probe container is not running")
def test_surface_captures_added_and_removed_structures() -> None:
    effects = _observe_effects(
        """
        CREATE TABLE public.keep (
            id bigint,
            obsolete text,
            email text,
            score integer,
            CONSTRAINT old_check CHECK (score >= 0)
        );
        CREATE TABLE public.legacy ();
        CREATE TABLE public.parent (id bigint);
        CREATE INDEX old_idx ON public.keep (obsolete);
        """,
        """
        CREATE TABLE public.audit ();
        DROP TABLE public.legacy;
        ALTER TABLE public.parent
            ADD CONSTRAINT parent_pkey PRIMARY KEY (id);
        ALTER TABLE public.keep
            ADD COLUMN created_at timestamp with time zone,
            ADD COLUMN parent_id bigint,
            DROP COLUMN obsolete,
            DROP CONSTRAINT old_check,
            ADD CONSTRAINT email_key UNIQUE (email),
            ADD CONSTRAINT keep_parent_fkey
                FOREIGN KEY (parent_id) REFERENCES public.parent (id);
        CREATE INDEX email_idx ON public.keep (email);
        """,
    )

    assert _effect_lines(effects) == [
        "data_integrity|ADDED|constraint|public.keep.email_key|constraint_type|None|'unique'",
        "data_integrity|ADDED|constraint|public.keep.email_key|definition|None|'UNIQUE (email)'",
        "data_integrity|ADDED|constraint|public.keep.keep_parent_fkey|constraint_type|"
        "None|'foreign_key'",
        "data_integrity|ADDED|constraint|public.keep.keep_parent_fkey|definition|"
        "None|'FOREIGN KEY (parent_id) REFERENCES public.parent(id)'",
        "data_integrity|REMOVED|constraint|public.keep.old_check|constraint_type|'check'|None",
        "data_integrity|REMOVED|constraint|public.keep.old_check|definition|"
        "'CHECK ((score >= 0))'|None",
        "data_integrity|ADDED|constraint|public.parent.parent_pkey|constraint_type|"
        "None|'primary_key'",
        "data_integrity|ADDED|constraint|public.parent.parent_pkey|definition|"
        "None|'PRIMARY KEY (id)'",
        "indexing|ADDED|index|public.keep.email_idx|definition|"
        "None|'CREATE INDEX email_idx ON public.keep USING btree (email)'",
        "indexing|ADDED|index|public.keep.email_idx|unique|None|False",
        "indexing|REMOVED|index|public.keep.old_idx|definition|"
        "'CREATE INDEX old_idx ON public.keep USING btree (obsolete)'|None",
        "indexing|REMOVED|index|public.keep.old_idx|unique|False|None",
        "schema_shape|ADDED|column|public.keep.created_at|data_type|"
        "None|'timestamp with time zone'",
        "schema_shape|ADDED|column|public.keep.created_at|default|None|None",
        "schema_shape|ADDED|column|public.keep.created_at|nullable|None|True",
        "schema_shape|REMOVED|column|public.keep.obsolete|data_type|'text'|None",
        "schema_shape|REMOVED|column|public.keep.obsolete|default|None|None",
        "schema_shape|REMOVED|column|public.keep.obsolete|nullable|True|None",
        "schema_shape|ADDED|column|public.keep.parent_id|data_type|None|'bigint'",
        "schema_shape|ADDED|column|public.keep.parent_id|default|None|None",
        "schema_shape|ADDED|column|public.keep.parent_id|nullable|None|True",
        "schema_shape|CHANGED|column|public.parent.id|nullable|True|False",
        "schema_shape|ADDED|table|public.audit|exists|None|True",
        "schema_shape|REMOVED|table|public.legacy|exists|True|None",
    ]


@pytest.mark.skipif(not postgres_available(), reason="PostgreSQL 17 probe container is not running")
def test_surface_captures_changed_structures() -> None:
    effects = _observe_effects(
        """
        CREATE TABLE public.records (
            value integer,
            email text,
            note text DEFAULT 'old'::text,
            score integer,
            CONSTRAINT score_check CHECK (score > 0)
        );
        CREATE INDEX records_email_idx ON public.records (email);
        """,
        """
        SET search_path = pg_catalog;
        ALTER TABLE public.records ALTER COLUMN value TYPE bigint;
        ALTER TABLE public.records ALTER COLUMN email SET NOT NULL;
        ALTER TABLE public.records ALTER COLUMN note SET DEFAULT 'new'::text;
        ALTER TABLE public.records DROP CONSTRAINT score_check;
        ALTER TABLE public.records ADD CONSTRAINT score_check CHECK (score >= 0);
        DROP INDEX public.records_email_idx;
        CREATE UNIQUE INDEX records_email_idx ON public.records (email);
        """,
    )

    assert _effect_lines(effects) == [
        "data_integrity|CHANGED|constraint|public.records.score_check|definition|"
        "'CHECK ((score > 0))'|'CHECK ((score >= 0))'",
        "indexing|CHANGED|index|public.records.records_email_idx|definition|"
        "'CREATE INDEX records_email_idx ON public.records USING btree (email)'|"
        "'CREATE UNIQUE INDEX records_email_idx ON public.records USING btree (email)'",
        "indexing|CHANGED|index|public.records.records_email_idx|unique|False|True",
        "schema_shape|CHANGED|column|public.records.email|nullable|True|False",
        "schema_shape|CHANGED|column|public.records.note|default|\"'old'::text\"|\"'new'::text\"",
        "schema_shape|CHANGED|column|public.records.value|data_type|'integer'|'bigint'",
    ]
