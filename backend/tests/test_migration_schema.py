"""The Alembic migration must mirror simulator.world.SCHEMA (names, order, types, nullability)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from incident_agent.simulator.world import SCHEMA, Dtype

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0002_synthetic_network.py"
)

SQL_TYPES: dict[Dtype, str] = {
    "str": "TEXT",
    "str?": "TEXT",
    "float": "DOUBLE PRECISION",
    "float?": "DOUBLE PRECISION",
    "int": "INTEGER",
    "bool": "BOOLEAN",
    "ts": "TIMESTAMP WITH TIME ZONE",
    "ts?": "TIMESTAMP WITH TIME ZONE",
    "str[]": "TEXT[]",
    "json": "JSONB",
}


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0002", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tables() -> dict[str, sa.Table]:
    md = _load_migration().build_metadata()
    return {t.name: t for t in md.tables.values()}


def test_migration_has_exactly_the_schema_tables(tables: dict[str, sa.Table]) -> None:
    assert set(tables) == set(SCHEMA)


def test_scenarios_live_in_gt_and_everything_else_in_public(tables: dict[str, sa.Table]) -> None:
    assert tables["scenarios"].schema == "gt"
    assert all(t.schema is None for name, t in tables.items() if name != "scenarios")


@pytest.mark.parametrize("table", sorted(SCHEMA))
def test_columns_match_schema(table: str, tables: dict[str, sa.Table]) -> None:
    dialect = postgresql.dialect()
    actual = [(c.name, c.type.compile(dialect=dialect), c.nullable) for c in tables[table].columns]
    expected = [(name, SQL_TYPES[dtype], dtype.endswith("?")) for name, dtype in SCHEMA[table]]
    assert actual == expected


def test_primary_keys_and_time_indexes(tables: dict[str, sa.Table]) -> None:
    def pk(name: str) -> list[str]:
        return [c.name for c in tables[name].primary_key.columns]

    def indexed(name: str) -> set[tuple[str, ...]]:
        return {tuple(c.name for c in ix.columns) for ix in tables[name].indexes}

    assert pk("cell_kpis") == ["cell_id", "ts"]
    assert pk("core_kpis") == ["node_id", "metric", "ts"]
    assert pk("alarms") == ["alarm_id"]
    assert ("ts",) in indexed("cell_kpis")
    assert ("raised_at",) in indexed("alarms")
    assert ("executed_at",) in indexed("changes")
    assert ("start_at",) in indexed("maintenance")
    assert ("start_at",) in indexed("external_events")
