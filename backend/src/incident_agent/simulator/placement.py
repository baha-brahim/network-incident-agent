"""Choose a start time for every planned scenario so that they do not clash.

Scenarios never overlap in time (with a margin), except the deliberate overlap groups: an
anchor plus a follower in a different region that starts 20-90 minutes after it.
"""

from dataclasses import dataclass

import pandas as pd

from incident_agent.simulator.config import ScenarioSpec
from incident_agent.simulator.drafts import Ctx, Params
from incident_agent.simulator.registry import scenario_kinds
from incident_agent.simulator.timeaxis import local_to_utc


@dataclass(frozen=True)
class Placed:
    spec: ScenarioSpec
    params: Params
    start: pd.Timestamp


def _conflicts(
    placed: list[tuple[pd.Timestamp, pd.Timestamp, int]],
    t0: pd.Timestamp,
    t1: pd.Timestamp,
    margin: pd.Timedelta,
    exempt: int | None,
) -> bool:
    return any(idx != exempt and t0 - margin < b and t1 + margin > a for a, b, idx in placed)


def place_scenarios(ctx: Ctx) -> list[Placed]:
    cfg, axis, rng = ctx.cfg, ctx.axis, ctx.rng
    kinds = scenario_kinds(cfg)
    specs = list(cfg.scenario_plan)
    params = [kinds[s.kind].sample(ctx, s.difficulty) for s in specs]
    margin = pd.Timedelta(minutes=cfg.scenario_margin_minutes)
    earliest = axis.at(cfg.first_scenario_day, 0.0)
    latest_end = local_to_utc(cfg.latest_scenario_end_local, cfg.utc_offset_hours)
    last_day = axis.day_of(latest_end)

    anchors: dict[str, int] = {}
    followers: dict[int, int] = {}  # anchor index -> follower index
    for i, s in enumerate(specs):
        if s.overlap_group is None:
            continue
        if s.overlap_group not in anchors:
            anchors[s.overlap_group] = i
        else:
            followers[anchors[s.overlap_group]] = i
    follower_set = set(followers.values())

    placed: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    starts: dict[int, pd.Timestamp] = {}

    usable_days = (latest_end - earliest) / pd.Timedelta(days=1)
    kind_count: dict[str, int] = {}
    for s in specs:
        kind_count[s.kind] = kind_count.get(s.kind, 0) + 1

    gap_scale: dict[str, float] = {}

    def kind_gap(kind: str) -> pd.Timedelta:
        """Preferred spacing between same-kind scenarios, shrunk when the kind has many."""
        days = min(cfg.same_kind_gap_days, 0.8 * usable_days / kind_count[kind])
        return pd.Timedelta(days=days * gap_scale.get(kind, 1.0))

    def too_close(i: int, t0: pd.Timestamp) -> bool:
        gap = kind_gap(specs[i].kind)
        return any(
            specs[j].kind == specs[i].kind and abs(t0 - starts[j]) < gap for j in starts if j != i
        )

    def try_place(
        i: int, exempt: int | None, anchor_start: pd.Timestamp | None, attempts: int | None = None
    ) -> bool:
        p = params[i]
        lo, hi = specs[i].start_hours or p.start_hours
        for _ in range(attempts or cfg.placement_attempts):
            if anchor_start is not None:
                # Start while the anchor is still running, so the two really overlap.
                anchor_min = (
                    params[exempt].duration / pd.Timedelta(minutes=1) if exempt is not None else 90
                )
                hi_off = max(21.0, min(90.0, anchor_min - 10.0))
                t0 = (anchor_start + pd.Timedelta(minutes=float(rng.uniform(20, hi_off)))).floor(
                    "min"
                )
            elif p.whole_day:
                day = int(rng.integers(cfg.first_scenario_day, last_day))
                if p.weekday_only and int(axis.local_dow[day * 24 * 60 // axis.step_min]) >= 5:
                    continue
                t0 = axis.at(day, 0.0)
            else:
                day = int(rng.integers(cfg.first_scenario_day, last_day + 1))
                t0 = axis.at(day, float(rng.uniform(lo, hi)))
            t1 = t0 + p.duration
            if t0 < earliest or t1 > latest_end:
                continue
            if _conflicts(placed, t0, t1, margin, exempt):
                continue
            if too_close(i, t0):
                continue
            placed.append((t0, t1, i))
            starts[i] = t0
            return True
        return False

    order = sorted(
        (i for i in range(len(specs)) if i not in follower_set),
        key=lambda i: -params[i].duration,
    )

    def unplace(i: int) -> None:
        placed[:] = [x for x in placed if x[2] != i]
        starts.pop(i, None)

    def place_one(i: int) -> bool:
        if i not in followers:
            return try_place(i, None, None)
        j = followers[i]
        # Anchor and follower are placed together; retry the pair if the follower cannot fit.
        for _ in range(100):
            if not try_place(i, None, None, attempts=50):
                continue
            if params[j].regions != params[i].regions and try_place(j, i, starts[i], attempts=20):
                return True
            unplace(i)
            params[j] = kinds[specs[j].kind].sample(ctx, specs[j].difficulty)
        return False

    for i in order:
        for _ in range(6):
            if place_one(i):
                break
            # Same-kind spacing is a preference: loosen it for this kind and try again.
            for k in {specs[i].kind, specs[followers[i]].kind if i in followers else specs[i].kind}:
                gap_scale[k] = gap_scale.get(k, 1.0) / 2
        else:
            raise RuntimeError(f"could not place scenario #{i} ({specs[i].kind})")

    out = [Placed(specs[i], params[i], starts[i]) for i in range(len(specs))]
    out.sort(key=lambda x: x.start)
    return out
