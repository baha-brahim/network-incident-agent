"""Coerce DataFrames to the canonical dtypes of `world.SCHEMA` (used on build and on read)."""

from typing import Any

import pandas as pd

from incident_agent.simulator.world import SCHEMA


def coerce(name: str, df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=pd.RangeIndex(len(df)))
    for col, dtype in SCHEMA[name]:
        s = df[col].reset_index(drop=True)
        if dtype in ("str", "str?"):
            out[col] = s.astype("str")
        elif dtype in ("float", "float?"):
            out[col] = s.astype("float64")
        elif dtype == "int":
            out[col] = s.astype("int64")
        elif dtype == "bool":
            out[col] = s.astype("bool")
        elif dtype in ("ts", "ts?"):
            out[col] = pd.to_datetime(s, utc=True).astype("datetime64[ns, UTC]")
        elif dtype == "str[]":
            out[col] = pd.Series([[str(x) for x in v] for v in s], dtype=object)
        else:  # json
            out[col] = pd.Series(list(s), dtype=object)
    return out


def rows_to_frame(name: str, rows: list[dict[str, Any]]) -> pd.DataFrame:
    cols = [c for c, _ in SCHEMA[name]]
    return coerce(name, pd.DataFrame(rows, columns=cols))
