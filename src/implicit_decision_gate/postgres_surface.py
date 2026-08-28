"""Normalized PostgreSQL structural effects from one small catalog surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import psycopg

from implicit_decision_gate.scenario import EffectChange, FactValue, ObservedEffect

SCHEMA_SHAPE = "schema_shape"
DATA_INTEGRITY = "data_integrity"
INDEXING = "indexing"

_CATALOG_QUERY = """
SELECT
    'schema_shape',
    'table',
    format('%I.%I', namespace.nspname, relation.relname),
    'exists',
    to_jsonb(true)
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
    AND relation.relkind IN ('r', 'p')

UNION ALL

SELECT
    'schema_shape',
    'column',
    format('%I.%I.%I', namespace.nspname, relation.relname, column_definition.attname),
    fact.attribute,
    fact.value
FROM pg_catalog.pg_attribute AS column_definition
JOIN pg_catalog.pg_class AS relation
    ON relation.oid = column_definition.attrelid
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
LEFT JOIN pg_catalog.pg_attrdef AS default_definition
    ON default_definition.adrelid = column_definition.attrelid
    AND default_definition.adnum = column_definition.attnum
CROSS JOIN LATERAL (
    VALUES
        (
            'data_type',
            to_jsonb(
                pg_catalog.format_type(
                    column_definition.atttypid,
                    column_definition.atttypmod
                )
            )
        ),
        ('nullable', to_jsonb(NOT column_definition.attnotnull)),
        (
            'default',
            to_jsonb(
                pg_catalog.pg_get_expr(
                    default_definition.adbin,
                    default_definition.adrelid,
                    false
                )
            )
        )
) AS fact(attribute, value)
WHERE namespace.nspname = 'public'
    AND relation.relkind IN ('r', 'p')
    AND column_definition.attnum > 0
    AND NOT column_definition.attisdropped

UNION ALL

SELECT
    'data_integrity',
    'constraint',
    format('%I.%I.%I', namespace.nspname, relation.relname, constraint_definition.conname),
    fact.attribute,
    fact.value
FROM pg_catalog.pg_constraint AS constraint_definition
JOIN pg_catalog.pg_class AS relation
    ON relation.oid = constraint_definition.conrelid
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL (
    VALUES
        (
            'constraint_type',
            to_jsonb(
                CASE constraint_definition.contype
                    WHEN 'c' THEN 'check'
                    WHEN 'f' THEN 'foreign_key'
                    WHEN 'p' THEN 'primary_key'
                    WHEN 'u' THEN 'unique'
                END
            )
        ),
        (
            'definition',
            to_jsonb(pg_catalog.pg_get_constraintdef(constraint_definition.oid, false))
        )
) AS fact(attribute, value)
WHERE namespace.nspname = 'public'
    AND relation.relkind IN ('r', 'p')
    AND constraint_definition.contype IN ('c', 'f', 'p', 'u')

UNION ALL

SELECT
    'indexing',
    'index',
    format('%I.%I.%I', namespace.nspname, relation.relname, index_relation.relname),
    fact.attribute,
    fact.value
FROM pg_catalog.pg_index AS index_definition
JOIN pg_catalog.pg_class AS relation
    ON relation.oid = index_definition.indrelid
JOIN pg_catalog.pg_class AS index_relation
    ON index_relation.oid = index_definition.indexrelid
JOIN pg_catalog.pg_namespace AS namespace
    ON namespace.oid = relation.relnamespace
CROSS JOIN LATERAL (
    VALUES
        ('unique', to_jsonb(index_definition.indisunique)),
        (
            'definition',
            to_jsonb(pg_catalog.pg_get_indexdef(index_definition.indexrelid, 0, false))
        )
) AS fact(attribute, value)
WHERE namespace.nspname = 'public'
    AND relation.relkind IN ('r', 'p')
    AND NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS owning_constraint
        WHERE owning_constraint.conindid = index_definition.indexrelid
            AND owning_constraint.contype IN ('p', 'u', 'x')
    )
"""


@dataclass(frozen=True, order=True)
class CatalogFact:
    """The stable identity of one observed catalog attribute."""

    rule_id: str
    object_kind: str
    identity: str
    attribute: str


type CatalogSnapshot = dict[CatalogFact, FactValue]


def capture_catalog(
    connection: psycopg.Connection[tuple[Any, ...]],
) -> CatalogSnapshot:
    """Capture the supported public-schema facts without persisting PostgreSQL OIDs."""

    with connection.transaction(force_rollback=True):
        connection.execute("SET LOCAL search_path = pg_catalog")
        rows = connection.execute(_CATALOG_QUERY).fetchall()

    snapshot: CatalogSnapshot = {}
    for rule_id, object_kind, identity, attribute, value in rows:
        fact = CatalogFact(
            rule_id=cast(str, rule_id),
            object_kind=cast(str, object_kind),
            identity=cast(str, identity),
            attribute=cast(str, attribute),
        )
        snapshot[fact] = cast(FactValue, value)
    return snapshot


def diff_catalogs(
    before: CatalogSnapshot,
    after: CatalogSnapshot,
) -> list[ObservedEffect]:
    """Return a deterministic attribute-level diff between two catalog snapshots."""

    effects: list[ObservedEffect] = []
    for fact in sorted(before.keys() | after.keys()):
        change: EffectChange
        before_value: FactValue
        after_value: FactValue
        if fact not in before:
            change = "ADDED"
            before_value = None
            after_value = after[fact]
        elif fact not in after:
            change = "REMOVED"
            before_value = before[fact]
            after_value = None
        elif before[fact] != after[fact]:
            change = "CHANGED"
            before_value = before[fact]
            after_value = after[fact]
        else:
            continue
        effects.append(
            ObservedEffect(
                rule_id=fact.rule_id,
                change=change,
                object_kind=fact.object_kind,
                identity=fact.identity,
                attribute=fact.attribute,
                before=before_value,
                after=after_value,
            )
        )
    return effects
