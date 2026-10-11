"""Turn tool payloads into plain JSON values, and keep them small enough to send."""

import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

MAX_DATA_BYTES = 60_000
_ITEM_LIMITS = (60, 30, 15, 8)
_MAX_STRING = 2_000
_MAX_DEPTH = 8


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """A JSON-safe copy of `value`: no datetimes, numpy types, NaN or infinities."""
    if _depth > _MAX_DEPTH:
        return None
    if value is None or isinstance(value, bool | str):
        return value
    if value is pd.NaT:
        return None
    if isinstance(value, Enum):
        return to_jsonable(value.value, _depth + 1)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return to_jsonable(float(value), _depth + 1)
    if isinstance(value, np.generic):
        return to_jsonable(value.item(), _depth + 1)
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist(), _depth + 1)
    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="json"), _depth + 1)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return [to_jsonable(v, _depth + 1) for v in sorted(value, key=str)]
    if isinstance(value, list | tuple):
        return [to_jsonable(v, _depth + 1) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _cut(value: Any, max_items: int) -> tuple[Any, bool]:
    """`value` with long lists and strings shortened, and whether anything was cut."""
    if isinstance(value, str):
        return (value, False) if len(value) <= _MAX_STRING else (value[:_MAX_STRING] + "...", True)
    if isinstance(value, list):
        cut = len(value) > max_items
        out = []
        for item in value[:max_items]:
            shorter, did = _cut(item, max_items)
            out.append(shorter)
            cut = cut or did
        return out, cut
    if isinstance(value, dict):
        cut = False
        result = {}
        for key, item in value.items():
            shorter, did = _cut(item, max_items)
            result[key] = shorter
            cut = cut or did
        return result, cut
    return value, False


def size_of(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def cap_data(value: Any) -> tuple[Any, bool]:
    """JSON-safe `value`, shortened until it fits `MAX_DATA_BYTES`. Returns (value, was_cut)."""
    safe = to_jsonable(value)
    if size_of(safe) <= MAX_DATA_BYTES:
        return safe, False
    for limit in _ITEM_LIMITS:
        shorter, _ = _cut(safe, limit)
        if size_of(shorter) <= MAX_DATA_BYTES:
            return shorter, True
    return None, True
