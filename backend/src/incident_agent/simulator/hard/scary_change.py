"""Trap `maintenance_with_scary_change`: a complete planned maintenance outage with a harmless
change on the same node shortly before the window."""

import pandas as pd

from incident_agent.simulator.drafts import Ctx, Params, ScenarioDraft
from incident_agent.simulator.hard.incidents import (
    finish,
    harmless_change,
    maintenance_draft,
    mins,
    uni,
)
from incident_agent.simulator.scenarios import _pick_diverse, _t

TRAP = "maintenance_with_scary_change"


def sample_scary(ctx: Ctx, difficulty: str, variant: str) -> Params:
    topo = ctx.topo
    if variant == "link":
        node = _pick_diverse(ctx, [x for x, m in topo.link_medium.items() if m == "fiber"])
        region = topo.link_region[node]
    else:
        node = _pick_diverse(ctx, list(topo.sites))
        region = topo.sites[node].region_id
    return Params(
        "planned_maintenance",
        difficulty,
        mins(uni(ctx, 120, 240)),
        (1.0, 3.5),
        [region],
        {"variant": variant, "node": node, "lead": round(uni(ctx, 20, 60))},
    )


def apply_scary(ctx: Ctx, p: Params, t0: pd.Timestamp) -> ScenarioDraft:
    node: str = p.data["node"]
    lead: int = p.data["lead"]
    link = p.data["variant"] == "link"
    sites = list(ctx.topo.link_sites[node]) if link else [node]
    d = maintenance_draft(
        ctx,
        node,
        sites,
        t0,
        _t(t0 + p.duration),
        f"Planned fibre splice work on {node}"
        if link
        else f"Planned battery replacement and cabinet inspection at {node}",
        "Downstream sites offline during splicing" if link else "Site offline for the works",
    )
    h, ctype, _ = harmless_change(ctx, node, t0 - mins(lead))
    return finish(
        d,
        TRAP,
        f"Sites went down inside the maintenance window on {node}; not an incident.",
        f"a {ctype} on {node} was executed {lead} min before the window opened, so a hasty "
        "investigator ties the outage to the change.",
        "the four tests of the maintenance runbook pass: the window covers the node, the "
        "outage lies inside it (it starts a few minutes after the window opens and ends before "
        "it closes), the works can cause it, and the window is completed; the KPIs were normal "
        "between the change and the window, and a change does not explain a loss-of-signal "
        "outage that follows the window.",
        conf=[
            (
                h,
                f"Harmless {ctype} on {node} {lead} min before the maintenance window; the "
                "outage follows the window, not the change.",
            )
        ],
    )
