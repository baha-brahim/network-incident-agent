"""Questions of the hard profile. They describe symptoms, never the cause or the trap.

Trap scenarios get a next-morning question, a mid-incident question and (unless another scenario
overlaps with them) a vague one. A scenario that overlaps with another in the same region is only
ever asked about through one of its own sites, so that the report can be held to that one.
"""

import numpy as np
import pandas as pd

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.drafts import ScenarioDraft
from incident_agent.simulator.questions import (
    _NATIONAL,
    _REGION,
    _SITE,
    _SYMPTOM,
    _VAGUE,
    _clock,
    _region_phrase,
    _Tpl,
    make_questions,
    when_phrase,
)
from incident_agent.simulator.timeaxis import TimeAxis, local_to_utc


def make_hard_questions(
    rng: np.random.Generator,
    cfg: SimConfig,
    axis: TimeAxis,
    draft: ScenarioDraft,
    region_names: dict[str, str],
) -> list[dict[str, str]]:
    if draft.trap is None:
        return make_questions(rng, cfg, axis, draft, region_names)

    now = local_to_utc(cfg.now_local, cfg.utc_offset_hours)
    impact_local = axis.to_local(draft.impact_start)
    region = _region_phrase(region_names[draft.regions[0]])
    sites = sorted(draft.affected_sites)

    def morning_after() -> pd.Timestamp:
        day = impact_local.normalize() + pd.Timedelta(days=0 if impact_local.hour < 6 else 1)
        asked = day + pd.Timedelta(hours=8, minutes=float(rng.uniform(0, 120)))
        return min(
            asked.floor("min") - pd.Timedelta(hours=cfg.utc_offset_hours), now.tz_localize(None)
        )

    def right_now() -> pd.Timestamp:
        asked = draft.impact_start + pd.Timedelta(minutes=float(rng.uniform(30, 90)))
        return min(asked.floor("min"), now).tz_localize(None)

    out: list[dict[str, str]] = []
    used: set[str] = set()

    def add(asked_utc_naive: pd.Timestamp, options: list[_Tpl], site_text: str = "") -> None:
        asked_local = asked_utc_naive + pd.Timedelta(hours=cfg.utc_offset_hours)
        phrase = when_phrase(impact_local, asked_local)
        fresh = [
            t for t in options if t(phrase, site_text, region, _clock(impact_local)) not in used
        ]
        tpl = (fresh or options)[int(rng.integers(len(fresh or options)))]
        text = tpl(phrase, site_text, region, _clock(impact_local))
        used.add(text)
        iso = asked_utc_naive.tz_localize("UTC").isoformat()
        out.append({"text": text, "asked_at": iso})

    if draft.kind == "dns_degradation":
        add(morning_after(), _NATIONAL["dns"])
        add(right_now(), _NATIONAL["dns"])
        add(morning_after(), _VAGUE)
        return out

    sym = _SYMPTOM[draft.kind]
    site_text = sites[int(rng.integers(len(sites)))]
    if draft.group is not None:
        add(morning_after(), _SITE[sym], site_text)
        add(right_now(), _SITE[sym], site_text)
        return out
    add(morning_after(), _REGION[sym])
    add(right_now(), _SITE[sym], site_text)
    add(morning_after(), _VAGUE)
    return out
