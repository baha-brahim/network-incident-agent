"""Trap `near_miss_maintenance`: a real outage that looks covered by the maintenance calendar but
is not."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.hard.incidents import (
    agg_of_link,
    fiber_cut_draft,
    finish,
    mins,
    outage_events,
    power_outage_draft,
    sibling_links,
    uni,
)
from incident_agent.simulator.scenarios import _pick, _pick_diverse, _t

TRAP = "near_miss_maintenance"


def sample_near_miss(ctx: Ctx, difficulty: str, variant: str) -> Params:
    topo = ctx.topo
    fibre = [x for x, m in topo.link_medium.items() if m == "fiber"]
    if variant == "none_expected_power":
        site = _pick_diverse(ctx, list(topo.sites))
        battery, outage = uni(ctx, 60, 150), uni(ctx, 90, 240)
        return Params(
            "power_outage",
            difficulty,
            mins(battery + outage + 60),
            (0.0, 24.0),
            [topo.sites[site].region_id],
            {"variant": variant, "site": site, "battery": battery, "outage": outage},
        )
    if variant == "other_link":
        eligible = [
            x for x in fibre if any(topo.link_medium[y] == "fiber" for y in sibling_links(ctx, x))
        ]
        link = _pick_diverse(ctx, eligible)
        other = _pick(ctx, [y for y in sibling_links(ctx, link) if topo.link_medium[y] == "fiber"])
        cut, w_off, w_len = uni(ctx, 150, 300), uni(ctx, -30, 30), uni(ctx, 150, 240)
        return Params(
            "fiber_cut",
            difficulty,
            mins(max(cut, w_off + w_len) + 10),
            (0.0, 24.0),
            [topo.link_region[link]],
            {
                "variant": variant,
                "link": link,
                "other": other,
                "cut": cut,
                "w_off": w_off,
                "w_len": w_len,
            },
        )
    link = _pick_diverse(ctx, fibre)
    if variant == "starts_before":
        total = uni(ctx, 270, 420)
    elif variant == "overrun":
        w_len, over = uni(ctx, 120, 180), uni(ctx, 150, 240)
        return Params(
            "fiber_cut",
            difficulty,
            mins(w_len + over + 10),
            (0.0, 24.0),
            [topo.link_region[link]],
            {"variant": variant, "link": link, "w_len": w_len, "over": over},
        )
    else:  # none_expected_fiber
        total = uni(ctx, 150, 300) + 60
    return Params(
        "fiber_cut",
        difficulty,
        mins(total),
        (0.0, 24.0),
        [topo.link_region[link]],
        {"variant": variant, "link": link, "total": total},
    )


def _other_link(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link, other = p.data["link"], p.data["other"]
    t1 = _t(t0 + mins(p.data["cut"]))
    d = fiber_cut_draft(ctx, link, t0, t1)
    osites = ctx.topo.link_sites[other]
    w0 = _t(t0 + mins(p.data["w_off"]))
    w1 = _t(w0 + mins(p.data["w_len"]))
    mw = ctx.log.maintenance(
        other,
        w0,
        w1,
        f"Planned fibre splice work on {other}",
        "Downstream sites offline during splicing",
        "completed",
    )
    ev = outage_events(
        ctx,
        other,
        osites,
        _t(w0 + mins(uni(ctx, 2, 8))),
        _t(w1 - mins(uni(ctx, 5, 15))),
        link_los=True,
    )
    return finish(
        d,
        TRAP,
        f"Fibre cut on {link}; all {len(d.affected_sites)} downstream sites lost service until "
        "repair.",
        f"a maintenance window for the same hours exists on {other}, another link under the "
        f"same router ({agg_of_link(ctx, link)}), and its own outage raises the same alarms.",
        f"(1) the window is on {other}, not on {link}, its sites or the router above; "
        f"(2) the sites that lost service are the children of {link}, not of {other}; "
        f"(3) the outage of {link} starts at its own LINK_LOS and does not follow the window.",
        conf=[
            (mw, f"A real window, but on {other}: it covers that link's outage, not {link}."),
            (ev[0], f"LINK_LOS on {other} raised by its planned works."),
        ],
        block=[other, *osites, agg_of_link(ctx, link)],
    )


def _starts_before(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    t1 = _t(t0 + mins(p.data["total"]))
    d = fiber_cut_draft(ctx, link, t0, t1)
    gap = uni(ctx, 70, 110)
    w0 = _t(t0 + mins(gap))
    w1 = _t(t1 - mins(uni(ctx, 0, 5)))
    mw = ctx.log.maintenance(
        link,
        w0,
        w1,
        f"Planned fibre splice work on {link}",
        "Downstream sites offline during splicing",
        "completed",
    )
    return finish(
        d,
        TRAP,
        f"Fibre cut on {link}; all {len(d.affected_sites)} downstream sites lost service until "
        f"repair. The maintenance window opened {gap:.0f} min after the cut, so the first "
        f"{gap:.0f} min of the outage are outside it and only the repair period is inside.",
        f"a splice window on the right link covers the end of the outage ({link}), but the "
        "outage started well before it opened.",
        f"(1) LINK_LOS and SITE_DOWN were raised, and the sites were down, {gap:.0f} min before "
        "the window starts, which fails the time test of the maintenance runbook; (2) the "
        "window closes when service returns, so it describes the repair, not the cause.",
        conf=[
            (
                mw,
                f"A window on {link} that opens {gap:.0f} min after the outage began; it covers "
                "only the repair, not the start of the outage.",
            )
        ],
    )


def _overrun(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    w1 = _t(t0 + mins(p.data["w_len"]))
    t1 = _t(w1 + mins(p.data["over"]))
    d = fiber_cut_draft(ctx, link, _t(t0 + mins(uni(ctx, 2, 8))), t1)
    mw = ctx.log.maintenance(
        link,
        t0,
        w1,
        f"Planned fibre splice work on {link}",
        "Downstream sites offline during splicing",
        "completed",
    )
    over = (t1 - w1) / pd.Timedelta(minutes=1)
    return finish(
        d,
        TRAP,
        f"The sites of {link} went down inside the maintenance window on {link} and stayed down "
        f"{over:.0f} min after it closed: the part inside the window is planned work, the "
        "remainder is an unplanned outage and is labelled an incident.",
        f"a splice window on the right link covers the start of the outage ({link}), but the "
        "outage runs hours past its end.",
        f"(1) the outage continues {over:.0f} min after the window ends, which fails the time "
        "test of the maintenance runbook; (2) LINK_LOS and SITE_DOWN stay active after the "
        "window closed instead of clearing with the end of the works.",
        conf=[
            (
                mw,
                f"A window on {link} that ended {over:.0f} min before service returned; it "
                "explains only the first part of the outage.",
            )
        ],
    )


def _none_expected_fiber(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    t1 = _t(t0 + mins(p.data["total"] - 60))
    d = fiber_cut_draft(ctx, link, t0, t1)
    mw = ctx.log.maintenance(
        link,
        _t(t0 - mins(uni(ctx, 10, 30))),
        _t(t1 + mins(uni(ctx, 10, 40))),
        f"Optical power level measurements on {link}",
        "None expected (measurement only)",
        "completed",
    )
    return finish(
        d,
        TRAP,
        f"Fibre cut on {link}; all {len(d.affected_sites)} downstream sites lost service until "
        "repair. The window on the link covers the whole outage in time but announces no "
        "impact.",
        f"a maintenance window on {link} covers the whole outage in time and scope, so a "
        "hasty investigator calls it planned.",
        "the window's expected impact says none (measurement only), so it fails the nature "
        "test of the maintenance runbook: measurements do not take downstream sites off the "
        "air.",
        conf=[
            (
                mw,
                f"A window on {link} covering the outage, but for measurements with no expected "
                "impact.",
            )
        ],
    )


def _none_expected_power(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    battery, outage = p.data["battery"], p.data["outage"]
    d = power_outage_draft(ctx, site, t0, battery, outage)
    w0 = _t(d.impact_start - mins(uni(ctx, 20, 50)))
    w1 = _t(d.end + mins(uni(ctx, 10, 40)))
    mw = ctx.log.maintenance(
        site, w0, w1, f"Battery inspection at {site}", "None expected", "completed"
    )
    return finish(
        d,
        TRAP,
        f"Mains failure at {site}; battery lasted {battery / 60:.1f} h, so KPIs were normal "
        "until the batteries were exhausted. The maintenance window on "
        f"{site} covers the time the site was down but announces no impact, and the mains "
        "failure began "
        f"{(w0 - t0) / pd.Timedelta(minutes=1):.0f} min before it opened.",
        f"a maintenance window on {site} covers the whole time the site was down, so a hasty "
        "investigator calls it planned.",
        "(1) the window's expected impact says none, so it fails the nature test; (2) "
        "MAINS_FAILURE was raised well before the window opened and BATTERY_LOW followed "
        "before SITE_DOWN, which is the power sequence, not an inspection.",
        conf=[
            (
                mw,
                f"A window on {site} covering the outage in time, but an inspection with no "
                "expected impact; the mains failure preceded it.",
            )
        ],
    )


def apply_near_miss(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    return {
        "other_link": _other_link,
        "starts_before": _starts_before,
        "overrun": _overrun,
        "none_expected_fiber": _none_expected_fiber,
        "none_expected_power": _none_expected_power,
    }[p.data["variant"]](ctx, p, t0)
