"""Parquet persistence for a World, plus a readable ground_truth.json."""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from incident_agent.simulator.frames import coerce
from incident_agent.simulator.world import SCHEMA, World

GROUND_TRUTH_FILE = "ground_truth.json"


def _json_cols(name: str) -> list[str]:
    return [c for c, d in SCHEMA[name] if d == "json"]


def write_world(world: World, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in world.tables().items():
        out = df.copy()
        for col in _json_cols(name):
            out[col] = [json.dumps(v, sort_keys=True) for v in df[col]]
        out.to_parquet(out_dir / f"{name}.parquet", index=False, compression="zstd")
    (out_dir / GROUND_TRUTH_FILE).write_text(
        json.dumps(ground_truth(world), indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def read_world(out_dir: Path) -> World:
    tables: dict[str, pd.DataFrame] = {}
    for name in World.__dataclass_fields__:
        df = pd.read_parquet(out_dir / f"{name}.parquet")
        for col in _json_cols(name):
            df[col] = pd.Series([json.loads(v) for v in df[col]], dtype=object)
        tables[name] = coerce(name, df)
    world = World(**tables)
    world.validate()
    return world


def ground_truth(world: World) -> dict[str, Any]:
    meta = dict(zip(world.dataset_meta["key"], world.dataset_meta["value"], strict=True))
    scenarios: list[dict[str, Any]] = []
    for row in world.scenarios.to_dict(orient="records"):
        rec: dict[str, Any] = {}
        for col, dtype in SCHEMA["scenarios"]:
            v = row[col]
            if dtype in ("ts", "ts?"):
                rec[col] = None if pd.isna(v) else v.isoformat()
            elif dtype == "str?":
                rec[col] = v if isinstance(v, str) else None
            elif dtype == "bool":
                rec[col] = bool(v)
            else:
                rec[col] = v
        scenarios.append(rec)
    return {"dataset": meta, "scenarios": scenarios}
