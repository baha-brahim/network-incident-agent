"""Trap `two_incidents_one_region`: two unrelated incidents on different nodes of one region that
overlap in time. Each is its own scenario with questions that name its own site."""

from typing import Any

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.events import Handle
from incident_agent.simulator.hard.incidents import (
    config_push_draft,
    fiber_cut_draft,
    finish,
    link_degradation_draft,
    mins,
    power_outage_draft,
    uni,
)
from incident_agent.simulator.scenarios import _pick, _pick_diverse, _t

TRAP = "two_incidents_one_region"


def _site_off_link(ctx: Ctx, region: str, links: list[str]) -> str:
    sites = [s for s in ctx.topo.region_sites[region] if ctx.topo.sites[s].link_id not in links]
    return _pick_diverse(ctx, sites)


def sample_pair(ctx: Ctx, difficulty: str, variant: str) -> Params:
    topo = ctx.topo
    regions = [r.region_id for r in ctx.cfg.regions]
    if variant == "linkdeg_power":
        regions = sorted(
            {topo.link_region[x] for x, m in topo.link_medium.items() if m == "microwave"}
        )
    region = _pick(ctx, regions)
    links = sorted(x for x in topo.link_sites if topo.link_region[x] == region)
    fibre = [x for x in links if topo.link_medium[x] == "fiber"]
    data: dict[str, Any] = {"variant": variant}
    if variant == "power_fiber":
        link = _pick_diverse(ctx, fibre)
        battery, outage, cut = uni(ctx, 80, 150), uni(ctx, 120, 240), uni(ctx, 150, 300)
        off = battery + uni(ctx, 15, 60)
        data |= {
            "link": link,
            "site": _site_off_link(ctx, region, [link]),
            "battery": battery,
            "outage": outage,
            "cut": cut,
            "off": off,
        }
        total = max(battery + outage, off + cut)
    elif variant == "fiber_config":
        link = _pick_diverse(ctx, fibre)
        other = _pick(ctx, [x for x in links if x != link])
        cut, cfg_len, off = uni(ctx, 180, 360), uni(ctx, 360, 900), uni(ctx, 30, 120)
        data |= {"link": link, "other": other, "cut": cut, "cfg_len": cfg_len, "off": off}
        total = max(cut, off + cfg_len)
    else:
        link = _pick_diverse(ctx, [x for x in links if topo.link_medium[x] == "microwave"])
        deg, off = uni(ctx, 180, 360), uni(ctx, 0, 40)
        battery, outage = uni(ctx, 60, 110), uni(ctx, 90, 200)
        data |= {
            "link": link,
            "site": _site_off_link(ctx, region, [link]),
            "deg": deg,
            "off": off,
            "battery": battery,
            "outage": outage,
            "vol": uni(ctx, 0.20, 0.50),
            "lat": uni(ctx, 0.3, 1.0),
        }
        total = max(deg, off + battery + outage)
    return Params("pair", difficulty, mins(total + 10), (0.0, 24.0), [region], data)


def _other_row(
    first: ScenarioDraft, second: ScenarioDraft
) -> tuple[list[tuple[Handle, str]], list[tuple[Handle, str]]]:
    def why(other: ScenarioDraft) -> str:
        return (
            f"A separate, unrelated {other.kind} on {other.root_node} in the same region, "
            "overlapping in time; it has its own scenario and must not be merged into this one."
        )

    return [(second.evidence[0], why(second))], [(first.evidence[0], why(first))]


def apply_pair(ctx: Ctx, p: Params, t0: pd.Timestamp) -> list[ScenarioDraft]:
    d = p.data
    variant: str = d["variant"]
    if variant == "power_fiber":
        a = power_outage_draft(ctx, d["site"], t0, d["battery"], d["outage"])
        b = fiber_cut_draft(
            ctx, d["link"], _t(t0 + mins(d["off"])), _t(t0 + mins(d["off"] + d["cut"]))
        )
        a_note = f"Mains failure at {d['site']}; the site went down when its batteries ran out."
        b_note = f"Fibre cut on {d['link']}; its {len(b.affected_sites)} sites lost service."
    elif variant == "fiber_config":
        sites = list(ctx.topo.link_sites[d["other"]])
        a = fiber_cut_draft(ctx, d["link"], t0, _t(t0 + mins(d["cut"])))
        b = config_push_draft(
            ctx,
            sites,
            "group",
            sorted(sites)[0],
            _t(t0 + mins(d["off"])),
            _t(t0 + mins(d["off"] + d["cfg_len"])),
        )
        a_note = f"Fibre cut on {d['link']}; its {len(a.affected_sites)} sites lost service."
        b_note = (
            f"A parameter batch pushed to the sites of {d['other']} regressed RRC success and "
            "drop rate until it was rolled back. Root cause node is the first site of the group."
        )
    else:
        a = link_degradation_draft(ctx, d["link"], t0, _t(t0 + mins(d["deg"])), d["vol"], d["lat"])
        b = power_outage_draft(ctx, d["site"], _t(t0 + mins(d["off"])), d["battery"], d["outage"])
        a_note = f"Rain fade on microwave link {d['link']}: throughput limited, sites stayed up."
        b_note = f"Mains failure at {d['site']}; the site went down when its batteries ran out."
    ca, cb = _other_row(a, b)
    trap = "two unrelated incidents overlap in one region, so the report can mix them up."
    settled = (
        "each has its own node, alarms and KPI signature; asked about one, the report must "
        "name that one's cause and keep the other out."
    )
    out = [
        finish(a, TRAP, a_note, trap, settled, conf=ca),
        finish(b, TRAP, b_note, trap, settled, conf=cb),
    ]
    out.sort(key=lambda x: x.start)
    return out
