"""Traps on a stadium day: `congestion_on_match_day` (a real congestion far from the venue) and
`expected_event_looks_like_fault` (a real event whose venue sites raise scary alarms)."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.hard.incidents import (
    congestion_draft,
    evening_util,
    finish,
    haversine_km,
    mins,
    pick,
    stadium_draft,
    uni,
    venue_sites,
)
from incident_agent.simulator.scenarios import _pick_diverse, _t

TRAP_CONGESTION = "congestion_on_match_day"
TRAP_VENUE = "expected_event_looks_like_fault"
MATCH = "Football match at Stade Olympique de Rades (expected attendance 40,000)"


def sample_match_day(ctx: Ctx, difficulty: str) -> Params:
    topo = ctx.topo
    venue = venue_sites(ctx)
    venue_links = {topo.sites[s].link_id for s in venue}

    def km_to_venue(site: str) -> float:
        a = topo.sites[site]
        return min(haversine_km(a.lat, a.lon, topo.sites[v].lat, topo.sites[v].lon) for v in venue)

    cand = [
        s
        for s, i in topo.sites.items()
        if i.region_id == ctx.cfg.venue_region
        and not i.near_venue
        and i.link_id not in venue_links
        and i.area_type != "rural"
        and km_to_venue(s) >= 6.0
    ]
    cand.sort(key=lambda s: -evening_util(ctx, s))
    site = _pick_diverse(ctx, cand[:6])
    cong, off, ev_len = uni(ctx, 90, 240), uni(ctx, -20, 30), uni(ctx, 180, 240)
    return Params(
        "congestion",
        difficulty,
        mins(max(cong, off + ev_len) + 10),
        (17.0, 19.0),
        [ctx.cfg.venue_region],
        {
            "site": site,
            "cong": cong,
            "event_off": off,
            "event_len": ev_len,
            "k": uni(ctx, 2.0, 3.5),
            "users": uni(ctx, 1.5, 2.5),
            "level": uni(ctx, 95, 100),
        },
    )


def apply_match_day(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    info = ctx.topo.sites[site]
    km = min(
        haversine_km(info.lat, info.lon, ctx.topo.sites[v].lat, ctx.topo.sites[v].lon)
        for v in venue_sites(ctx)
    )
    te = _t(t0 + mins(p.data["event_off"]))
    stadium = stadium_draft(ctx, te, _t(te + mins(p.data["event_len"])), p.data["k"], MATCH, 2)
    event, *venue_alarms = stadium.evidence
    d = congestion_draft(
        ctx, [site], t0, _t(t0 + mins(p.data["cong"])), p.data["users"], p.data["level"]
    )
    return finish(
        d,
        TRAP_CONGESTION,
        f"Demand surge saturated the radio resources of {site}, {km:.0f} km from the stadium; "
        "the match is real but is not the cause.",
        f"a stadium event is on the calendar for the region and the evening, so a hasty "
        f"investigator calls the congestion at {site} expected.",
        f"(1) {site} is not a venue site (near_venue is false, about {km:.0f} km away, under "
        f"{info.link_id} while the venue sites hang under other links), and the event record "
        "names the venue; (2) latency and drop rate at the site are far worse than at the "
        "venue sites, whose extra capacity keeps them mild; (3) the runbook says an event far "
        "from the saturated site does not explain it.",
        conf=[
            (
                event,
                f"A real stadium event the same evening in the same region, but its venue is "
                f"about {km:.0f} km from {site}; it explains the venue sites, not this site.",
            ),
            *[(a, "HIGH_PRB at a venue site, caused by the event.") for a in venue_alarms[:1]],
        ],
        block=stadium.block_nodes,
    )


def sample_venue_noise(ctx: Ctx, difficulty: str) -> Params:
    n = ctx.used.get("venue_noise", 0)
    ctx.used["venue_noise"] = n + 1
    ev_len = uni(ctx, 180, 240)
    return Params(
        "stadium_event",
        difficulty,
        mins(ev_len + 60),
        (18.0, 19.5),
        [ctx.cfg.venue_region],
        {"event_len": ev_len, "k": uni(ctx, 2.0, 3.5), "n": n},
    )


_NOISE = [
    ("RECTIFIER_FAULT", "Rectifier module fault at {s}"),
    ("VSWR_HIGH", "VSWR above threshold on sector antenna at {s}"),
]


def apply_venue_noise(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    sites = venue_sites(ctx)
    d = stadium_draft(ctx, t0, _t(t0 + mins(p.data["event_len"])), p.data["k"], MATCH, len(sites))
    site = sites[p.data["n"] % len(sites)]
    a_type, text = _NOISE[p.data["n"] % len(_NOISE)]
    conf = []
    t = t0 + mins(uni(ctx, 40, 100))
    for _ in range(pick(ctx, [1, 2])):
        end = t + mins(uni(ctx, 6, 14))
        h = ctx.log.alarm(site, a_type, "major", _t(t), _t(end), text.format(s=site))
        conf.append(
            (
                h,
                f"A major {a_type} alarm at the venue site {site} that cleared by itself within "
                "minutes; availability and quality KPIs were not affected.",
            )
        )
        t = end + mins(uni(ctx, 10, 25))
    return finish(
        d,
        TRAP_VENUE,
        "Traffic surge around the stadium caused by a scheduled event; not an incident.",
        f"every venue site raises HIGH_PRB and {site} also raises a major {a_type} alarm "
        "that clears by itself, so the venue looks faulty.",
        "(1) availability stays at 100 % and RRC success and drop rate stay normal at all "
        "venue sites; (2) the major alarm clears within minutes and moves no KPI; (3) the "
        "external event covers the region, the evening and the venue sites, and extra traffic "
        "with high PRB is what the event explains.",
        conf=conf,
    )
