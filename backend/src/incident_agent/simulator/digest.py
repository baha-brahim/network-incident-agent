"""A stable content digest of a World, to prove that a world did not change.

Floats are rounded to 6 decimals (the simulator rounds its output to 5 at most) so that a last-bit
difference between platforms cannot change the digest.
"""

import hashlib
import json

import numpy as np
import pandas as pd

from incident_agent.simulator.world import World


def _column_bytes(series: pd.Series) -> bytes:
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        nanos = (series - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(1, "ns")
        return bytes(nanos.to_numpy().astype("int64").tobytes())
    kind = series.dtype.kind
    if kind == "f":
        return (np.round(series.to_numpy(dtype="float64"), 6) + 0.0).tobytes()
    if kind in "iub":
        return series.to_numpy().astype("int64").tobytes()
    parts = [json.dumps(v, sort_keys=True, default=str) for v in series.tolist()]
    return "\x1f".join(parts).encode("utf-8")


def table_digest(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(f"{len(df)}|{','.join(df.columns)}".encode())
    for col in df.columns:
        h.update(col.encode())
        h.update(b"\x00")
        h.update(_column_bytes(df[col]))
    return h.hexdigest()


def table_digests(world: World) -> dict[str, str]:
    """Digest of every table, keyed by table name."""
    return {name: table_digest(df) for name, df in sorted(world.tables().items())}


def world_digest(world: World) -> str:
    """One digest over all tables."""
    h = hashlib.sha256()
    for name, digest in table_digests(world).items():
        h.update(f"{name}={digest};".encode())
    return h.hexdigest()
