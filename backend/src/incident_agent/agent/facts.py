"""Structured records the tools returned, kept for the checks of the verify step.

Tools put their rows in `ToolResult.data`. `rows_of` picks out the ones the look-alike checks need,
keyed by evidence ref, and `Facts` parses them into typed records with tz-aware times.
Nothing here is rendered into a prompt, and a row that cannot be read is skipped, never raised.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from incident_agent.agent.tools.timeutil import parse_time

# tool -> (key of the row list in `data`, key of the row's id)
_SOURCES: dict[str, tuple[str, str]] = {
    "get_maintenance": ("rows", "mw_id"),
    "get_external_events": ("rows", "event_id"),
    "get_changes": ("rows", "change_id"),
    "get_alarms": ("rows", "alarm_id"),
    "get_anomalies": ("alerts", "alert_id"),
}


def rows_of(tool: str, data: Any) -> dict[str, dict[str, Any]]:
    """Evidence ref -> row for the tools whose rows the checks read; `{}` for anything else."""
    source = _SOURCES.get(tool)
    if source is None or not isinstance(data, dict):
        return {}
    rows_key, id_key = source
    rows = data.get(rows_key)
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get(id_key), str) and row[id_key].strip():
            out[row[id_key].strip()] = row
    return out


@dataclass(frozen=True)
class Window:
    ref: str
    node_id: str
    start: datetime
    end: datetime
    expected_impact: str


@dataclass(frozen=True)
class Event:
    ref: str
    region_id: str | None
    node_id: str | None
    start: datetime
    end: datetime | None  # None while in progress


@dataclass(frozen=True)
class Change:
    ref: str
    node_id: str
    change_type: str
    at: datetime
    description: str
    rollback_of: str | None


@dataclass(frozen=True)
class Alarm:
    ref: str
    node_id: str
    alarm_type: str
    severity: str
    raised: datetime
    cleared: datetime | None  # None while active


@dataclass(frozen=True)
class Alert:
    ref: str
    start: datetime
    end: datetime | None  # None while ongoing
    entities: tuple[str, ...]


def _id(value: Any) -> str:
    return str(value).strip().upper()


def _opt_id(value: Any) -> str | None:
    return _id(value) if value not in (None, "") else None


def _time(value: Any) -> datetime:
    return parse_time(value)


def _opt_time(value: Any) -> datetime | None:
    return None if value is None else _time(value)


def _window(row: dict[str, Any]) -> Window:
    return Window(
        _id(row["mw_id"]),
        _id(row["node_id"]),
        _time(row["start_at"]),
        _time(row["end_at"]),
        str(row.get("expected_impact") or ""),
    )


def _event(row: dict[str, Any]) -> Event:
    return Event(
        _id(row["event_id"]),
        _opt_id(row.get("region_id")),
        _opt_id(row.get("node_id")),
        _time(row["start_at"]),
        _opt_time(row.get("end_at")),
    )


def _change(row: dict[str, Any]) -> Change:
    return Change(
        _id(row["change_id"]),
        _id(row["node_id"]),
        str(row.get("change_type") or ""),
        _time(row["executed_at"]),
        str(row.get("description") or ""),
        _opt_id(row.get("rollback_of")),
    )


def _alarm(row: dict[str, Any]) -> Alarm:
    return Alarm(
        _id(row["alarm_id"]),
        _id(row["node_id"]),
        str(row.get("alarm_type") or ""),
        str(row.get("severity") or "").lower(),
        _time(row["raised_at"]),
        _opt_time(row.get("cleared_at")),
    )


def _alert(row: dict[str, Any]) -> Alert:
    entities = row.get("entities")
    if not isinstance(entities, list):
        entities = []
    return Alert(
        _id(row["alert_id"]),
        _time(row["start_at"]),
        _opt_time(row.get("end_at")),
        tuple(_id(e) for e in entities),
    )


def _kind(row: dict[str, Any]) -> str | None:
    for key, kind in (
        ("mw_id", "windows"),
        ("event_id", "events"),
        ("change_id", "changes"),
        ("alarm_id", "alarms"),
        ("alert_id", "alerts"),
    ):
        if key in row:
            return kind
    return None


_PARSERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "windows": _window,
    "events": _event,
    "changes": _change,
    "alarms": _alarm,
    "alerts": _alert,
}


@dataclass
class Facts:
    """The parsed records of one run, by kind and keyed by (upper-case) ref."""

    windows: dict[str, Window] = field(default_factory=dict)
    events: dict[str, Event] = field(default_factory=dict)
    changes: dict[str, Change] = field(default_factory=dict)
    alarms: dict[str, Alarm] = field(default_factory=dict)
    alerts: dict[str, Alert] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: dict[str, dict[str, Any]]) -> "Facts":
        facts = cls()
        for row in rows.values():
            kind = _kind(row) if isinstance(row, dict) else None
            if kind is None:
                continue
            try:
                parsed = _PARSERS[kind](row)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            getattr(facts, kind)[parsed.ref] = parsed
        return facts
