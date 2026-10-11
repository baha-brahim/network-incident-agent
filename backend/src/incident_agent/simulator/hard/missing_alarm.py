"""Trap `missing_alarm`: a real outage whose characteristic alarm was never raised."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.hard.incidents import (
    fiber_cut_draft,
    finish,
    mins,
    power_outage_draft,
    uni,
)
from incident_agent.simulator.scenarios import _pick_diverse, _t

TRAP = "missing_alarm"


def sample_missing_fiber(ctx: Ctx, difficulty: str) -> Params:
    # Three sites or more: with two, "independent site faults" would be a fair reading.
    eligible = [
        x
        for x, m in ctx.topo.link_medium.items()
        if m == "fiber" and len(ctx.topo.link_sites[x]) >= 3
    ]
    link = _pick_diverse(ctx, eligible)
    return Params(
        "fiber_cut",
        difficulty,
        mins(uni(ctx, 120, 300)),
        (0.0, 24.0),
        [ctx.topo.link_region[link]],
        {"link": link},
    )


def apply_missing_fiber(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    d = fiber_cut_draft(ctx, link, t0, _t(t0 + p.duration), link_los=False)
    n = len(d.affected_sites)
    return finish(
        d,
        TRAP,
        f"Fibre cut on {link}; all {n} downstream sites lost service until repair. The "
        "LINK_LOS alarm was never raised: only SITE_DOWN alarms on the sites exist.",
        f"there is no alarm on {link}, only {n} SITE_DOWN alarms on sites, so a hasty "
        "investigator names a site or a set of independent site faults.",
        f"get_topology shows that the {n} sites share the parent {link} and that nothing else "
        "hangs under it; they went down in the same minute and sites on sibling links stayed "
        "up, so the shared link is the one cause.",
    )


def sample_missing_power(ctx: Ctx, difficulty: str) -> Params:
    site = _pick_diverse(ctx, list(ctx.topo.sites))
    battery, outage = uni(ctx, 60, 180), uni(ctx, 60, 240)
    return Params(
        "power_outage",
        difficulty,
        mins(battery + outage),
        (0.0, 24.0),
        [ctx.topo.sites[site].region_id],
        {"site": site, "battery": battery, "outage": outage},
    )


def apply_missing_power(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    d = power_outage_draft(ctx, site, t0, p.data["battery"], p.data["outage"], mains=False)
    return finish(
        d,
        TRAP,
        f"Mains failure at {site}; battery lasted {p.data['battery'] / 60:.1f} h, so KPIs were "
        "normal until the batteries were exhausted. The MAINS_FAILURE alarm was never raised: "
        "BATTERY_LOW and SITE_DOWN exist.",
        f"there is no MAINS_FAILURE alarm, only BATTERY_LOW and SITE_DOWN on {site}, so a "
        "hasty investigator reports an unexplained site outage or a hardware fault.",
        f"BATTERY_LOW on {site} precedes SITE_DOWN by about 15 minutes, which is the end of "
        "the battery autonomy; only this one site is down while its siblings, its link and its "
        "router are healthy and there is no LINK_LOS; the KPIs were normal until the site died.",
    )
