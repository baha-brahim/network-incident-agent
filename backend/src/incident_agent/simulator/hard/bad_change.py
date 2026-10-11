"""Trap `bad_change_loud_coincidence`: a real configuration regression with an innocent change
record, while a louder unrelated signal overlaps in time."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.events import Handle
from incident_agent.simulator.hard.incidents import (
    agg_of_link,
    config_push_draft,
    finish,
    mins,
    outage_events,
    pick,
    sibling_links,
    stadium_draft,
    uni,
)
from incident_agent.simulator.scenarios import _pick, _pick_diverse, _t

TRAP = "bad_change_loud_coincidence"


def sample_bad_change(ctx: Ctx, difficulty: str, variant: str) -> Params:
    topo = ctx.topo
    links = sorted(topo.link_sites)
    other: str | None = None
    if variant == "maint_sibling":
        eligible = [
            x for x in links if any(topo.link_medium[y] == "fiber" for y in sibling_links(ctx, x))
        ]
    elif variant == "stadium_region":
        eligible = [
            x
            for x in links
            if topo.link_region[x] == ctx.cfg.venue_region
            and not any(topo.sites[s].near_venue for s in topo.link_sites[x])
        ]
    else:
        eligible = links
    link = _pick_diverse(ctx, eligible)
    if variant == "maint_sibling":
        other = _pick(ctx, [y for y in sibling_links(ctx, link) if topo.link_medium[y] == "fiber"])
    return Params(
        "config_push",
        difficulty,
        mins(uni(ctx, 360, 900)),
        (17.5, 19.5) if variant == "stadium_region" else (9.0, 16.0),
        [topo.link_region[link]],
        {"variant": variant, "link": link, "other": other},
    )


def _maintenance_on_sibling(
    ctx: Ctx, other: str, t0: pd.Timestamp
) -> tuple[list[tuple[Handle, str]], list[str]]:
    sites = ctx.topo.link_sites[other]
    w0 = _t(t0 + mins(uni(ctx, 40, 90)))
    w1 = _t(w0 + mins(uni(ctx, 120, 200)))
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
        sites,
        _t(w0 + mins(uni(ctx, 2, 8))),
        _t(w1 - mins(uni(ctx, 5, 15))),
        link_los=True,
    )
    conf = [
        (
            mw,
            f"A real, fully covered maintenance window on the sibling link {other} overlaps the "
            "regression; it explains the outage of that link's sites and nothing else.",
        ),
        (ev[0], f"LINK_LOS on {other} raised by the planned works, on a different link."),
    ]
    return conf, [other, *sites]


def _flapping_alarms(ctx: Ctx, link: str, t0: pd.Timestamp) -> list[tuple[Handle, str]]:
    out: list[tuple[Handle, str]] = []
    t = t0 - mins(uni(ctx, 10, 30))
    for _ in range(3):
        end = t + mins(uni(ctx, 6, 14))
        h = ctx.log.alarm(
            link,
            "LINK_DEGRADED",
            "major",
            _t(t),
            _t(end),
            f"Optical receive power fluctuating on {link}",
        )
        out.append(
            (
                h,
                f"A major LINK_DEGRADED alarm on {link}, the parent of the pushed sites, "
                "flapped and cleared by itself within minutes while the regression went on for "
                "hours; availability and volume were not affected by it.",
            )
        )
        t = end + mins(uni(ctx, 10, 25))
    return out


def apply_bad_change(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    variant: str = p.data["variant"]
    link: str = p.data["link"]
    topo = ctx.topo
    sites = list(topo.link_sites[link])
    root = sorted(sites)[0]
    d = config_push_draft(ctx, sites, "group", root, t0, _t(t0 + p.duration))
    story = (
        f"A scheduled parameter optimisation batch pushed to the {len(sites)} sites of {link} "
        "regressed RRC success and drop rate until it was rolled back. Root cause node is the "
        "first site of the pushed group."
    )
    block = [link, agg_of_link(ctx, link)]
    if variant == "maint_sibling":
        other: str = p.data["other"]
        conf, extra = _maintenance_on_sibling(ctx, other, t0)
        return finish(
            d,
            TRAP,
            story,
            "the change record looks innocent, and a louder, unrelated planned-maintenance "
            f"outage on the sibling link {other} overlaps in time and draws the attention.",
            "(1) the regression starts at the change time, before the maintenance window "
            f"opens, on exactly the pushed sites, which keep 100 % availability while the "
            f"sites of {other} are down; (2) it carries on after the window closes and ends at "
            "the rollback.",
            conf=conf,
            block=[*block, *extra],
        )
    if variant == "flapping_link":
        return finish(
            d,
            TRAP,
            story,
            f"a major alarm on {link}, the parent of the pushed sites, flaps around the onset "
            "and clears by itself, and the change record looks innocent.",
            "(1) the alarm clears within minutes while the KPI regression goes on for hours, "
            "and availability stays at 100 %; (2) the regression starts at the change time on "
            "exactly the pushed sites and ends at the rollback; (3) the sites of the sibling "
            "links are normal.",
            conf=_flapping_alarms(ctx, link, t0),
            block=block,
        )
    # A stadium event in the same region the same evening.
    te = _t(t0 + mins(uni(ctx, -45, 30)))
    stadium = stadium_draft(
        ctx,
        te,
        _t(te + mins(uni(ctx, 180, 240))),
        uni(ctx, 2.0, 3.5),
        "Football match at Stade Olympique de Rades (expected attendance 40,000)",
        pick(ctx, [1, 2, 3]),
    )
    event, *venue_alarms = stadium.evidence
    return finish(
        d,
        TRAP,
        story,
        "a stadium event in the same region the same evening makes traffic and alarms "
        "noisy, and the change record looks innocent.",
        "(1) the stadium event raises traffic at the venue sites, whereas the pushed sites "
        "are other sites that lose RRC success and volume; (2) the regression starts at the "
        "change time on exactly the pushed sites and ends at the rollback, long after the "
        "event.",
        conf=[
            (
                event,
                "A real stadium event in the same region and evening; it explains the traffic "
                "surge at the venue sites, not the regression on the pushed sites.",
            ),
            *[(a, "HIGH_PRB at a venue site, caused by the event.") for a in venue_alarms[:1]],
        ],
        block=[*block, *stadium.block_nodes],
    )
