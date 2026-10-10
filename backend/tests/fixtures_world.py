"""A tiny hand-made World for loader, plotting and migration tests.

It does not depend on the simulator. Window: 4 days at 15-minute steps starting
2026-09-01 00:00 Africa/Tunis (UTC+1). Two regions, five sites, fifteen cells, and one row
(or two) in every event table. Scenarios:

- SCN-001 fiber_cut on LNK-TUN-01-A (sites S-TUN-001/002 down), evidence in alarms
- SCN-002 dns_degradation, nationwide (empty affected list), alarm + DNS core KPIs
- SCN-003 planned_maintenance red herring on S-SFX-001
- SCN-004 stadium_event, affected cell ids, evidence in external_events
- SCN-005 config_push on AGG-TUN-01 (downstream sites through the parent tree), evidence in changes
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from incident_agent.simulator.world import SCHEMA, World

START = datetime(2026, 8, 31, 23, 0, tzinfo=UTC)  # 2026-09-01 00:00 Africa/Tunis
STEPS = 4 * 96
NOW = START + timedelta(days=3, hours=8)


def at(day: int, hour: float) -> datetime:
    """UTC time `hour` hours into day `day` (0-based) of the window, local Tunis clock."""
    return START + timedelta(days=day, hours=hour)


def _frame(table: str, rows: list[tuple[object, ...]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=[c for c, _ in SCHEMA[table]])
    for col, dtype in SCHEMA[table]:
        if dtype in ("ts", "ts?"):
            df[col] = pd.to_datetime(df[col], utc=True)
    return df


def _topology() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    regions = _frame("regions", [("TUN", "Grand Tunis"), ("SFX", "Sfax")])
    site_attrs = {"lat": 36.8, "lon": 10.18, "area_type": "urban", "near_venue": False}
    nodes = _frame(
        "nodes",
        [
            ("CORE-DNS-01", "core_dns", "DNS", None, None, {}),
            ("CORE-AMF-01", "core_amf", "AMF", None, None, {}),
            ("CORE-UPF-01", "core_upf", "UPF 1", None, None, {}),
            ("CORE-UPF-02", "core_upf", "UPF 2", None, None, {}),
            ("AGG-TUN-01", "agg_router", "AGG TUN 01", "TUN", "CORE-UPF-01", {}),
            ("AGG-SFX-01", "agg_router", "AGG SFX 01", "SFX", "CORE-UPF-02", {}),
            ("LNK-TUN-01-A", "transport_link", "Link A", "TUN", "AGG-TUN-01", {"medium": "fiber"}),
            ("LNK-TUN-01-B", "transport_link", "Link B", "TUN", "AGG-TUN-01", {"medium": "fiber"}),
            ("LNK-SFX-01-A", "transport_link", "Link A", "SFX", "AGG-SFX-01", {"medium": "fiber"}),
            ("S-TUN-001", "site", "Tunis 1", "TUN", "LNK-TUN-01-A", site_attrs),
            ("S-TUN-002", "site", "Tunis 2", "TUN", "LNK-TUN-01-A", site_attrs),
            ("S-TUN-003", "site", "Tunis 3", "TUN", "LNK-TUN-01-B", site_attrs),
            ("S-SFX-001", "site", "Sfax 1", "SFX", "LNK-SFX-01-A", site_attrs),
            ("S-SFX-002", "site", "Sfax 2", "SFX", "LNK-SFX-01-A", site_attrs),
        ],
    )
    cell_rows: list[tuple[object, ...]] = []
    for site_id in nodes.loc[nodes["node_type"] == "site", "node_id"]:
        for sector in (1, 2, 3):
            tech = "5G" if sector == 1 else "4G"
            cell_rows.append(
                (
                    f"C-{site_id[2:]}-{sector}",
                    site_id,
                    tech,
                    sector,
                    400.0 if tech == "5G" else 150.0,
                )
            )
    return regions, nodes, _frame("cells", cell_rows)


def _diurnal(ts: pd.DatetimeIndex) -> np.ndarray:
    hour = (ts.tz_convert("Africa/Tunis").hour + ts.minute / 60).to_numpy()
    dist = np.abs(hour - 21.5)
    dist = np.minimum(dist, 24 - dist)
    return 0.35 + 0.65 * np.exp(-(dist**2) / 18)


def _kpis(cells: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    ts = pd.date_range(START, periods=STEPS, freq="15min", tz="UTC")
    n_cells = len(cells)
    base = _diurnal(ts)[None, :] * rng.uniform(0.8, 1.2, size=(n_cells, 1))
    noise = rng.normal(1.0, 0.04, size=(n_cells, STEPS))
    users = 120 * base * noise
    dl = users * 90
    cell_ids = cells["cell_id"].to_numpy()
    site_of = cells["site_id"].to_numpy()
    avail = np.full((n_cells, STEPS), 100.0)

    def window_mask(start: datetime, end: datetime) -> np.ndarray:
        return ((ts >= start) & (ts < end))[None, :]

    # SCN-001: fiber cut, downstream sites of LNK-TUN-01-A are down for 4 hours.
    cut = np.isin(site_of, ["S-TUN-001", "S-TUN-002"])[:, None] & window_mask(at(1, 18), at(1, 22))
    # SCN-003: planned maintenance on S-SFX-001.
    maint = (site_of == "S-SFX-001")[:, None] & window_mask(at(2, 3), at(2, 5))
    # Not a scenario: all of SFX is dark for an hour, so the regional view has nothing to average.
    blackout = np.isin(site_of, ["S-SFX-001", "S-SFX-002"])[:, None] & window_mask(
        at(3, 1), at(3, 2)
    )
    down = cut | maint | blackout
    avail[down] = 0.0
    dl[down] = 0.0
    users[down] = 0.0
    # SCN-004: stadium spike on one cell.
    spike = (cell_ids == "C-TUN-003-1")[:, None] & window_mask(at(2, 19), at(2, 22))
    dl[spike] *= 3
    users[spike] *= 3

    prb = np.clip(dl / 200, 0, 100)
    latency = np.where(down, np.nan, 35 + 60 * np.clip(prb - 70, 0, None) / 30)
    return pd.DataFrame(
        {
            "ts": np.tile(ts.to_numpy(), n_cells),
            "cell_id": np.repeat(cell_ids, STEPS),
            "dl_volume_mb": dl.ravel(),
            "ul_volume_mb": (dl * 0.15).ravel(),
            "active_users": users.ravel(),
            "rrc_success_pct": np.where(down, np.nan, 99.4).ravel(),
            "drop_rate_pct": np.where(down, np.nan, 0.5).ravel(),
            "latency_ms": latency.ravel(),
            "prb_util_pct": prb.ravel(),
            "availability_pct": avail.ravel(),
        }
    ).assign(ts=lambda d: pd.to_datetime(d["ts"], utc=True))


def _core_kpis() -> pd.DataFrame:
    ts = pd.date_range(START, periods=STEPS, freq="15min", tz="UTC")
    degraded = (ts >= at(1, 12)) & (ts < at(1, 14))
    frames = [
        pd.DataFrame(
            {
                "ts": ts,
                "node_id": "CORE-DNS-01",
                "metric": "query_success_pct",
                "value": np.where(degraded, 89.0, 99.9),
            }
        ),
        pd.DataFrame(
            {
                "ts": ts,
                "node_id": "CORE-DNS-01",
                "metric": "resolution_ms",
                "value": np.where(degraded, 120.0, 10.0),
            }
        ),
        pd.DataFrame(
            {"ts": ts, "node_id": "CORE-AMF-01", "metric": "attach_success_pct", "value": 99.5}
        ),
    ]
    return pd.concat(frames, ignore_index=True)


def _scenarios() -> pd.DataFrame:
    def ev(table: str, ident: str) -> dict[str, str]:
        return {"table": table, "id": ident}

    def scenario(
        scenario_id: str, kind: str, day: int, hours: tuple[float, float], **fields: object
    ) -> dict[str, object]:
        start, end = at(day, hours[0]), at(day, hours[1])
        row: dict[str, object] = {
            "scenario_id": scenario_id,
            "kind": kind,
            "is_incident": True,
            "root_cause_category": kind,
            "root_cause_node_id": None,
            "start_at": start,
            "impact_start_at": start,
            "end_at": end,
            "affected_node_ids": [],
            "affected_region_ids": ["TUN"],
            "severity": "medium",
            "difficulty": "easy",
            "evidence": [],
            "expected_tools": ["query_kpis"],
            "questions": [{"text": "Anything unusual?", "asked_at": at(day + 1, 9).isoformat()}],
            "confounders": [],
            "notes": f"fixture {kind}",
        }
        return row | fields

    rows = [
        scenario(
            "SCN-001",
            "fiber_cut",
            1,
            (18, 22),
            root_cause_node_id="LNK-TUN-01-A",
            affected_node_ids=["LNK-TUN-01-A"],
            severity="high",
            evidence=[ev("alarms", "ALM-000001"), ev("alarms", "ALM-000002")],
            expected_tools=["get_alarms", "get_topology", "query_kpis"],
        ),
        scenario(
            "SCN-002",
            "dns_degradation",
            1,
            (12, 14),
            root_cause_category="core_degradation",
            root_cause_node_id="CORE-DNS-01",
            affected_region_ids=["TUN", "SFX"],
            difficulty="hard",
            evidence=[ev("alarms", "ALM-000003")],
            confounders=[{"table": "changes", "id": "CHG-2026-0001", "why": "harmless change"}],
        ),
        scenario(
            "SCN-003",
            "planned_maintenance",
            2,
            (3, 5),
            is_incident=False,
            root_cause_node_id="S-SFX-001",
            affected_node_ids=["S-SFX-001"],
            affected_region_ids=["SFX"],
            severity="low",
            evidence=[ev("maintenance", "MW-0001")],
            expected_tools=["get_maintenance"],
        ),
        scenario(
            "SCN-004",
            "stadium_event",
            2,
            (19, 22),
            is_incident=False,
            root_cause_category="expected_event",
            affected_node_ids=["C-TUN-003-1"],
            severity="low",
            difficulty="medium",
            evidence=[ev("external_events", "EVT-001")],
        ),
        scenario(
            "SCN-005",
            "config_push",
            0,
            (10, 16),
            root_cause_node_id="AGG-TUN-01",
            affected_node_ids=["AGG-TUN-01"],
            difficulty="medium",
            evidence=[ev("changes", "CHG-2026-0002"), ev("changes", "CHG-2026-0003")],
            expected_tools=["get_changes", "query_kpis"],
        ),
    ]
    df = pd.DataFrame(rows)[[c for c, _ in SCHEMA["scenarios"]]]
    for col in ("start_at", "impact_start_at", "end_at"):
        df[col] = pd.to_datetime(df[col], utc=True)
    return df


def make_fixture_world() -> World:
    regions, nodes, cells = _topology()
    alarms = _frame(
        "alarms",
        [
            ("ALM-000001", "LNK-TUN-01-A", "LINK_LOS", "critical", at(1, 18), at(1, 22), "LOS"),
            ("ALM-000002", "S-TUN-001", "SITE_DOWN", "critical", at(1, 18.02), at(1, 22), "down"),
            (
                "ALM-000003",
                "CORE-DNS-01",
                "DNS_TIMEOUT_RATE",
                "major",
                at(1, 12.5),
                None,
                "timeouts",
            ),
        ],
    )
    changes = _frame(
        "changes",
        [
            (
                "CHG-2026-0001",
                "CORE-DNS-01",
                "software_upgrade",
                at(1, 11),
                "patch",
                "T-1",
                "completed",
                None,
            ),
            (
                "CHG-2026-0002",
                "AGG-TUN-01",
                "config_push",
                at(0, 10),
                "qos",
                "T-2",
                "rolled_back",
                None,
            ),
            (
                "CHG-2026-0003",
                "AGG-TUN-01",
                "rollback",
                at(0, 16),
                "revert",
                "T-3",
                "completed",
                "CHG-2026-0002",
            ),
        ],
    )
    maintenance = _frame(
        "maintenance",
        [("MW-0001", "S-SFX-001", at(2, 3), at(2, 5), "battery swap", "site down", "completed")],
    )
    external_events = _frame(
        "external_events",
        [("EVT-001", "TUN", "S-TUN-003", "stadium_event", at(2, 19), at(2, 22), "match at Rades")],
    )
    dataset_meta = _frame(
        "dataset_meta",
        [
            ("seed", "0"),
            ("window_start", START.isoformat()),
            ("window_end", (START + timedelta(days=4)).isoformat()),
            ("now", NOW.isoformat()),
            ("step_minutes", "15"),
            ("version", "fixture"),
        ],
    )
    world = World(
        regions=regions,
        nodes=nodes,
        cells=cells,
        cell_kpis=_kpis(cells),
        core_kpis=_core_kpis(),
        alarms=alarms,
        changes=changes,
        maintenance=maintenance,
        external_events=external_events,
        scenarios=_scenarios(),
        dataset_meta=dataset_meta,
    )
    world.validate()
    return world
