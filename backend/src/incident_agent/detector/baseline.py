"""Robust baseline and z-scores.

For every series, day type (weekday / Saturday / Sunday) and time-of-day slot, the baseline is the
median of the values seen at that slot (and its neighbours) on days of the same type. The spread
is the MAD (median absolute deviation). Both ignore NaN. The window being scored is also the
window the baseline is learnt from (a batch, in-sample baseline); the median and MAD make that
safe as long as incidents cover a minority of the samples in each pool.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.series import SeriesSet

MAD_TO_SIGMA = 1.4826  # makes the MAD comparable to a standard deviation for normal data


@dataclass(frozen=True)
class Scored:
    """Series plus their expected value and robust z-score at every step."""

    series: SeriesSet
    baseline: np.ndarray  # (N, T) expected value
    z: np.ndarray  # (N, T) signed robust z; NaN where value or baseline is unknown


def nanmedian_rows(a: np.ndarray) -> np.ndarray:
    """Median of each row of `a`, ignoring NaN. Rows with no valid value give NaN."""
    ordered = np.sort(a, axis=1)  # NaN sorts to the end
    n = (~np.isnan(a)).sum(axis=1)
    rows = np.arange(a.shape[0])
    lo = np.maximum((n - 1) // 2, 0)
    hi = np.minimum(n // 2, a.shape[1] - 1)
    med: np.ndarray = (ordered[rows, lo] + ordered[rows, hi]) / 2.0
    med[n == 0] = np.nan
    return med


def robust_stats(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Row-wise (median, MAD, number of valid samples) of `samples`, ignoring NaN."""
    med = nanmedian_rows(samples)
    mad = nanmedian_rows(np.abs(samples - med[:, None]))
    return med, mad, (~np.isnan(samples)).sum(axis=1)


def day_type_and_slot(ts: pd.DatetimeIndex, cfg: DetectorConfig) -> tuple[np.ndarray, np.ndarray]:
    """Day type (0 weekday, 1 Saturday, 2 Sunday) and time-of-day slot of each step, local time."""
    local = ts.tz_convert(cfg.timezone)
    dow = np.asarray(local.dayofweek)
    day_type = np.where(dow < 5, 0, dow - 4)
    step_min = (
        round(float(np.median(np.diff(ts.to_numpy())) / np.timedelta64(1, "m")))
        if len(ts) > 1
        else 15
    )
    slot = (np.asarray(local.hour) * 60 + np.asarray(local.minute)) // max(step_min, 1)
    return day_type, slot


def score_series(series: SeriesSet, cfg: DetectorConfig) -> Scored:
    """Compute the baseline and signed robust z-score of every series at every step."""
    x = series.values
    day_type, slot = day_type_and_slot(series.ts, cfg)
    n_slots = int(slot.max()) + 1 if len(slot) else 0
    baseline = np.full(x.shape, np.nan)
    scale = np.full(x.shape, np.nan)

    for dt in np.unique(day_type):
        in_type = day_type == dt
        by_slot = [np.flatnonzero(in_type & (slot == s)) for s in range(n_slots)]
        for s in range(n_slots):
            own = by_slot[s]
            if len(own) == 0:
                continue
            pool = np.concatenate(
                [by_slot[(s + k) % n_slots] for k in range(-cfg.pool_slots, cfg.pool_slots + 1)]
            )
            med, mad, n_valid = robust_stats(x[:, pool])
            ok = n_valid >= cfg.min_baseline_samples
            baseline[np.ix_(ok, own)] = med[ok, None]
            scale[np.ix_(ok, own)] = mad[ok, None]

    abs_floor = np.array([m.abs_floor for m in series.spec])[:, None]
    rel_floor = np.array([m.rel_floor for m in series.spec])[:, None]
    denom = MAD_TO_SIGMA * scale + abs_floor + rel_floor * np.abs(baseline)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(denom > 0, (x - baseline) / denom, np.nan)
    return Scored(series=series, baseline=baseline, z=z)
