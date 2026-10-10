"""The data contract between the simulator (produces a World) and the DB loader (consumes it).

Each table is a pandas DataFrame whose columns match SCHEMA exactly, in that order.
Timestamps are tz-aware UTC. The DB schema (Alembic migration 0002) mirrors this file.
"""

from dataclasses import dataclass, fields
from typing import Literal

import pandas as pd

Dtype = Literal["str", "str?", "float", "float?", "int", "bool", "ts", "ts?", "str[]", "json"]

# table -> ordered (column, dtype). "?" = nullable; "str[]" = list[str]; "json" = dict/list.
SCHEMA: dict[str, list[tuple[str, Dtype]]] = {
    "regions": [
        ("region_id", "str"),  # TUN, SAH, SFX, SUD
        ("name", "str"),
    ],
    "nodes": [
        ("node_id", "str"),  # CORE-DNS-01, CORE-UPF-01, AGG-TUN-01, LNK-TUN-01-A, S-TUN-001
        ("node_type", "str"),  # core_dns | core_upf | core_amf | agg_router | transport_link | site
        ("name", "str"),
        ("region_id", "str?"),  # null for core nodes
        ("parent_id", "str?"),  # dependency tree: site -> link -> agg -> upf; null for core
        ("attrs", "json"),  # site: lat, lon, area_type, near_venue; link: medium (fiber|microwave)
    ],
    "cells": [
        ("cell_id", "str"),  # C-TUN-001-1
        ("site_id", "str"),
        ("technology", "str"),  # 4G | 5G
        ("sector", "int"),  # 1..3
        ("capacity_mbps", "float"),
    ],
    # One row per cell per 15-minute step. The three quality KPIs are null (NaN in pandas) while
    # a cell is fully down (availability 0): a dead cell reports no measurements.
    "cell_kpis": [
        ("ts", "ts"),
        ("cell_id", "str"),
        ("dl_volume_mb", "float"),
        ("ul_volume_mb", "float"),
        ("active_users", "float"),
        ("rrc_success_pct", "float?"),
        ("drop_rate_pct", "float?"),
        ("latency_ms", "float?"),
        ("prb_util_pct", "float"),
        ("availability_pct", "float"),
    ],
    "core_kpis": [  # long format, one row per node per metric per step
        ("ts", "ts"),
        ("node_id", "str"),
        ("metric", "str"),  # dns: query_success_pct, resolution_ms; upf: throughput_gbps,
        ("value", "float"),  # session_count; amf: attach_success_pct
    ],
    "alarms": [
        ("alarm_id", "str"),  # ALM-000123
        ("node_id", "str"),
        ("alarm_type", "str"),  # LINK_LOS, LINK_DEGRADED, MAINS_FAILURE, BATTERY_LOW, SITE_DOWN,
        ("severity", "str"),  # HIGH_PRB, DNS_TIMEOUT_RATE, TEMP_HIGH, VSWR_HIGH, ...
        ("raised_at", "ts"),  # severity: critical | major | minor | warning
        ("cleared_at", "ts?"),
        ("description", "str"),
    ],
    "changes": [
        ("change_id", "str"),  # CHG-2026-0412
        ("node_id", "str"),
        ("change_type", "str"),  # config_push | software_upgrade | parameter_tuning | rollback ...
        ("executed_at", "ts"),
        ("description", "str"),
        ("ticket", "str"),
        ("status", "str"),  # completed | rolled_back
        ("rollback_of", "str?"),  # change_id this one reverts
    ],
    "maintenance": [
        ("mw_id", "str"),  # MW-0042
        ("node_id", "str"),
        ("start_at", "ts"),
        ("end_at", "ts"),
        ("description", "str"),
        ("expected_impact", "str"),
        ("status", "str"),  # planned | completed
    ],
    "external_events": [
        ("event_id", "str"),  # EVT-007
        ("region_id", "str?"),  # null = nationwide
        ("node_id", "str?"),  # e.g. nearest site to a venue
        ("event_type", "str"),  # stadium_event | public_holiday | festival
        ("start_at", "ts"),
        ("end_at", "ts"),
        ("description", "str"),
    ],
    # Ground truth. Loaded into the `gt` schema, which the agent's DB role can't read.
    "scenarios": [
        ("scenario_id", "str"),  # SCN-001
        ("kind", "str"),  # fiber_cut | power_outage | config_push | dns_degradation |
        # congestion | link_degradation | planned_maintenance | stadium_event |
        # public_holiday | alarm_storm
        ("is_incident", "bool"),  # false for red herrings
        ("root_cause_category", "str"),
        ("root_cause_node_id", "str?"),
        ("start_at", "ts"),  # when the root cause happened (may precede KPI impact)
        ("impact_start_at", "ts"),
        ("end_at", "ts"),
        ("affected_node_ids", "str[]"),  # sites/cells/links whose KPIs moved
        ("affected_region_ids", "str[]"),
        ("severity", "str"),  # low | medium | high
        ("difficulty", "str"),  # easy | medium | hard
        ("evidence", "json"),  # [{"table": "alarms", "id": "ALM-000123"}, ...]
        ("expected_tools", "str[]"),
        ("questions", "json"),  # [{"text": "Why did traffic drop in Sfax last night?",
        #                          "asked_at": "2026-09-14T08:00:00+00:00"}]
        ("confounders", "json"),  # [{"table": "changes", "id": ..., "why": ...}]
        ("notes", "str"),
    ],
    "dataset_meta": [
        ("key", "str"),  # seed, window_start, window_end, now, step_minutes, version
        ("value", "str"),
    ],
}


@dataclass(frozen=True)
class World:
    regions: pd.DataFrame
    nodes: pd.DataFrame
    cells: pd.DataFrame
    cell_kpis: pd.DataFrame
    core_kpis: pd.DataFrame
    alarms: pd.DataFrame
    changes: pd.DataFrame
    maintenance: pd.DataFrame
    external_events: pd.DataFrame
    scenarios: pd.DataFrame
    dataset_meta: pd.DataFrame

    def tables(self) -> dict[str, pd.DataFrame]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def validate(self) -> None:
        """Raise ValueError if any table's columns differ from SCHEMA (names and order)."""
        for name, df in self.tables().items():
            expected = [col for col, _ in SCHEMA[name]]
            if list(df.columns) != expected:
                raise ValueError(f"{name}: columns {list(df.columns)} != {expected}")
            for col, dtype in SCHEMA[name]:
                if dtype in ("ts", "ts?") and len(df) and str(df[col].dt.tz) != "UTC":
                    raise ValueError(f"{name}.{col} must be tz-aware UTC")
