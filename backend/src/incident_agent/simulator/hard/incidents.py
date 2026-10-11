"""Building blocks of the trap scenarios: a clean incident (KPI effect, event rows, draft) that a
trap module then decorates with decoys, extra windows or missing alarms.

The effects follow the ordinary kinds in `simulator.scenarios`; the drafts leave `trap` and
`notes` for the caller.
"""

import math

import numpy as np
import pandas as pd

from incident_agent.simulator.drafts import Ctx, ScenarioDraft
from incident_agent.simulator.events import Handle, make_ticket
from incident_agent.simulator.kpis import ar1
from incident_agent.simulator.scenarios import _jitter, _pick, _profile, _t, _u
from incident_agent.simulator.topology import DNS_ID


def mins(x: float) -> pd.Timedelta:
    return pd.Timedelta(minutes=float(x))


def floor_min(t: pd.Timestamp) -> pd.Timestamp:
    return _t(t)


def uni(ctx: Ctx, lo: float, hi: float) -> float:
    return _u(ctx, lo, hi)


def pick[T](ctx: Ctx, seq: list[T]) -> T:
    return _pick(ctx, seq)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


# ----------------------------------------------------------------------------- transport


def outage_events(
    ctx: Ctx, node: str, sites: list[str], d0: pd.Timestamp, d1: pd.Timestamp, *, link_los: bool
) -> list[Handle]:
    """Sites down from d0 to d1 with SITE_DOWN alarms, and LINK_LOS on `node` when it is a link."""
    ctx.fx.add_down(ctx.topo.cell_rows(sites), ctx.axis.coverage(d0, d1))
    log = ctx.log
    ev: list[Handle] = []
    if link_los:
        ev.append(
            log.alarm(
                node,
                "LINK_LOS",
                "critical",
                d0,
                _t(d1 + mins(uni(ctx, 0, 3))),
                f"Loss of signal on {node}: no light received on uplink port",
            )
        )
    for s in sites:
        ev.append(
            log.alarm(
                s,
                "SITE_DOWN",
                "critical",
                _t(d0 + mins(uni(ctx, 1, 2))),
                _t(d1 + mins(uni(ctx, 1, 5))),
                f"Site {s} unreachable: OAM heartbeat lost",
            )
        )
    return ev


def fiber_cut_draft(
    ctx: Ctx, link: str, t0: pd.Timestamp, t1: pd.Timestamp, *, link_los: bool = True
) -> ScenarioDraft:
    sites = ctx.topo.link_sites[link]
    ev = outage_events(ctx, link, sites, t0, t1, link_los=link_los)
    return ScenarioDraft(
        kind="fiber_cut",
        is_incident=True,
        category="transport_failure",
        root_node=link,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[link, *sites],
        regions=[ctx.topo.link_region[link]],
        severity="high" if len(sites) >= 4 else "medium",
        difficulty="hard",
        evidence=ev,
        expected_tools=["get_alarms", "get_topology", "query_kpis", "get_maintenance"],
        notes="",
        block_nodes=[link, *sites],
        affected_sites=list(sites),
    )


def link_degradation_draft(
    ctx: Ctx, link: str, t0: pd.Timestamp, t1: pd.Timestamp, vol: float, lat: float
) -> ScenarioDraft:
    sites = ctx.topo.link_sites[link]
    rows = ctx.topo.cell_rows(sites)
    n_t = ctx.axis.n_steps
    fade = np.clip(0.85 + 0.12 * ar1(ctx.rng, 1, n_t, 0.8, 1.0)[0], 0.5, 1.0)
    prof = (_profile(ctx, t0, t1, ramp_in=15, ramp_out=15) * fade)[None, :]
    jit = _jitter(ctx, len(rows), 0.9, 1.1)[:, None]
    fx = ctx.fx
    fx.volume_mult[rows] *= 1.0 - vol * jit * prof
    fx.latency_mult[rows] *= 1.0 + lat * jit * prof
    blips = (ctx.rng.random((len(rows), n_t)) < 0.25) & (prof > 0.5)
    fx.add_down(rows, np.where(blips, ctx.rng.uniform(0.01, 0.05, (len(rows), n_t)), 0.0))
    ev = [
        ctx.log.alarm(
            link,
            "LINK_DEGRADED",
            "major",
            _t(t0 + mins(uni(ctx, 1, 5))),
            _t(t1 + mins(uni(ctx, 2, 10))),
            f"Microwave link {link} running at reduced modulation (RSL below threshold)",
        )
    ]
    return ScenarioDraft(
        kind="link_degradation",
        is_incident=True,
        category="transport_degradation",
        root_node=link,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[link, *sites],
        regions=[ctx.topo.link_region[link]],
        severity="medium",
        difficulty="hard",
        evidence=ev,
        expected_tools=["get_alarms", "query_kpis", "get_topology", "search_runbooks"],
        notes="",
        block_nodes=[link, *sites],
        affected_sites=list(sites),
    )


# -------------------------------------------------------------------------------- power


def power_outage_draft(
    ctx: Ctx,
    site: str,
    t0: pd.Timestamp,
    battery: float,
    outage: float,
    *,
    mains: bool = True,
) -> ScenarioDraft:
    t_impact = _t(t0 + mins(battery))
    t_end = _t(t0 + mins(battery + outage))
    ctx.fx.add_down(ctx.topo.cell_rows([site]), ctx.axis.coverage(t_impact, t_end))
    log = ctx.log
    clear = _t(t_end + mins(2))
    ev: list[Handle] = []
    if mains:
        ev.append(
            log.alarm(
                site,
                "MAINS_FAILURE",
                "major",
                t0,
                clear,
                f"AC mains failure at {site}; running on battery",
            )
        )
    ev.append(
        log.alarm(
            site,
            "BATTERY_LOW",
            "major",
            _t(t_impact - mins(15)),
            clear,
            f"Battery voltage low at {site}; autonomy about 15 min",
        )
    )
    ev.append(
        log.alarm(
            site,
            "SITE_DOWN",
            "critical",
            _t(t_impact + mins(uni(ctx, 0, 1))),
            clear,
            f"Site {site} down: power supply exhausted",
        )
    )
    info = ctx.topo.sites[site]
    return ScenarioDraft(
        kind="power_outage",
        is_incident=True,
        category="power_failure",
        root_node=site,
        start=t0,
        impact_start=t_impact,
        end=t_end,
        affected_nodes=[site],
        regions=[info.region_id],
        severity="low" if info.area_type == "rural" else "medium",
        difficulty="hard",
        evidence=ev,
        expected_tools=["get_alarms", "query_kpis", "get_topology", "search_runbooks"],
        notes="",
        block_nodes=[site],
        affected_sites=[site],
    )


# ------------------------------------------------------------------------ configuration


def config_push_draft(
    ctx: Ctx,
    sites: list[str],
    scope: str,
    root: str,
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    *,
    minor_alarms: bool = True,
) -> ScenarioDraft:
    """A regressing change (innocent description) on `root` (a router) or on each of `sites`."""
    rrc, drop, vol = uni(ctx, 3, 7), uni(ctx, 3, 5), uni(ctx, 0.10, 0.30)
    rows = ctx.topo.cell_rows(sites)
    prof = ctx.axis.coverage(t0, t1)[None, :]
    jit = _jitter(ctx, len(rows))[:, None]
    fx = ctx.fx
    fx.rrc_add[rows] -= rrc * jit * prof
    fx.drop_mult[rows] *= 1.0 + (drop - 1.0) * jit * prof
    fx.volume_mult[rows] *= 1.0 - vol * jit * prof
    log = ctx.log
    ctype = pick(ctx, ["config_push", "parameter_tuning"])
    template = pick(ctx, ["RT-2.4", "RT-2.5", "OPT-17", "OPT-21"])
    targets = [root] if scope == "agg" else sorted(sites)
    ticket, rb_ticket = make_ticket(ctx.rng), make_ticket(ctx.rng)
    ev: list[Handle] = []
    for node in targets:
        h = log.change(
            node,
            ctype,
            t0,
            f"Scheduled parameter optimisation batch {template} applied to {node}",
            ticket,
            status="rolled_back",
        )
        rb = log.change(
            node,
            "rollback",
            _t(t1 + mins(uni(ctx, 0, 3))),
            f"Rollback of {template} on {node} after KPI regression escalated by NOC",
            rb_ticket,
            rollback_of=h,
        )
        ev += [h, rb]
    if minor_alarms:
        n_alarm = min(len(sites), pick(ctx, [1, 2]))
        for s in ctx.rng.choice(sorted(sites), size=n_alarm, replace=False):
            ev.append(
                log.alarm(
                    str(s),
                    "RRC_FAILURE_RATE_HIGH",
                    "minor",
                    _t(t0 + mins(uni(ctx, 15, 45))),
                    _t(t1 + mins(uni(ctx, 1, 10))),
                    f"RRC setup failure rate above threshold at {s}",
                )
            )
    return ScenarioDraft(
        kind="config_push",
        is_incident=True,
        category="bad_change",
        root_node=root,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=sorted(sites),
        regions=[ctx.topo.sites[sites[0]].region_id],
        severity="high" if scope == "agg" else "medium",
        difficulty="hard",
        evidence=ev,
        expected_tools=[
            "get_changes",
            "query_kpis",
            "get_alarms",
            "get_topology",
            "search_runbooks",
        ],
        notes="",
        block_nodes=[root, *sites],
        affected_sites=sorted(sites),
    )


# ------------------------------------------------------------------------------- core


def dns_draft(
    ctx: Ctx, t0: pd.Timestamp, t1: pd.Timestamp, *, alarm_delay: float | None
) -> ScenarioDraft:
    lat, vol = uni(ctx, 1.4, 2.2), uni(ctx, 0.18, 0.30)
    success, res = uni(ctx, 85, 93), uni(ctx, 5, 20)
    n_t = ctx.axis.n_steps
    prof = _profile(ctx, t0, t1, ramp_in=5, ramp_out=5) * np.clip(
        0.97 + 0.03 * ctx.rng.standard_normal(n_t), 0.9, 1.0
    )
    jit = _jitter(ctx, len(ctx.topo.cells), 0.9, 1.1)[:, None]
    fx = ctx.fx
    fx.latency_mult *= 1.0 + (lat - 1.0) * jit * prof[None, :]
    fx.volume_mult *= 1.0 - vol * jit * prof[None, :]
    fx.dns_success_sub += (99.9 - success) * prof
    fx.dns_res_mult *= 1.0 + (res - 1.0) * prof
    ev: list[Handle] = []
    if alarm_delay is not None:
        ev.append(
            ctx.log.alarm(
                DNS_ID,
                "DNS_TIMEOUT_RATE",
                "major",
                _t(t0 + mins(alarm_delay)),
                _t(t1 + mins(uni(ctx, 2, 10))),
                "DNS query timeout rate above 5% on CORE-DNS-01",
            )
        )
    return ScenarioDraft(
        kind="dns_degradation",
        is_incident=True,
        category="core_degradation",
        root_node=DNS_ID,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[DNS_ID, *ctx.topo.sites],
        regions=[r.region_id for r in ctx.cfg.regions],
        severity="high",
        difficulty="hard",
        evidence=ev,
        expected_tools=[
            "query_kpis",
            "get_alarms",
            "get_changes",
            "get_topology",
            "search_runbooks",
        ],
        notes="",
        block_nodes=[DNS_ID],
        affected_sites=[],
    )


# ---------------------------------------------------------------------- radio capacity


def evening_util(ctx: Ctx, site: str) -> float:
    rows = ctx.topo.site_cell_rows[site]
    mask = (ctx.axis.local_hour >= 18.5) & (ctx.axis.local_hour <= 21.5)
    util = ctx.base.demand_mbps[rows][:, mask] / ctx.base.cap_mbps[rows][:, None]
    return float(util.mean())


def congestion_draft(
    ctx: Ctx, sites: list[str], t0: pd.Timestamp, t1: pd.Timestamp, users: float, level: float
) -> ScenarioDraft:
    rows = ctx.topo.cell_rows(sites)
    prof = _profile(ctx, t0, t1, ramp_in=10, ramp_out=10)[None, :]
    window = prof[0] > 0
    peak = ctx.base.demand_mbps[rows][:, window].max(axis=1)
    needed = 1.05 * ctx.base.cap_mbps[rows] / np.maximum(peak, 1e-9)
    drawn = users * _jitter(ctx, len(rows), 0.9, 1.1)
    mult = np.clip(np.maximum(drawn, needed), 1.5, 3.2)[:, None]
    fx = ctx.fx
    fx.users_mult[rows] *= 1.0 + (mult - 1.0) * prof
    fx.demand_floor[rows] = np.maximum(fx.demand_floor[rows], level / 100.0 * prof)
    ev = [
        ctx.log.alarm(
            s,
            "HIGH_PRB",
            "warning",
            _t(t0 + mins(uni(ctx, 10, 25))),
            _t(t1 + mins(uni(ctx, 2, 10))),
            f"PRB utilisation above 90% on cells of {s}",
        )
        for s in sites
    ]
    return ScenarioDraft(
        kind="congestion",
        is_incident=True,
        category="capacity",
        root_node=sites[0],
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=list(sites),
        regions=[ctx.topo.sites[sites[0]].region_id],
        severity="medium",
        difficulty="hard",
        evidence=ev,
        expected_tools=[
            "query_kpis",
            "get_alarms",
            "get_topology",
            "get_external_events",
            "get_changes",
            "search_runbooks",
        ],
        notes="",
        block_nodes=list(sites),
        affected_sites=list(sites),
    )


def venue_sites(ctx: Ctx) -> list[str]:
    return [s for s, i in ctx.topo.sites.items() if i.near_venue]


def stadium_draft(
    ctx: Ctx, t0: pd.Timestamp, t1: pd.Timestamp, k: float, description: str, n_alarm: int
) -> ScenarioDraft:
    sites = venue_sites(ctx)
    rows = ctx.topo.cell_rows(sites)
    prof = _profile(ctx, t0, t1, ramp_in=60, ramp_out=30)
    peak = ctx.base.demand_mbps[rows][:, prof > 0].max(axis=1)
    cap = ctx.base.cap_mbps[rows]
    kk = k * _jitter(ctx, len(rows), 0.9, 1.1)
    k_eff = np.maximum(1.3, np.minimum(kk, 0.9 * cap / np.maximum(peak, 1e-9)))
    ctx.fx.users_mult[rows] *= 1.0 + (k_eff[:, None] - 1.0) * prof[None, :]
    log = ctx.log
    ev: list[Handle] = [
        log.external_event("stadium_event", t0, t1, description, ctx.cfg.venue_region, sites[0])
    ]
    for s in sites[:n_alarm]:
        ev.append(
            log.alarm(
                s,
                "HIGH_PRB",
                "warning",
                _t(t0 + mins(uni(ctx, 40, 80))),
                _t(t1 + mins(uni(ctx, 10, 30))),
                f"PRB utilisation above 85% on cells of {s}",
            )
        )
    return ScenarioDraft(
        kind="stadium_event",
        is_incident=False,
        category="expected_event",
        root_node=sites[0],
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=list(sites),
        regions=[ctx.cfg.venue_region],
        severity="low",
        difficulty="hard",
        evidence=ev,
        expected_tools=["query_kpis", "get_alarms", "get_external_events", "get_topology"],
        notes="",
        block_nodes=list(sites),
        affected_sites=list(sites),
    )


# -------------------------------------------------------------------------- maintenance


def maintenance_draft(
    ctx: Ctx,
    node: str,
    sites: list[str],
    t0: pd.Timestamp,
    t_end: pd.Timestamp,
    description: str,
    impact: str,
) -> ScenarioDraft:
    """A fully covered window: the sites go down a few minutes after it starts."""
    d0 = _t(t0 + mins(uni(ctx, 2, 8)))
    d1 = _t(t_end - mins(uni(ctx, 5, 15)))
    is_link = node != sites[0] or len(sites) > 1
    ev: list[Handle] = [ctx.log.maintenance(node, t0, t_end, description, impact, "completed")]
    ev += outage_events(ctx, node, sites, d0, d1, link_los=is_link)
    return ScenarioDraft(
        kind="planned_maintenance",
        is_incident=False,
        category="planned_maintenance",
        root_node=node,
        start=t0,
        impact_start=d0,
        end=t_end,
        affected_nodes=sorted({node, *sites}) if is_link else [node],
        regions=[ctx.topo.sites[sites[0]].region_id],
        severity="low",
        difficulty="hard",
        evidence=ev,
        expected_tools=["get_maintenance", "get_alarms", "query_kpis", "get_changes"],
        notes="",
        block_nodes=sorted({node, *sites}),
        affected_sites=list(sites),
    )


# --------------------------------------------------------------------- harmless changes


def harmless_change(
    ctx: Ctx, node: str, t: pd.Timestamp, ticket: str | None = None
) -> tuple[Handle, str, str]:
    """A routine change on `node` at `t`. Returns (handle, change type, description)."""
    if node.startswith("S-"):
        ctype, desc = pick(
            ctx,
            [
                ("parameter_tuning", f"Handover hysteresis fine-tuning on {node}"),
                ("parameter_tuning", f"Neighbour list refresh on {node}"),
                ("software_upgrade", f"Minor firmware patch on {node} baseband unit"),
            ],
        )
    elif node.startswith("AGG-"):
        ctype, desc = pick(
            ctx,
            [
                ("config_push", f"Routing policy update on {node}"),
                ("software_upgrade", f"Software patch 21.4.2 -> 21.4.3 on {node}"),
            ],
        )
    elif node.startswith("LNK-"):
        ctype, desc = pick(
            ctx,
            [
                ("parameter_tuning", f"Optical port parameter alignment on {node}"),
                ("config_push", f"QoS profile refresh on {node}"),
            ],
        )
    else:
        ctype, desc = "software_upgrade", f"Software patch 21.4.2 -> 21.4.3 on {node}"
    h = ctx.log.change(node, ctype, _t(t), desc, ticket or make_ticket(ctx.rng))
    return h, ctype, desc


def agg_of_link(ctx: Ctx, link: str) -> str:
    return ctx.topo.sites[ctx.topo.link_sites[link][0]].agg_id


def sibling_links(ctx: Ctx, link: str) -> list[str]:
    return [x for x in ctx.topo.agg_links[agg_of_link(ctx, link)] if x != link]


def trap_notes(story: str, trap: str, settled_by: str) -> str:
    """The prose of a trap scenario's notes (the `trap=` prefix is added at build time)."""
    return f"{story} Trap: {trap} Settled by: {settled_by}"


def finish(
    draft: ScenarioDraft,
    trap: str,
    story: str,
    trap_text: str,
    settled_by: str,
    *,
    conf: list[tuple[Handle, str]] | None = None,
    evidence: list[Handle] | None = None,
    block: list[str] | None = None,
) -> ScenarioDraft:
    """Mark a draft as a trap scenario: name, notes, decoys, extra evidence, blocked nodes."""
    draft.trap = trap
    draft.notes = trap_notes(story, trap_text, settled_by)
    draft.confounders += conf or []
    draft.evidence += evidence or []
    draft.block_nodes += block or []
    return draft
