"""Baseline and onset detection for one KPI series, using only data before the step it judges.

The baseline of a step is the median of the same time-of-day slot on earlier days of the same
day type (weekday, Saturday, Sunday). The spread is a robust MAD of the residuals around those
medians, pooled over neighbouring slots. A step deviates when its robust z-score is large. The
deviation is the longest run of such steps; its first step is the onset, and the first normal
step after it is the recovery. Pure numpy/pandas: no database, no clock.
"""

import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

import numpy as np
import pandas as pd

from incident_agent.agent.tools.timeutil import LOCAL_TZ, STEP

MIN_HISTORY_DAYS = 2  # fewer earlier same-type days than this: no baseline for that slot
THIN_HISTORY_DAYS = 4  # fewer than this: a baseline exists but the body says it is thin
Z_THRESHOLD = 3.5
MIN_RUN = 2  # a single deviating step is a blip, not a deviation
BRIDGE = 1  # normal steps tolerated inside one run
POOL_SLOTS = 2  # neighbouring slots pooled to estimate the spread
MAD_TO_SIGMA = 1.4826
LEAD_IN = timedelta(hours=6)  # extra look-back so an onset just before the window is found


@dataclass(frozen=True)
class Floors:
    """Smallest deviation worth noticing, so near-constant series do not produce huge z-scores."""

    abs_floor: float = 0.0
    rel_floor: float = 0.0


@dataclass
class Run:
    first: int  # step indexes into Analysis.index
    last: int
    direction: str  # "below" | "above"
    worst: int  # step with the most extreme value inside the run


@dataclass
class Analysis:
    index: pd.DatetimeIndex  # steps from the lead-in start to the window end (UTC)
    values: np.ndarray
    baseline: np.ndarray
    z: np.ndarray
    n_hist: np.ndarray
    in_window: np.ndarray  # bool mask over `index`
    run: Run | None
    recovery: int | None  # step index of the first normal step after the run
    ongoing: bool  # the run lasts until the last step with data
    before_window: bool  # the run started before the requested window


def day_type(local_index: pd.DatetimeIndex) -> np.ndarray:
    """0 weekday, 1 Saturday, 2 Sunday."""
    dow = np.asarray(local_index.dayofweek)
    return np.where(dow < 5, 0, dow - 4)


def isodow_values(types: set[int]) -> list[int]:
    """Postgres ISODOW values (Mon=1..Sun=7) of the given day types."""
    out: list[int] = []
    if 0 in types:
        out += [1, 2, 3, 4, 5]
    if 1 in types:
        out.append(6)
    if 2 in types:
        out.append(7)
    return out


def _pooled_scale(resid_abs: np.ndarray, n_slots: int) -> np.ndarray:
    scale = np.full(n_slots, np.nan)
    for s in range(n_slots):
        block = resid_abs[:, max(0, s - POOL_SLOTS) : s + POOL_SLOTS + 1].ravel()
        block = block[~np.isnan(block)]
        if block.size:
            scale[s] = MAD_TO_SIGMA * float(np.median(block))
    return scale


def compute_baseline(
    series: pd.Series,
    start: datetime,
    end: datetime,
    *,
    tz: tzinfo = LOCAL_TZ,
    min_days: int = MIN_HISTORY_DAYS,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(index, values, baseline, scale, n_hist) for every step in [start, end].

    `series` is indexed by UTC step times and may contain history before `start`. The baseline of
    a step on date D uses only dates before D.
    """
    first = series.index.min().floor("15min") if len(series) else pd.Timestamp(start)
    grid = pd.date_range(
        min(first, pd.Timestamp(start).floor("15min")), end, freq="15min", tz="UTC"
    )
    s = series[~series.index.duplicated()].reindex(grid)
    local = grid.tz_convert(tz)
    dates = np.asarray(local.date)
    n_slots = int(24 * 60 / (STEP.total_seconds() / 60))
    slot = np.asarray(local.hour * 60 + local.minute) // int(STEP.total_seconds() / 60)
    types = day_type(local)

    row_dates = sorted(set(dates))
    row_of = {d: i for i, d in enumerate(row_dates)}
    date_type = {d: int(t) for d, t in zip(dates, types, strict=True)}
    row_types = np.array([date_type[d] for d in row_dates])
    matrix = np.full((len(row_dates), n_slots), np.nan)
    rows = np.array([row_of[d] for d in dates])
    matrix[rows, slot] = s.to_numpy()

    in_range = (grid >= pd.Timestamp(start)) & (grid <= pd.Timestamp(end))
    idx = grid[in_range]
    values = s.to_numpy()[in_range]
    baseline = np.full(len(idx), np.nan)
    scale = np.full(len(idx), np.nan)
    n_hist = np.zeros(len(idx), dtype=int)

    pos = np.flatnonzero(in_range)
    by_date: dict[object, list[int]] = {}
    for k, p in enumerate(pos):
        by_date.setdefault(dates[p], []).append(k)
    for d, ks in by_date.items():
        earlier = np.array(
            [rd < d and rt == date_type[d] for rd, rt in zip(row_dates, row_types, strict=True)]
        )
        sub = matrix[earlier] if earlier.any() else np.empty((0, n_slots))
        if sub.shape[0] == 0:
            continue
        valid = (~np.isnan(sub)).sum(axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slots give NaN, as intended
            med = np.nanmedian(sub, axis=0)
        resid = np.abs(sub - med[None, :])
        spread = _pooled_scale(resid, n_slots)
        for k in ks:
            sl = int(slot[pos[k]])
            n_hist[k] = int(valid[sl])
            if valid[sl] >= min_days:
                baseline[k] = med[sl]
                scale[k] = spread[sl] if not np.isnan(spread[sl]) else 0.0
    return idx, values, baseline, scale, n_hist


def zscores(
    values: np.ndarray, baseline: np.ndarray, scale: np.ndarray, floors: Floors
) -> np.ndarray:
    denom = scale + floors.abs_floor + floors.rel_floor * np.abs(baseline)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(denom > 0, (values - baseline) / denom, np.nan)
    return z


def find_run(z: np.ndarray, in_window: np.ndarray, values: np.ndarray) -> Run | None:
    """The longest run of deviating steps (one direction) that touches the window."""
    best: Run | None = None
    best_len = 0
    for sign, direction in ((-1.0, "below"), (1.0, "above")):
        with np.errstate(invalid="ignore"):
            dev = sign * z >= Z_THRESHOLD
        n = len(z)
        i = 0
        while i < n:
            if not dev[i]:
                i += 1
                continue
            j = i
            last = i
            gap = 0
            while j + 1 < n:
                nxt = j + 1
                if dev[nxt]:
                    last = nxt
                    gap = 0
                elif not np.isnan(z[nxt]) and gap < BRIDGE:
                    gap += 1
                else:
                    break
                j = nxt
            length = last - i + 1
            touches = bool(in_window[i : last + 1].any())
            if touches and length >= MIN_RUN and length > best_len:
                seg = sign * np.nan_to_num(values[i : last + 1], nan=-np.inf * sign)
                best = Run(i, last, direction, i + int(np.argmax(seg)))
                best_len = length
            i = last + 1
    return best


def analyse(
    series: pd.Series,
    start: datetime,
    end: datetime,
    floors: Floors,
    *,
    tz: tzinfo = LOCAL_TZ,
    min_days: int = MIN_HISTORY_DAYS,
) -> Analysis:
    """Baseline, z-scores and the main deviation of `series` over [start, end]."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    lead_start = start - LEAD_IN
    idx, values, baseline, scale, n_hist = compute_baseline(
        series, lead_start, end, tz=tz, min_days=min_days
    )
    z = zscores(values, baseline, scale, floors)
    in_window = np.asarray(idx >= pd.Timestamp(start))
    run = find_run(z, in_window, values)
    recovery: int | None = None
    ongoing = False
    before = False
    if run is not None:
        before = bool(not in_window[run.first])
        judged = np.flatnonzero(~np.isnan(z))
        later = judged[judged > run.last]
        # The run is over at the first later step that could be judged (it is normal by then).
        recovery = int(later[0]) if len(later) else None
        ongoing = recovery is None
    return Analysis(idx, values, baseline, z, n_hist, in_window, run, recovery, ongoing, before)
