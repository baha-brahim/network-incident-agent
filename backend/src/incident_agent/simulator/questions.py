"""Natural-language questions per scenario. They describe symptoms, never the cause."""

from collections.abc import Callable

import numpy as np
import pandas as pd

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.drafts import ScenarioDraft
from incident_agent.simulator.timeaxis import TimeAxis, local_to_utc

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def when_phrase(impact: pd.Timestamp, asked: pd.Timestamp) -> str:
    """Relative time phrase from naive local timestamps ('last night', 'yesterday evening')."""
    diff = (asked.normalize() - impact.normalize()).days
    h = impact.hour
    if h < 5 or h >= 22:
        part = "night"
    elif h < 12:
        part = "morning"
    elif h < 18:
        part = "afternoon"
    else:
        part = "evening"
    if part == "night":
        if diff == 0 and h >= 22:
            return "tonight"
        if diff <= 1:
            return "last night"
        return f"on {_DAYS[impact.dayofweek]} night"
    if diff == 0:
        return f"this {part}"
    if diff == 1:
        return f"yesterday {part}"
    return f"on {_DAYS[impact.dayofweek]} {part}"


def _clock(t: pd.Timestamp) -> str:
    t = t.round("5min")
    return f"{t.hour:02d}:{t.minute:02d}"


def _region_phrase(region: str) -> str:
    return "the South" if region == "South" else region


# Each template maps (when, site_text, region_text, clock) to a question string.
_Tpl = Callable[[str, str, str, str], str]

_SITE: dict[str, list[_Tpl]] = {
    "down": [
        lambda w, s, r, c: f"{s} has been down since {c}, what happened?",
        lambda w, s, r, c: f"Customers served by {s} have no service {w}. Can you find out why?",
        lambda w, s, r, c: f"Availability for {s} fell to zero {w}. What is going on?",
    ],
    "degraded": [
        lambda w, s, r, c: f"Traffic is down and latency is up at {s} {w}. What is going on?",
        lambda w, s, r, c: f"{s} looks sluggish {w}; users are complaining about slow data. Why?",
    ],
    "accessibility": [
        lambda w, s, r, c: (
            f"Call setup failures and dropped sessions rose at {s} {w}. What is behind it?"
        ),
        lambda w, s, r, c: f"{s} shows poor accessibility since {c}. Why?",
    ],
    "slow": [
        lambda w, s, r, c: f"Customers around {s} complain about very slow speeds {w}. Why?",
        lambda w, s, r, c: f"Why is {s} struggling {w}? Latency is high and throughput is poor.",
    ],
    "surge": [
        lambda w, s, r, c: f"Traffic at {s} was far above normal {w}. Is something wrong?",
        lambda w, s, r, c: f"Why did usage jump around {s} {w}?",
    ],
    "offline_ok": [
        lambda w, s, r, c: f"{s} dropped off the network {w}. Is that an incident?",
        lambda w, s, r, c: f"Why did traffic fall to nothing at {s} {w}?",
    ],
    "alarms": [
        lambda w, s, r, c: f"{s} keeps raising alarms {w}. Is the site in trouble?",
        lambda w, s, r, c: f"A lot of alarms came from {s} {w}. Should we worry?",
    ],
}
_REGION: dict[str, list[_Tpl]] = {
    "down": [
        lambda w, s, r, c: f"Why did traffic drop in {r} {w}?",
        lambda w, s, r, c: f"Several sites in {r} went quiet {w}. What happened?",
    ],
    "degraded": [
        lambda w, s, r, c: f"Reports of sluggish data in {r} {w}. What is going on?",
        lambda w, s, r, c: f"Why did traffic fall and latency rise in {r} {w}?",
    ],
    "accessibility": [
        lambda w, s, r, c: (
            f"Call setup failures and dropped calls went up in {r} {w}. What is behind it?"
        ),
        lambda w, s, r, c: f"RRC success rate fell across several sites in {r} {w}. Why?",
    ],
    "slow": [
        lambda w, s, r, c: f"Why was latency high in parts of {r} {w}?",
        lambda w, s, r, c: f"Customers in {r} report slow speeds {w}. Any idea why?",
    ],
    "surge": [
        lambda w, s, r, c: f"Why did traffic jump in {r} {w}?",
        lambda w, s, r, c: f"Usage in {r} was unusually high {w}. Anything to worry about?",
    ],
    "offline_ok": [
        lambda w, s, r, c: f"Some sites in {r} went offline {w}. Is that an incident?",
        lambda w, s, r, c: f"Why did traffic drop in {r} {w}?",
    ],
    "alarms": [
        lambda w, s, r, c: f"We saw a burst of alarms in {r} {w}. Is anything really wrong?",
    ],
}
_NATIONAL: dict[str, list[_Tpl]] = {
    "dns": [
        lambda w, s, r, c: f"Latency complaints across the country {w}, any idea?",
        lambda w, s, r, c: (
            f"Customers everywhere report slow data and traffic dipped nationally {w}. Why?"
        ),
        lambda w, s, r, c: f"Why did nationwide traffic fall and latency rise {w}?",
    ],
    "holiday": [
        lambda w, s, r, c: (
            f"Total traffic was noticeably lower across the country {w}. Anything to worry about?"
        ),
        lambda w, s, r, c: f"Why was nationwide traffic down {w}?",
    ],
}
_VAGUE: list[_Tpl] = [
    lambda w, s, r, c: f"Anything unusual in the network {w}?",
    lambda w, s, r, c: f"Did anything notable happen on the network {w}?",
    lambda w, s, r, c: f"Give me a quick rundown of network problems {w}.",
]

_SYMPTOM = {
    "fiber_cut": "down",
    "power_outage": "down",
    "config_push": "accessibility",
    "congestion": "slow",
    "link_degradation": "degraded",
    "planned_maintenance": "offline_ok",
    "stadium_event": "surge",
    "alarm_storm": "alarms",
}


def make_questions(
    rng: np.random.Generator,
    cfg: SimConfig,
    axis: TimeAxis,
    draft: ScenarioDraft,
    region_names: dict[str, str],
) -> list[dict[str, str]]:
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

    def pick(options: list[_Tpl]) -> _Tpl:
        return options[int(rng.integers(len(options)))]

    out: list[dict[str, str]] = []
    used: set[str] = set()

    def add(asked_utc_naive: pd.Timestamp, options: list[_Tpl], site_text: str = "") -> None:
        asked_local = asked_utc_naive + pd.Timedelta(hours=cfg.utc_offset_hours)
        if draft.kind == "public_holiday":
            same_day = asked_local.normalize() == impact_local.normalize()
            phrase = "today" if same_day else "yesterday"
        else:
            phrase = when_phrase(impact_local, asked_local)
        for _ in range(6):
            text = pick(options)(phrase, site_text, region, _clock(impact_local))
            if text not in used:
                break
        used.add(text)
        iso = asked_utc_naive.tz_localize("UTC").isoformat()
        out.append({"text": text, "asked_at": iso})

    kind = draft.kind
    n_questions = {"easy": 2, "medium": 2 + int(rng.integers(0, 2)), "hard": 3}[draft.difficulty]
    allow_vague = draft.group is None
    if kind == "dns_degradation":
        add(morning_after(), _NATIONAL["dns"])
        add(right_now(), _NATIONAL["dns"])
        if n_questions > 2 and allow_vague:
            add(morning_after(), _VAGUE)
    elif kind == "public_holiday":
        add(morning_after(), _NATIONAL["holiday"])
        add(morning_after(), _NATIONAL["holiday"])
        if n_questions > 2:
            add(morning_after(), _VAGUE)
    else:
        sym = _SYMPTOM[kind]
        site_text = sites[int(rng.integers(len(sites)))] if sites else ""
        first = _SITE[sym] if sites and draft.difficulty != "hard" else _REGION[sym]
        second = _SITE[sym] if sites and draft.difficulty != "easy" else _REGION[sym]
        add(morning_after(), first, site_text)
        add(right_now(), second, site_text)
        if n_questions > 2:
            if allow_vague:
                add(morning_after(), _VAGUE)
            else:
                add(morning_after(), _REGION[sym])
    return out
