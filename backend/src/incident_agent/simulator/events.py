"""Collects alarms/changes/maintenance/external events and assigns IDs in time order at the end.

Scenarios and noise refer to rows through opaque handles, because the final IDs are only
known once every row exists and is sorted by time.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from incident_agent.simulator.frames import rows_to_frame

Handle = tuple[str, int]  # (table, index in insertion order)


@dataclass(frozen=True)
class FinalEvents:
    alarms: pd.DataFrame
    changes: pd.DataFrame
    maintenance: pd.DataFrame
    external_events: pd.DataFrame
    ids: dict[Handle, str]


def make_ticket(rng: np.random.Generator) -> str:
    return f"TKT-{int(rng.integers(10000, 99999))}"


class EventLog:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, Any]]] = {
            "alarms": [],
            "changes": [],
            "maintenance": [],
            "external_events": [],
        }

    def _add(self, table: str, row: dict[str, Any]) -> Handle:
        self._rows[table].append(row)
        return (table, len(self._rows[table]) - 1)

    def alarm(
        self,
        node_id: str,
        alarm_type: str,
        severity: str,
        raised_at: pd.Timestamp,
        cleared_at: pd.Timestamp | None,
        description: str,
    ) -> Handle:
        return self._add(
            "alarms",
            {
                "node_id": node_id,
                "alarm_type": alarm_type,
                "severity": severity,
                "raised_at": raised_at,
                "cleared_at": cleared_at,
                "description": description,
            },
        )

    def change(
        self,
        node_id: str,
        change_type: str,
        executed_at: pd.Timestamp,
        description: str,
        ticket: str,
        status: str = "completed",
        rollback_of: Handle | None = None,
    ) -> Handle:
        return self._add(
            "changes",
            {
                "node_id": node_id,
                "change_type": change_type,
                "executed_at": executed_at,
                "description": description,
                "ticket": ticket,
                "status": status,
                "rollback_of": rollback_of,
            },
        )

    def set_status(self, handle: Handle, status: str) -> None:
        self._rows[handle[0]][handle[1]]["status"] = status

    def maintenance(
        self,
        node_id: str,
        start_at: pd.Timestamp,
        end_at: pd.Timestamp,
        description: str,
        expected_impact: str,
        status: str = "completed",
    ) -> Handle:
        return self._add(
            "maintenance",
            {
                "node_id": node_id,
                "start_at": start_at,
                "end_at": end_at,
                "description": description,
                "expected_impact": expected_impact,
                "status": status,
            },
        )

    def external_event(
        self,
        event_type: str,
        start_at: pd.Timestamp,
        end_at: pd.Timestamp,
        description: str,
        region_id: str | None = None,
        node_id: str | None = None,
    ) -> Handle:
        return self._add(
            "external_events",
            {
                "region_id": region_id,
                "node_id": node_id,
                "event_type": event_type,
                "start_at": start_at,
                "end_at": end_at,
                "description": description,
            },
        )

    def finalize(self) -> FinalEvents:
        time_col = {
            "alarms": "raised_at",
            "changes": "executed_at",
            "maintenance": "start_at",
            "external_events": "start_at",
        }
        id_col = {
            "alarms": ("alarm_id", "ALM-{:06d}"),
            "changes": ("change_id", "CHG-2026-{:04d}"),
            "maintenance": ("mw_id", "MW-{:04d}"),
            "external_events": ("event_id", "EVT-{:03d}"),
        }
        ids: dict[Handle, str] = {}
        for table, rows in self._rows.items():
            order = sorted(range(len(rows)), key=lambda i: (rows[i][time_col[table]], i))
            fmt = id_col[table][1]
            for rank, i in enumerate(order, start=1):
                ids[(table, i)] = fmt.format(rank)
        frames: dict[str, pd.DataFrame] = {}
        for table, rows in self._rows.items():
            out_rows: list[dict[str, Any]] = []
            order = sorted(range(len(rows)), key=lambda i: (rows[i][time_col[table]], i))
            for i in order:
                row = dict(rows[i])
                row[id_col[table][0]] = ids[(table, i)]
                if table == "changes" and row["rollback_of"] is not None:
                    row["rollback_of"] = ids[row["rollback_of"]]
                out_rows.append(row)
            frames[table] = rows_to_frame(table, out_rows)
        return FinalEvents(
            alarms=frames["alarms"],
            changes=frames["changes"],
            maintenance=frames["maintenance"],
            external_events=frames["external_events"],
            ids=ids,
        )
