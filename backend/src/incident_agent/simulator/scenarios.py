"""Scenario sampling and injection: one sample/apply pair per kind, registered in SCENARIO_KINDS.

`sample` decides targets, magnitudes and durations (no start time yet, so placement can check
for clashes); `apply` writes the KPI effects and every event row for a chosen start time.

Difficulty conventions:
  easy   - clean evidence trail, alarms within minutes of the root cause.
  medium - evidence is a little slower or noisier (precursors, delayed alarms).
  hard   - a confounder (harmless change or alarm on an affected node shortly before the
           incident) and, for DNS, no alarm at all.
"""

import numpy as np
import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft, ScenarioKind
from incident_agent.simulator.events import Handle, make_ticket
from incident_agent.simulator.kpis import ar1
from incident_agent.simulator.topology import DNS_ID


def _mins(x: float) -> pd.Timedelta:
    return pd.Timedelta(minutes=float(x))


def _t(t: pd.Timestamp) -> pd.Timestamp:
    return t.floor("min")


def _u(ctx: Ctx, lo: float, hi: float) -> float:
    return float(ctx.rng.uniform(lo, hi))


def _pick[T](ctx: Ctx, seq: list[T]) -> T:
    return seq[int(ctx.rng.integers(len(seq)))]


def _pick_diverse(ctx: Ctx, seq: list[str]) -> str:
    """Pick uniformly among the least-used targets so scenarios spread over the network."""
    low = min(ctx.used.get(x, 0) for x in seq)
    choice = _pick(ctx, [x for x in seq if ctx.used.get(x, 0) == low])
    ctx.used[choice] = ctx.used.get(choice, 0) + 1
    return choice


def _regions(ctx: Ctx, sites: list[str]) -> list[str]:
    return sorted({ctx.topo.sites[s].region_id for s in sites})


def _all_sites(ctx: Ctx) -> list[str]:
    return list(ctx.topo.sites)


def _profile(
    ctx: Ctx, t0: pd.Timestamp, t1: pd.Timestamp, ramp_in: float = 0.0, ramp_out: float = 0.0
) -> np.ndarray:
    """Effect strength per step in [0, 1]: exact step coverage, or a trapezoid with ramps."""
    if ramp_in <= 0 and ramp_out <= 0:
        return ctx.axis.coverage(t0, t1)
    step = ctx.axis.step_min
    centre = np.arange(ctx.axis.n_steps) + 0.5
    s, e = ctx.axis.pos(t0), ctx.axis.pos(t1)
    up = np.clip((centre - s) / max(ramp_in / step, 1e-9), 0.0, 1.0)
    down = np.clip((e - centre) / max(ramp_out / step, 1e-9), 0.0, 1.0)
    out: np.ndarray = np.minimum(up, down)
    return out


def _jitter(ctx: Ctx, n: int, lo: float = 0.85, hi: float = 1.15) -> np.ndarray:
    return ctx.rng.uniform(lo, hi, n)


def _confounder(ctx: Ctx, node_id: str, t0: pd.Timestamp) -> tuple[Handle, str]:
    """A harmless change or noise alarm on `node_id` 15-90 minutes before t0."""
    lead = round(_u(ctx, 15, 90))
    t = _t(t0 - _mins(lead))
    is_core = not node_id.startswith("S-")
    if ctx.rng.random() < 0.5 and not is_core:
        change_type, desc = _pick(
            ctx,
            [
                ("software_upgrade", f"Minor firmware patch on {node_id} baseband unit"),
                ("parameter_tuning", f"Neighbour list refresh on {node_id}"),
                ("parameter_tuning", f"Handover hysteresis fine-tuning on {node_id}"),
            ],
        )
        h = ctx.log.change(node_id, change_type, t, desc, make_ticket(ctx.rng))
        why = (
            f"Harmless {change_type} on {node_id} completed {lead} min before the incident; "
            "the KPI impact has a different cause."
        )
    else:
        a_type, sev, desc = (
            ("CPU_HIGH", "warning", f"CPU load above 85% on {node_id}")
            if is_core
            else _pick(
                ctx,
                [
                    ("TEMP_HIGH", "warning", f"Cabinet temperature high at {node_id}"),
                    ("VSWR_HIGH", "minor", f"VSWR above threshold on sector antenna at {node_id}"),
                ],
            )
        )
        h = ctx.log.alarm(node_id, a_type, sev, t, _t(t + _mins(_u(ctx, 8, 30))), desc)
        why = (
            f"Routine {a_type} {sev} alarm on {node_id} {lead} min before the incident; "
            "it cleared by itself and has no KPI impact."
        )
    return h, why


# ----------------------------------------------------------------------------- fiber_cut


def sample_fiber_cut(ctx: Ctx, difficulty: str) -> Params:
    fibre = [lnk for lnk, m in ctx.topo.link_medium.items() if m == "fiber"]
    link = _pick_diverse(ctx, fibre)
    return Params(
        "fiber_cut",
        difficulty,
        _mins(_u(ctx, 120, 480)),
        (0.0, 24.0),
        [ctx.topo.link_region[link]],
        {"link": link},
    )


def apply_fiber_cut(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    sites = ctx.topo.link_sites[link]
    t1 = _t(t0 + p.duration)
    ctx.fx.add_down(ctx.topo.cell_rows(sites), ctx.axis.coverage(t0, t1))
    log = ctx.log
    ev: list[Handle] = []
    if p.difficulty == "medium":
        ev.append(
            log.alarm(
                link,
                "LINK_DEGRADED",
                "minor",
                _t(t0 - _mins(_u(ctx, 20, 60))),
                _t(t0 + _mins(1)),
                f"Optical power dropping on {link} (rx level -24 dBm)",
            )
        )
    ev.append(
        log.alarm(
            link,
            "LINK_LOS",
            "critical",
            t0,
            _t(t1 + _mins(_u(ctx, 0, 3))),
            f"Loss of signal on {link}: no light received on uplink port",
        )
    )
    for s in sites:
        ev.append(
            log.alarm(
                s,
                "SITE_DOWN",
                "critical",
                _t(t0 + _mins(_u(ctx, 1, 2))),
                _t(t1 + _mins(_u(ctx, 1, 5))),
                f"Site {s} unreachable: OAM heartbeat lost",
            )
        )
    conf = []
    if p.difficulty == "hard":
        conf.append(_confounder(ctx, _pick(ctx, sites), t0))
    return ScenarioDraft(
        kind="fiber_cut",
        is_incident=True,
        category="transport_failure",
        root_node=link,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[link, *sites],
        regions=p.regions,
        severity="high" if len(sites) >= 4 else "medium",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["get_alarms", "get_topology", "query_kpis", "search_runbooks"],
        notes=f"Fibre cut on {link}; all {len(sites)} downstream sites lost service until repair.",
        confounders=conf,
        block_nodes=[link, *sites],
        affected_sites=list(sites),
    )


# --------------------------------------------------------------------------- power_outage


def sample_power_outage(ctx: Ctx, difficulty: str) -> Params:
    site = _pick_diverse(ctx, _all_sites(ctx))
    battery = _u(ctx, 60, 240)
    outage = _u(ctx, 60, 300)
    return Params(
        "power_outage",
        difficulty,
        _mins(battery + outage),
        (0.0, 24.0),
        [ctx.topo.sites[site].region_id],
        {"site": site, "battery": battery, "outage": outage},
    )


def apply_power_outage(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    t_impact = _t(t0 + _mins(p.data["battery"]))
    t_end = _t(t0 + p.duration)
    ctx.fx.add_down(ctx.topo.cell_rows([site]), ctx.axis.coverage(t_impact, t_end))
    log = ctx.log
    clear = _t(t_end + _mins(2))
    ev = [
        log.alarm(
            site,
            "MAINS_FAILURE",
            "major",
            t0,
            clear,
            f"AC mains failure at {site}; running on battery",
        ),
        log.alarm(
            site,
            "BATTERY_LOW",
            "major",
            _t(t_impact - _mins(15)),
            clear,
            f"Battery voltage low at {site}; autonomy about 15 min",
        ),
        log.alarm(
            site,
            "SITE_DOWN",
            "critical",
            _t(t_impact + _mins(_u(ctx, 0, 1))),
            clear,
            f"Site {site} down: power supply exhausted",
        ),
    ]
    conf = [_confounder(ctx, site, t0)] if p.difficulty == "hard" else []
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
        regions=p.regions,
        severity="low" if info.area_type == "rural" else "medium",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["get_alarms", "query_kpis", "get_topology", "search_runbooks"],
        notes=(
            f"Mains failure at {site}; battery lasted {p.data['battery'] / 60:.1f} h, so KPIs "
            "were normal until the batteries were exhausted."
        ),
        confounders=conf,
        block_nodes=[site],
        affected_sites=[site],
    )


# ---------------------------------------------------------------------------- config_push


def sample_config_push(ctx: Ctx, difficulty: str) -> Params:
    topo = ctx.topo
    if ctx.rng.random() < 0.5:
        agg = _pick(ctx, sorted(topo.agg_links))
        sites = [s for lnk in topo.agg_links[agg] for s in topo.link_sites[lnk]]
        scope, root, region = "agg", agg, topo.agg_region[agg]
    else:
        link = _pick(ctx, sorted(topo.link_sites))
        sites = list(topo.link_sites[link])
        scope, root, region = "group", sorted(sites)[0], topo.link_region[link]
    return Params(
        "config_push",
        difficulty,
        _mins(_u(ctx, 240, 1440)),
        (9.0, 16.0) if difficulty == "hard" else (1.0, 4.5),
        [region],
        {
            "scope": scope,
            "root": root,
            "sites": sites,
            "rrc": _u(ctx, 3, 7),
            "drop": _u(ctx, 3, 5),
            "vol": _u(ctx, 0.10, 0.30),
        },
    )


def apply_config_push(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    sites: list[str] = p.data["sites"]
    t1 = _t(t0 + p.duration)
    rows = ctx.topo.cell_rows(sites)
    prof = ctx.axis.coverage(t0, t1)[None, :]
    jit = _jitter(ctx, len(rows))[:, None]
    fx = ctx.fx
    fx.rrc_add[rows] -= p.data["rrc"] * jit * prof
    fx.drop_mult[rows] *= 1.0 + (p.data["drop"] - 1.0) * jit * prof
    fx.volume_mult[rows] *= 1.0 - p.data["vol"] * jit * prof

    log = ctx.log
    ctype = (
        "config_push" if p.difficulty == "easy" else _pick(ctx, ["config_push", "parameter_tuning"])
    )
    template = _pick(ctx, ["RT-2.4", "RT-2.5", "OPT-17", "OPT-21"])
    targets = [p.data["root"]] if p.data["scope"] == "agg" else sorted(sites)
    ticket = make_ticket(ctx.rng)
    rb_ticket = make_ticket(ctx.rng)
    ev: list[Handle] = []
    for node in targets:
        if p.difficulty == "hard":
            desc = f"Scheduled parameter optimisation batch {template} applied to {node}"
        else:
            desc = (
                f"Push RAN parameter template {template} to {node} (admission control, RRC timers)"
            )
        h = log.change(node, ctype, t0, desc, ticket, status="rolled_back")
        rb = log.change(
            node,
            "rollback",
            _t(t1 + _mins(_u(ctx, 0, 3))),
            f"Rollback of {template} on {node} after KPI regression escalated by NOC",
            rb_ticket,
            rollback_of=h,
        )
        ev += [h, rb]
    if p.difficulty != "hard":
        for s in ctx.rng.choice(
            sorted(sites), size=min(len(sites), _pick(ctx, [1, 2, 3])), replace=False
        ):
            ev.append(
                log.alarm(
                    str(s),
                    "RRC_FAILURE_RATE_HIGH",
                    "minor",
                    _t(t0 + _mins(_u(ctx, 15, 45))),
                    _t(t1 + _mins(_u(ctx, 1, 10))),
                    f"RRC setup failure rate above threshold at {s}",
                )
            )
    conf = [_confounder(ctx, _pick(ctx, sorted(sites)), t0)] if p.difficulty == "hard" else []
    root: str = p.data["root"]
    return ScenarioDraft(
        kind="config_push",
        is_incident=True,
        category="bad_change",
        root_node=root,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=sorted(sites),
        regions=p.regions,
        severity="high" if p.data["scope"] == "agg" else "medium",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=[
            "get_changes",
            "query_kpis",
            "get_alarms",
            "get_topology",
            "search_runbooks",
        ],
        notes=(
            f"Change {template} pushed to "
            f"{'the aggregation router' if p.data['scope'] == 'agg' else 'a group of sites'} "
            f"({root}) regressed RRC success and drop rate until it was rolled back. "
            + (
                "Root cause node is the first site of the pushed group."
                if p.data["scope"] == "group"
                else ""
            )
        ),
        confounders=conf,
        block_nodes=[root, *sites],
        affected_sites=sorted(sites),
    )


# ------------------------------------------------------------------------ dns_degradation


def sample_dns_degradation(ctx: Ctx, difficulty: str) -> Params:
    delay = {"easy": _u(ctx, 1, 4), "medium": _u(ctx, 10, 25)}.get(difficulty)
    return Params(
        "dns_degradation",
        difficulty,
        _mins(_u(ctx, 60, 180)),
        (9.0, 19.0),
        [r.region_id for r in ctx.cfg.regions],
        {
            "lat": _u(ctx, 1.4, 2.2),
            "vol": _u(ctx, 0.18, 0.30),
            "success": _u(ctx, 85, 93),
            "res": _u(ctx, 5, 20),
            "alarm_delay": delay,
        },
    )


def apply_dns_degradation(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    t1 = _t(t0 + p.duration)
    n_t = ctx.axis.n_steps
    prof = _profile(ctx, t0, t1, ramp_in=5, ramp_out=5) * np.clip(
        0.97 + 0.03 * ctx.rng.standard_normal(n_t), 0.9, 1.0
    )
    n_c = len(ctx.topo.cells)
    jit = _jitter(ctx, n_c, 0.9, 1.1)[:, None]
    fx = ctx.fx
    fx.latency_mult *= 1.0 + (p.data["lat"] - 1.0) * jit * prof[None, :]
    fx.volume_mult *= 1.0 - p.data["vol"] * jit * prof[None, :]
    fx.dns_success_sub += (99.9 - p.data["success"]) * prof
    fx.dns_res_mult *= 1.0 + (p.data["res"] - 1.0) * prof
    log = ctx.log
    ev: list[Handle] = []
    if p.data["alarm_delay"] is not None:
        ev.append(
            log.alarm(
                DNS_ID,
                "DNS_TIMEOUT_RATE",
                "major",
                _t(t0 + _mins(p.data["alarm_delay"])),
                _t(t1 + _mins(_u(ctx, 2, 10))),
                "DNS query timeout rate above 5% on CORE-DNS-01",
            )
        )
    conf = []
    if p.difficulty == "hard":
        conf.append(_confounder(ctx, DNS_ID, t0))
    sites = _all_sites(ctx)
    note = (
        "CORE-DNS-01 degraded: query success dropped and resolution time multiplied. "
        f"Applied nationwide: latency x{p.data['lat']:.2f}, DL volume -{p.data['vol'] * 100:.0f}%."
    )
    if p.data["alarm_delay"] is None:
        note += " No alarm was raised; the evidence is only in core_kpis."
    return ScenarioDraft(
        kind="dns_degradation",
        is_incident=True,
        category="core_degradation",
        root_node=DNS_ID,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[DNS_ID, *sites],
        regions=p.regions,
        severity="high",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["query_kpis", "get_alarms", "get_topology", "search_runbooks"],
        notes=note,
        confounders=conf,
        block_nodes=[DNS_ID],
        affected_sites=[],
    )


# ----------------------------------------------------------------------------- congestion


def _evening_util(ctx: Ctx, site: str) -> float:
    rows = ctx.topo.site_cell_rows[site]
    mask = (ctx.axis.local_hour >= 18.5) & (ctx.axis.local_hour <= 21.5)
    util = ctx.base.demand_mbps[rows][:, mask] / ctx.base.cap_mbps[rows][:, None]
    return float(util.mean())


def sample_congestion(ctx: Ctx, difficulty: str) -> Params:
    topo = ctx.topo
    cand = [s for s, i in topo.sites.items() if i.area_type != "rural" and not i.near_venue]
    cand.sort(key=lambda s: -_evening_util(ctx, s))
    anchor = _pick(ctx, cand[:10])
    region = topo.sites[anchor].region_id
    same = [s for s in cand if topo.sites[s].region_id == region and s != anchor]
    k = {"easy": 1, "medium": 2, "hard": 2}[difficulty]
    sites = sorted([anchor, *same[: k - 1]])
    return Params(
        "congestion",
        difficulty,
        _mins(_u(ctx, 60, 240)),
        (16.5, 20.5),
        [region],
        {"sites": sites, "users": _u(ctx, 1.5, 2.5), "level": _u(ctx, 95, 100)},
    )


def apply_congestion(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    sites: list[str] = p.data["sites"]
    t1 = _t(t0 + p.duration)
    rows = ctx.topo.cell_rows(sites)
    prof = _profile(ctx, t0, t1, ramp_in=10, ramp_out=10)[None, :]
    window = prof[0] > 0
    peak = ctx.base.demand_mbps[rows][:, window].max(axis=1)
    needed = 1.05 * ctx.base.cap_mbps[rows] / np.maximum(peak, 1e-9)
    drawn = p.data["users"] * _jitter(ctx, len(rows), 0.9, 1.1)
    mult = np.clip(np.maximum(drawn, needed), 1.5, 3.2)[:, None]
    fx = ctx.fx
    fx.users_mult[rows] *= 1.0 + (mult - 1.0) * prof
    fx.demand_floor[rows] = np.maximum(fx.demand_floor[rows], p.data["level"] / 100.0 * prof)
    log = ctx.log
    ev = [
        log.alarm(
            s,
            "HIGH_PRB",
            "warning",
            _t(t0 + _mins(_u(ctx, 10, 25))),
            _t(t1 + _mins(_u(ctx, 2, 10))),
            f"PRB utilisation above 90% on cells of {s}",
        )
        for s in sites
    ]
    conf = []
    if p.difficulty == "hard":
        node = _pick(ctx, sites)
        lead = round(_u(ctx, 15, 90))
        h = log.change(
            node,
            "parameter_tuning",
            _t(t0 - _mins(lead)),
            f"Scheduler weight tuning on {node}",
            make_ticket(ctx.rng),
        )
        conf.append(
            (
                h,
                f"Harmless scheduler parameter tuning on {node} {lead} min before the "
                "congestion; the cause is a demand surge, not this change.",
            )
        )
    return ScenarioDraft(
        kind="congestion",
        is_incident=True,
        category="capacity",
        root_node=sites[0],
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=list(sites),
        regions=p.regions,
        severity="medium",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=[
            "query_kpis",
            "get_alarms",
            "get_topology",
            "get_external_events",
            "search_runbooks",
        ],
        notes=(
            "Demand surge saturated the radio resources of "
            f"{', '.join(sites)}; there was no external event to explain it."
        ),
        confounders=conf,
        block_nodes=list(sites),
        affected_sites=list(sites),
    )


# ------------------------------------------------------------------------ link_degradation


def sample_link_degradation(ctx: Ctx, difficulty: str) -> Params:
    mw = [lnk for lnk, m in ctx.topo.link_medium.items() if m == "microwave"]
    link = _pick_diverse(ctx, mw)
    return Params(
        "link_degradation",
        difficulty,
        _mins(_u(ctx, 60, 360)),
        (0.0, 24.0),
        [ctx.topo.link_region[link]],
        {"link": link, "vol": _u(ctx, 0.20, 0.50), "lat": _u(ctx, 0.3, 1.0)},
    )


def apply_link_degradation(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    sites = ctx.topo.link_sites[link]
    t1 = _t(t0 + p.duration)
    rows = ctx.topo.cell_rows(sites)
    n_t = ctx.axis.n_steps
    fade = np.clip(0.85 + 0.12 * ar1(ctx.rng, 1, n_t, 0.8, 1.0)[0], 0.5, 1.0)
    prof = (_profile(ctx, t0, t1, ramp_in=15, ramp_out=15) * fade)[None, :]
    jit = _jitter(ctx, len(rows), 0.9, 1.1)[:, None]
    fx = ctx.fx
    fx.volume_mult[rows] *= 1.0 - p.data["vol"] * jit * prof
    fx.latency_mult[rows] *= 1.0 + p.data["lat"] * jit * prof
    blips = (ctx.rng.random((len(rows), n_t)) < 0.25) & (prof > 0.5)
    fx.add_down(rows, np.where(blips, ctx.rng.uniform(0.01, 0.05, (len(rows), n_t)), 0.0))
    ev = [
        ctx.log.alarm(
            link,
            "LINK_DEGRADED",
            "major",
            _t(t0 + _mins(_u(ctx, 1, 5))),
            _t(t1 + _mins(_u(ctx, 2, 10))),
            f"Microwave link {link} running at reduced modulation (RSL below threshold)",
        )
    ]
    conf = [_confounder(ctx, _pick(ctx, sites), t0)] if p.difficulty == "hard" else []
    return ScenarioDraft(
        kind="link_degradation",
        is_incident=True,
        category="transport_degradation",
        root_node=link,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=[link, *sites],
        regions=p.regions,
        severity="medium",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["get_alarms", "query_kpis", "get_topology", "search_runbooks"],
        notes=f"Rain fade on microwave link {link}: throughput limited, sites stayed up.",
        confounders=conf,
        block_nodes=[link, *sites],
        affected_sites=list(sites),
    )


# ----------------------------------------------------------------------- planned_maintenance


def sample_planned_maintenance(ctx: Ctx, difficulty: str) -> Params:
    topo = ctx.topo
    if difficulty == "easy":
        node = _pick_diverse(ctx, _all_sites(ctx))
        sites, region = [node], topo.sites[node].region_id
    else:
        fibre = [lnk for lnk, m in topo.link_medium.items() if m == "fiber"]
        node = _pick_diverse(ctx, fibre)
        sites, region = list(topo.link_sites[node]), topo.link_region[node]
    return Params(
        "planned_maintenance",
        difficulty,
        _mins(_u(ctx, 120, 240)),
        (1.0, 3.5),
        [region],
        {"node": node, "sites": sites},
    )


def apply_planned_maintenance(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    node: str = p.data["node"]
    sites: list[str] = p.data["sites"]
    t_end = _t(t0 + p.duration)
    d0 = _t(t0 + _mins(_u(ctx, 2, 8)))
    d1 = _t(t_end - _mins(_u(ctx, 5, 15)))
    ctx.fx.add_down(ctx.topo.cell_rows(sites), ctx.axis.coverage(d0, d1))
    log = ctx.log
    if p.difficulty == "easy":
        desc, impact = (
            f"Planned battery replacement and cabinet inspection at {node}",
            "Site offline for the duration of the works",
        )
    elif p.difficulty == "medium":
        desc, impact = (
            f"Planned fibre splice work on {node}",
            "Downstream sites offline during splicing",
        )
    else:
        desc, impact = "Routine transport network works", "Possible short service interruptions"
    ev: list[Handle] = [log.maintenance(node, t0, t_end, desc, impact, "completed")]
    if node != sites[0] or len(sites) > 1:
        ev.append(
            log.alarm(
                node,
                "LINK_LOS",
                "critical",
                d0,
                _t(d1 + _mins(1)),
                f"Loss of signal on {node}: no light received on uplink port",
            )
        )
    for s in sites:
        ev.append(
            log.alarm(
                s,
                "SITE_DOWN",
                "critical",
                _t(d0 + _mins(_u(ctx, 1, 2))),
                _t(d1 + _mins(_u(ctx, 1, 3))),
                f"Site {s} unreachable: OAM heartbeat lost",
            )
        )
    return ScenarioDraft(
        kind="planned_maintenance",
        is_incident=False,
        category="planned_maintenance",
        root_node=node,
        start=t0,
        impact_start=d0,
        end=t_end,
        affected_nodes=sorted({node, *sites}) if node != sites[0] else [node],
        regions=p.regions,
        severity="low",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["get_maintenance", "get_alarms", "query_kpis"],
        notes=f"Sites went down inside the maintenance window on {node}; not an incident.",
        block_nodes=sorted({node, *sites}),
        affected_sites=list(sites),
    )


# --------------------------------------------------------------------------- stadium_event


def sample_stadium_event(ctx: Ctx, difficulty: str) -> Params:
    sites = [s for s, i in ctx.topo.sites.items() if i.near_venue]
    return Params(
        "stadium_event",
        difficulty,
        _mins(_u(ctx, 180, 240)),
        (18.0, 19.5),
        [ctx.cfg.venue_region],
        {"sites": sites, "k": _u(ctx, 2.0, 3.5)},
    )


def apply_stadium_event(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    sites: list[str] = p.data["sites"]
    t1 = _t(t0 + p.duration)
    rows = ctx.topo.cell_rows(sites)
    prof = _profile(ctx, t0, t1, ramp_in=60, ramp_out=30)
    window = prof > 0
    peak = ctx.base.demand_mbps[rows][:, window].max(axis=1)
    cap = ctx.base.cap_mbps[rows]
    k = p.data["k"] * _jitter(ctx, len(rows), 0.9, 1.1)
    k_eff = np.maximum(1.3, np.minimum(k, 0.9 * cap / np.maximum(peak, 1e-9)))
    ctx.fx.users_mult[rows] *= 1.0 + (k_eff[:, None] - 1.0) * prof[None, :]
    desc = {
        "easy": "Football match at Stade Olympique de Rades (expected attendance 40,000)",
        "medium": "Concert at Stade Olympique de Rades",
        "hard": "Event at Rades Olympic complex",
    }[p.difficulty]
    log = ctx.log
    ev: list[Handle] = [
        log.external_event("stadium_event", t0, t1, desc, ctx.cfg.venue_region, sites[0])
    ]
    n_alarm = min(len(sites), _pick(ctx, [1, 2, 3]))
    for s in sites[:n_alarm]:
        ev.append(
            log.alarm(
                s,
                "HIGH_PRB",
                "warning",
                _t(t0 + _mins(_u(ctx, 40, 80))),
                _t(t1 + _mins(_u(ctx, 10, 30))),
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
        regions=p.regions,
        severity="low",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["query_kpis", "get_alarms", "get_external_events"],
        notes="Traffic surge around the stadium caused by a scheduled event; not an incident.",
        block_nodes=list(sites),
        affected_sites=list(sites),
    )


# -------------------------------------------------------------------------- public_holiday


def sample_public_holiday(ctx: Ctx, difficulty: str) -> Params:
    return Params(
        "public_holiday",
        difficulty,
        pd.Timedelta(days=1),
        (0.0, 0.0),
        [r.region_id for r in ctx.cfg.regions],
        {},
        whole_day=True,
        weekday_only=True,
    )


def apply_public_holiday(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    t1 = t0 + p.duration
    day = ctx.axis.coverage(t0, t1)[None, :]
    h = ctx.axis.local_hour
    business = np.exp(-0.5 * ((h - 13.0) / 4.5) ** 2)[None, :]
    area = np.array(ctx.base.cell_area)[:, None]
    drop, boost = ctx.cfg.holiday_urban_drop, ctx.cfg.holiday_residential_boost
    factor = np.where(
        area == "urban",
        1.0 - drop * (0.35 + 0.65 * business),
        1.0 + boost * (0.5 + 0.5 * business),
    )
    ctx.fx.users_mult *= 1.0 + (factor - 1.0) * day
    ev: list[Handle] = [
        ctx.log.external_event(
            "public_holiday",
            t0,
            t1,
            "National public holiday: government offices and most businesses closed",
        )
    ]
    return ScenarioDraft(
        kind="public_holiday",
        is_incident=False,
        category="expected_event",
        root_node=None,
        start=t0,
        impact_start=t0,
        end=t1,
        affected_nodes=_all_sites(ctx),
        regions=p.regions,
        severity="low",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["query_kpis", "get_external_events"],
        notes="Nationwide public holiday: business-area traffic down, residential up.",
        block_nodes=[],
        affected_sites=[],
    )


# ----------------------------------------------------------------------------- alarm_storm

_STORM_TYPES: list[tuple[str, str, str]] = [
    ("TEMP_HIGH", "warning", "Cabinet temperature high at {s}"),
    ("VSWR_HIGH", "minor", "VSWR above threshold on sector antenna at {s}"),
    ("DOOR_OPEN", "warning", "Cabinet door open at {s}"),
    ("FAN_FAILURE", "minor", "Cooling fan speed low at {s}"),
    ("RECTIFIER_FAULT", "minor", "Rectifier module fault at {s}"),
]


def sample_alarm_storm(ctx: Ctx, difficulty: str) -> Params:
    sites = _all_sites(ctx)
    if difficulty == "hard":
        sites = [s for s in sites if ctx.topo.sites[s].area_type == "urban"]
    site = _pick_diverse(ctx, sites)
    n = {"easy": _u(ctx, 20, 25), "medium": _u(ctx, 25, 33), "hard": _u(ctx, 36, 48)}[difficulty]
    return Params(
        "alarm_storm",
        difficulty,
        _mins(70),
        (0.0, 24.0),
        [ctx.topo.sites[site].region_id],
        {"site": site, "n": int(n)},
    )


def apply_alarm_storm(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    offs = np.sort(ctx.rng.uniform(0, 60, p.data["n"]))
    pool = _STORM_TYPES[:2] if p.difficulty == "easy" else _STORM_TYPES
    ev: list[Handle] = []
    for off in offs:
        a_type, sev, text = _pick(ctx, pool)
        raised = _t(t0 + _mins(float(off)))
        ev.append(
            ctx.log.alarm(
                site, a_type, sev, raised, _t(raised + _mins(_u(ctx, 1, 6))), text.format(s=site)
            )
        )
    return ScenarioDraft(
        kind="alarm_storm",
        is_incident=False,
        category="no_impact",
        root_node=site,
        start=t0,
        impact_start=t0,
        end=_t(t0 + p.duration),
        affected_nodes=[],
        regions=p.regions,
        severity="low",
        difficulty=p.difficulty,
        evidence=ev,
        expected_tools=["get_alarms", "query_kpis"],
        notes=f"{site} raised {p.data['n']} minor/warning alarms in an hour with no KPI impact.",
        block_nodes=[site],
        affected_sites=[site],
    )


SCENARIO_KINDS: dict[str, ScenarioKind] = {
    k.name: k
    for k in [
        ScenarioKind("fiber_cut", True, sample_fiber_cut, apply_fiber_cut),
        ScenarioKind("power_outage", True, sample_power_outage, apply_power_outage),
        ScenarioKind("config_push", True, sample_config_push, apply_config_push),
        ScenarioKind("dns_degradation", True, sample_dns_degradation, apply_dns_degradation),
        ScenarioKind("congestion", True, sample_congestion, apply_congestion),
        ScenarioKind("link_degradation", True, sample_link_degradation, apply_link_degradation),
        ScenarioKind(
            "planned_maintenance", False, sample_planned_maintenance, apply_planned_maintenance
        ),
        ScenarioKind("stadium_event", False, sample_stadium_event, apply_stadium_event),
        ScenarioKind("public_holiday", False, sample_public_holiday, apply_public_holiday),
        ScenarioKind("alarm_storm", False, sample_alarm_storm, apply_alarm_storm),
    ]
}
