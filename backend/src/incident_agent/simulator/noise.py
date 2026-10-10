"""Background clutter: harmless alarms, changes and maintenance windows unrelated to scenarios."""

import numpy as np
import pandas as pd

from incident_agent.simulator.drafts import Ctx, ScenarioDraft
from incident_agent.simulator.events import make_ticket
from incident_agent.simulator.topology import AMF_ID, DNS_ID

_BLOCK_PAD = pd.Timedelta(hours=2)


class Blocklist:
    """Per node time windows in which noise must not appear (so labels stay honest)."""

    def __init__(self, drafts: list[ScenarioDraft]) -> None:
        self._windows: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
        for d in drafts:
            for node in d.block_nodes:
                self._windows.setdefault(node, []).append(
                    (d.start - _BLOCK_PAD, d.end + _BLOCK_PAD)
                )

    def blocked(self, node: str, t0: pd.Timestamp, t1: pd.Timestamp) -> bool:
        return any(t0 < b and t1 > a for a, b in self._windows.get(node, []))


_ALARM_KINDS = [
    # type, severity, weight, node kind, flaps (lo, hi), duration minutes (lo, hi), description
    ("TEMP_HIGH", "warning", 0.35, "site", (2, 6), (2, 15), "Cabinet temperature high at {n}"),
    (
        "VSWR_HIGH",
        "minor",
        0.25,
        "site",
        (1, 4),
        (3, 20),
        "VSWR above threshold on sector antenna at {n}",
    ),
    (
        "LINK_DEGRADED",
        "minor",
        0.20,
        "link",
        (1, 3),
        (5, 30),
        "Minor errored seconds on {n}; link still within SLA",
    ),
    ("CPU_HIGH", "warning", 0.10, "agg", (1, 2), (3, 12), "CPU load above 80% on {n}"),
    ("DOOR_OPEN", "warning", 0.05, "site", (1, 1), (5, 40), "Cabinet door open at {n}"),
    ("FAN_FAILURE", "minor", 0.05, "site", (1, 1), (60, 240), "Cooling fan speed low at {n}"),
]

_TUNING = [
    "Antenna tilt adjusted on {n}",
    "Neighbour list update on {n}",
    "Handover threshold tuning on {n}",
    "Paging cycle parameter alignment on {n}",
    "Power control parameter refresh on {n}",
]
_UPGRADES = [
    "Software patch 21.4.2 -> 21.4.3 on {n}",
    "Firmware update of radio unit at {n}",
    "Security hotfix installed on {n}",
]
_MISC = [
    "NTP server list updated on {n}",
    "SNMP community rotation on {n}",
    "Licence file renewed on {n}",
]
_MAINT = [
    ("Battery inspection at {n}", "None expected"),
    ("Antenna and feeder inspection at {n}", "None expected"),
    ("Cabinet cleaning and filter replacement at {n}", "None expected"),
    ("Generator test run at {n}", "None expected"),
    ("Grounding resistance measurement at {n}", "None expected"),
]


def add_background_noise(ctx: Ctx, blocks: Blocklist) -> None:
    rng, axis, log, topo = ctx.rng, ctx.axis, ctx.log, ctx.topo
    sites = list(topo.sites)
    links = sorted(topo.link_sites)
    aggs = sorted(topo.agg_links)
    now = local_now(ctx)
    days = ctx.cfg.days
    weights = np.array([k[2] for k in _ALARM_KINDS])
    weights = weights / weights.sum()

    def minutes(x: float) -> pd.Timedelta:
        return pd.Timedelta(minutes=float(x))

    # Alarm episodes: a node flaps a few times.
    for _ in range(int(rng.poisson(ctx.cfg.alarm_episodes_per_day * days))):
        a_type, sev, _w, nkind, flaps, dur, text = _ALARM_KINDS[
            int(rng.choice(len(_ALARM_KINDS), p=weights))
        ]
        pool = {"site": sites, "link": links, "agg": aggs}[nkind]
        node = pool[int(rng.integers(len(pool)))]
        hour = float(rng.uniform(11, 19)) if a_type == "TEMP_HIGH" else float(rng.uniform(0, 24))
        t = axis.at(int(rng.integers(0, days)), hour)
        for _flap in range(int(rng.integers(flaps[0], flaps[1] + 1))):
            end = t + minutes(rng.uniform(*dur))
            if not blocks.blocked(node, t, end) and t < now:
                cleared = end.floor("min") if end < now else None
                log.alarm(node, a_type, sev, t.floor("min"), cleared, text.format(n=node))
            t = end + minutes(rng.uniform(5, 40))

    # Harmless changes, 1-3 a day.
    core = [DNS_ID, AMF_ID, *sorted(topo.upf_regions)]
    for _ in range(int(rng.poisson(ctx.cfg.changes_per_day * days))):
        roll = float(rng.random())
        if roll < 0.65:
            node = sites[int(rng.integers(len(sites)))]
        elif roll < 0.85:
            node = aggs[int(rng.integers(len(aggs)))]
        else:
            node = core[int(rng.integers(len(core)))]
        c_roll = float(rng.random())
        if c_roll < 0.45:
            ctype, templates = "parameter_tuning", _TUNING
        elif c_roll < 0.80:
            ctype, templates = "software_upgrade", _UPGRADES
        else:
            ctype, templates = "config_push", _MISC
        day = int(rng.integers(0, days))
        hour = (
            float(rng.uniform(1, 5))
            if node in core or ctype == "software_upgrade"
            else float(rng.uniform(8, 17))
        )
        t = axis.at(day, hour) + minutes(rng.uniform(0, 59))
        if blocks.blocked(node, t, t + minutes(1)) or t >= now:
            continue
        desc = templates[int(rng.integers(len(templates)))].format(n=node)
        log.change(node, ctype, t.floor("min"), desc, make_ticket(rng))

    # Planned maintenance with no expected impact; the last ones lie in the future.
    total = ctx.cfg.noise_maintenance_windows + ctx.cfg.future_maintenance_windows
    for i in range(total):
        node = sites[int(rng.integers(len(sites)))]
        future = i >= ctx.cfg.noise_maintenance_windows
        day = days + int(rng.integers(1, 5)) if future else int(rng.integers(0, days))
        t0 = axis.at(day, float(rng.uniform(8, 14)))
        t1 = t0 + minutes(rng.uniform(60, 180))
        if not future and blocks.blocked(node, t0, t1):
            continue
        desc, impact = _MAINT[int(rng.integers(len(_MAINT)))]
        log.maintenance(
            node,
            t0,
            t1.floor("min"),
            desc.format(n=node),
            impact,
            "planned" if future else "completed",
        )


def local_now(ctx: Ctx) -> pd.Timestamp:
    from incident_agent.simulator.timeaxis import local_to_utc

    return local_to_utc(ctx.cfg.now_local, ctx.cfg.utc_offset_hours)
