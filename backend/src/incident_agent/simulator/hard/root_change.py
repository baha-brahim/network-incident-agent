"""Trap `change_on_root_node`: a real fault of another kind, with a harmless change on the failed
node itself or on its parent a little before the onset."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.events import Handle, make_ticket
from incident_agent.simulator.hard.incidents import (
    agg_of_link,
    congestion_draft,
    dns_draft,
    evening_util,
    fiber_cut_draft,
    finish,
    harmless_change,
    link_degradation_draft,
    mins,
    power_outage_draft,
    sibling_links,
    uni,
)
from incident_agent.simulator.scenarios import _pick, _pick_diverse, _t
from incident_agent.simulator.topology import AMF_ID, DNS_ID

TRAP = "change_on_root_node"


def sample_root_change(ctx: Ctx, difficulty: str, variant: str) -> Params:
    topo = ctx.topo
    lead = round(uni(ctx, 20, 90))
    if variant.startswith("dns_upgrade"):
        return Params(
            "dns_degradation",
            difficulty,
            mins(uni(ctx, 60, 180)),
            (9.0, 19.0),
            [r.region_id for r in ctx.cfg.regions],
            {
                "variant": variant,
                "lead": round(uni(ctx, 35, 90)),
                "alarm_delay": None if variant.endswith("silent") else uni(ctx, 8, 25),
            },
        )
    if variant == "power_param":
        site = _pick_diverse(ctx, list(topo.sites))
        battery, outage = uni(ctx, 60, 180), uni(ctx, 60, 240)
        return Params(
            "power_outage",
            difficulty,
            mins(battery + outage),
            (0.0, 24.0),
            [topo.sites[site].region_id],
            {"variant": variant, "lead": lead, "site": site, "battery": battery, "outage": outage},
        )
    if variant == "fiber_router":
        link = _pick_diverse(ctx, [x for x, m in topo.link_medium.items() if m == "fiber"])
        return Params(
            "fiber_cut",
            difficulty,
            mins(uni(ctx, 120, 300)),
            (0.0, 24.0),
            [topo.link_region[link]],
            {"variant": variant, "lead": lead, "link": link},
        )
    if variant == "linkdeg_router":
        link = _pick_diverse(ctx, [x for x, m in topo.link_medium.items() if m == "microwave"])
        return Params(
            "link_degradation",
            difficulty,
            mins(uni(ctx, 90, 360)),
            (0.0, 24.0),
            [topo.link_region[link]],
            {
                "variant": variant,
                "lead": lead,
                "link": link,
                "vol": uni(ctx, 0.20, 0.50),
                "lat": uni(ctx, 0.3, 1.0),
            },
        )
    if variant == "congestion_batch":
        cand = [
            s
            for s, i in topo.sites.items()
            if i.area_type != "rural" and not i.near_venue and len(topo.link_sites[i.link_id]) >= 3
        ]
        cand.sort(key=lambda s: -evening_util(ctx, s))
        site = _pick(ctx, cand[:10])
        return Params(
            "congestion",
            difficulty,
            mins(uni(ctx, 90, 240)),
            (16.5, 20.5),
            [topo.sites[site].region_id],
            {
                "variant": variant,
                "lead": lead,
                "site": site,
                "users": uni(ctx, 1.5, 2.5),
                "level": uni(ctx, 95, 100),
            },
        )
    raise ValueError(variant)


def _dns(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    lead: int = p.data["lead"]
    t1 = _t(t0 + p.duration)
    d = dns_draft(ctx, t0, t1, alarm_delay=p.data["alarm_delay"])
    tc = _t(t0 - mins(lead))
    ticket = make_ticket(ctx.rng)
    text = "Software patch 21.4.2 -> 21.4.3 on {n} (resolver service restart)"
    h = ctx.log.change(DNS_ID, "software_upgrade", tc, text.format(n=DNS_ID), ticket)
    upf = sorted(ctx.topo.upf_regions)[0]
    controls: list[Handle] = [
        ctx.log.change(
            n,
            "software_upgrade",
            _t(tc + mins(uni(ctx, 1, 4))),
            text.format(n=n).replace(" (resolver service restart)", " (service restart)"),
            ticket,
        )
        for n in (AMF_ID, upf)
    ]
    silent = p.data["alarm_delay"] is None
    return finish(
        d,
        TRAP,
        "CORE-DNS-01 degraded for about "
        f"{p.duration / pd.Timedelta(minutes=1):.0f} min; nationwide latency up, volume down, "
        "RRC unaffected."
        + (" No alarm was raised; the evidence is in core_kpis." if silent else ""),
        f"a software upgrade on CORE-DNS-01 itself ran {lead} min before the onset, so a hasty "
        "investigator blames the change.",
        f"(1) the DNS and RRC KPIs were normal for {lead} min after the upgrade, while a "
        "configuration change takes effect at once; (2) the same patch under the same ticket went "
        f"onto {AMF_ID} and {upf} at the same time and both stayed healthy; (3) the degradation "
        "ended by itself, with no rollback or other change at the recovery.",
        conf=[
            (
                h,
                f"Harmless software_upgrade on {DNS_ID} completed {lead} min before the "
                "degradation; the DNS KPIs stayed normal until the onset and the same patch on "
                "other core nodes did nothing.",
            )
        ],
        evidence=controls,
        block=[AMF_ID, upf],
    )


def _power(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    lead: int = p.data["lead"]
    d = power_outage_draft(ctx, site, t0, p.data["battery"], p.data["outage"])
    tc = _t(t0 - mins(lead))
    ticket = make_ticket(ctx.rng)
    desc = f"Handover hysteresis fine-tuning on {site}"
    h = ctx.log.change(site, "parameter_tuning", tc, desc, ticket)
    link = ctx.topo.sites[site].link_id
    sibs = [s for s in sorted(ctx.topo.link_sites[link]) if s != site][:2]
    controls = [
        ctx.log.change(
            s,
            "parameter_tuning",
            _t(tc + mins(uni(ctx, 0, 3))),
            f"Handover hysteresis fine-tuning on {s}",
            ticket,
        )
        for s in sibs
    ]
    return finish(
        d,
        TRAP,
        f"Mains failure at {site}; the batteries lasted {p.data['battery'] / 60:.1f} h, so the "
        "KPIs stayed normal until they were exhausted.",
        f"a parameter change on {site} itself ran {lead} min before the mains failure, so a "
        "hasty investigator blames it for the site going down.",
        "(1) MAINS_FAILURE (major) and later BATTERY_LOW precede the SITE_DOWN, which is the "
        "power sequence, and a parameter change cannot cut the mains; (2) the KPIs were normal "
        "for hours after the change; (3) the same tuning went onto "
        f"{', '.join(sibs) or 'no other site'} under the same ticket and they stayed up.",
        conf=[
            (
                h,
                f"Harmless parameter_tuning on {site} {lead} min before the mains failure; the "
                "site went down hours later, when the batteries ran out, and neighbours with the "
                "same change were unaffected.",
            )
        ],
        evidence=controls,
        block=[link, *sibs],
    )


def _fiber(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    lead: int = p.data["lead"]
    d = fiber_cut_draft(ctx, link, t0, _t(t0 + p.duration))
    agg = agg_of_link(ctx, link)
    h, ctype, _ = harmless_change(ctx, agg, t0 - mins(lead))
    sibs = sibling_links(ctx, link)
    return finish(
        d,
        TRAP,
        f"Fibre cut on {link}; all {len(d.affected_sites)} downstream sites lost service until "
        "repair.",
        f"a {ctype} on {agg}, the router above the link, ran {lead} min before the cut, so a "
        "hasty investigator blames the router change.",
        f"(1) LINK_LOS (no light, critical) on {link} is a physical fault that no router change "
        f"explains; (2) only the sites of {link} went down while the sites of "
        f"{', '.join(sibs)}, under the same router, stayed at 100 % availability; (3) the KPIs "
        "were normal between the change and the cut.",
        conf=[
            (
                h,
                f"Harmless {ctype} on {agg} {lead} min before the cut; the sibling links under "
                "the same router were unaffected.",
            )
        ],
        block=[agg],
    )


def _linkdeg(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    link: str = p.data["link"]
    lead: int = p.data["lead"]
    d = link_degradation_draft(ctx, link, t0, _t(t0 + p.duration), p.data["vol"], p.data["lat"])
    agg = agg_of_link(ctx, link)
    h, ctype, _ = harmless_change(ctx, agg, t0 - mins(lead))
    sibs = sibling_links(ctx, link)
    return finish(
        d,
        TRAP,
        f"Rain fade on microwave link {link}: throughput limited, sites stayed up.",
        f"a {ctype} on {agg}, the router above the link, ran {lead} min before the "
        "degradation, so a hasty investigator blames the router change.",
        f"(1) only the sites of {link} degraded, while the sites of {', '.join(sibs)} under the "
        "same router stayed normal, so a router change is not the cause; (2) the KPIs were "
        "normal between the change and the onset; (3) the major LINK_DEGRADED alarm is on the "
        "microwave link, whose signal fluctuates like weather rather than stepping; (4) it "
        "recovered without any rollback.",
        conf=[
            (
                h,
                f"Harmless {ctype} on {agg} {lead} min before the degradation; the sibling "
                "links under the same router were unaffected.",
            )
        ],
        block=[agg],
    )


def _congestion(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    site: str = p.data["site"]
    lead: int = p.data["lead"]
    d = congestion_draft(ctx, [site], t0, _t(t0 + p.duration), p.data["users"], p.data["level"])
    tc = _t(t0 - mins(lead))
    ticket = make_ticket(ctx.rng)
    h = ctx.log.change(site, "parameter_tuning", tc, f"Scheduler weight tuning on {site}", ticket)
    link = ctx.topo.sites[site].link_id
    sibs = [s for s in sorted(ctx.topo.link_sites[link]) if s != site][:2]
    controls = [
        ctx.log.change(
            s,
            "parameter_tuning",
            _t(tc + mins(uni(ctx, 0, 3))),
            f"Scheduler weight tuning on {s}",
            ticket,
        )
        for s in sibs
    ]
    return finish(
        d,
        TRAP,
        f"Demand surge saturated the radio resources of {site}; there was no external event.",
        f"a scheduler tuning on {site} itself ran {lead} min before the congestion, so a "
        "hasty investigator blames the change.",
        "(1) the number of active users roughly doubled, which a scheduler setting cannot do; "
        f"(2) the same tuning under the same ticket went onto {', '.join(sibs)} and their load "
        "and PRB stayed normal; (3) the KPIs were normal between the change and the onset.",
        conf=[
            (
                h,
                f"Harmless parameter_tuning on {site} {lead} min before the congestion; the "
                "cause is a demand surge and neighbours with the same tuning were unaffected.",
            )
        ],
        evidence=controls,
        block=[link, *sibs],
    )


def apply_root_change(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    variant: str = p.data["variant"]
    if variant.startswith("dns_upgrade"):
        return _dns(ctx, p, t0)
    return {
        "power_param": _power,
        "fiber_router": _fiber,
        "linkdeg_router": _linkdeg,
        "congestion_batch": _congestion,
    }[variant](ctx, p, t0)
