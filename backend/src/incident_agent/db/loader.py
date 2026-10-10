"""Bulk-load a simulator World into Postgres with COPY, in one transaction."""

import json
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb
from sqlalchemy import Engine

from incident_agent.db.session import get_engine
from incident_agent.simulator.world import SCHEMA, Dtype, World

# Parents before children (foreign keys). gt.scenarios is last: it references nodes.
LOAD_ORDER = [
    "regions",
    "nodes",
    "cells",
    "cell_kpis",
    "core_kpis",
    "alarms",
    "changes",
    "maintenance",
    "external_events",
    "dataset_meta",
    "scenarios",
]
GT_TABLES = {"scenarios"}


def qualified_name(table: str) -> str:
    return f"gt.{table}" if table in GT_TABLES else f"public.{table}"


def _json_default(obj: object) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def _dumps_json(obj: object) -> str:
    return json.dumps(obj, default=_json_default)


def _timestamps(s: pd.Series) -> list[Any]:
    # Timestamp is a datetime subclass, so psycopg dumps it as timestamptz; NaT becomes NULL.
    values: list[Any] = s.astype(object).tolist()
    return [None if pd.isna(v) else v for v in values]


def _nullable(s: pd.Series) -> list[Any]:
    values: list[Any] = s.astype(object).tolist()
    return [None if pd.isna(v) else v for v in values]


def _string_arrays(s: pd.Series) -> list[list[str]]:
    return [[str(x) for x in v] for v in s]


def _column_values(s: pd.Series, dtype: Dtype) -> list[Any]:
    """One column as Python objects that psycopg adapts to the right Postgres type."""
    converters: dict[Dtype, Callable[[pd.Series], list[Any]]] = {
        "ts": _timestamps,
        "ts?": _timestamps,
        "str?": _nullable,
        "float?": _nullable,
        "str[]": _string_arrays,
        "json": lambda col: [Jsonb(v, dumps=_dumps_json) for v in col],
    }
    convert = converters.get(dtype)
    if convert is not None:
        return convert(s)
    if dtype == "float" and s.isna().any():
        raise ValueError(f"column {s.name!r} is not nullable but contains NaN")
    values: list[Any] = s.tolist()  # str / int / float / bool: native Python scalars
    return values


def _rows(df: pd.DataFrame, columns: list[tuple[str, Dtype]]) -> Iterator[tuple[Any, ...]]:
    return zip(*(_column_values(df[name], dtype) for name, dtype in columns), strict=True)


def _copy_table(conn: Connection[Any], table: str, df: pd.DataFrame) -> int:
    columns = SCHEMA[table]
    names = ", ".join(name for name, _ in columns)
    with conn.cursor() as cur, cur.copy(f"COPY {qualified_name(table)} ({names}) FROM STDIN") as cp:
        for row in _rows(df, columns):
            cp.write_row(row)
    return len(df)


def load_world(world: World, engine: Engine | None = None) -> dict[str, int]:
    """Replace the contents of every simulator table with `world`; return rows per table.

    Truncate and reload happen in a single transaction, so a failure leaves the old data intact.
    """
    world.validate()
    tables = world.tables()
    counts: dict[str, int] = {}
    with (engine or get_engine()).begin() as sa_conn:
        raw: Connection[Any] = sa_conn.connection.driver_connection  # type: ignore[assignment]
        with raw.cursor() as cur:
            cur.execute("TRUNCATE " + ", ".join(qualified_name(t) for t in LOAD_ORDER))
        for table in LOAD_ORDER:
            counts[table] = _copy_table(raw, table, tables[table])
    return counts
