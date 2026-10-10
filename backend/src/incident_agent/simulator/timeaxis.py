"""The 15-minute time grid and helpers to convert between local wall-clock and UTC."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from incident_agent.simulator.config import SimConfig


def local_to_utc(local_iso: str, offset_hours: int) -> pd.Timestamp:
    return (pd.Timestamp(local_iso) - pd.Timedelta(hours=offset_hours)).tz_localize("UTC")


@dataclass(frozen=True)
class TimeAxis:
    start: pd.Timestamp  # UTC
    n_steps: int
    step_min: int
    utc_offset_h: int
    ts: pd.DatetimeIndex
    local_hour: np.ndarray  # hour of day at the start of each step, fractional
    local_dow: np.ndarray  # 0 = Monday
    local_day: np.ndarray  # day index since window start

    @classmethod
    def from_config(cls, cfg: SimConfig) -> "TimeAxis":
        start = local_to_utc(cfg.window_start_local, cfg.utc_offset_hours)
        n = cfg.days * 24 * 60 // cfg.step_minutes
        ts = pd.date_range(start, periods=n, freq=f"{cfg.step_minutes}min")
        local = (ts + pd.Timedelta(hours=cfg.utc_offset_hours)).tz_localize(None)
        hour = local.hour.to_numpy() + local.minute.to_numpy() / 60.0
        return cls(
            start=start,
            n_steps=n,
            step_min=cfg.step_minutes,
            utc_offset_h=cfg.utc_offset_hours,
            ts=ts,
            local_hour=hour.astype(float),
            local_dow=local.dayofweek.to_numpy().astype(int),
            local_day=np.arange(n) * cfg.step_minutes // (24 * 60),
        )

    @property
    def end(self) -> pd.Timestamp:
        return self.start + pd.Timedelta(minutes=self.step_min * self.n_steps)

    def pos(self, t: pd.Timestamp) -> float:
        """Position of `t` on the grid, in (fractional) steps."""
        return float((t - self.start) / pd.Timedelta(minutes=self.step_min))

    def coverage(self, t0: pd.Timestamp, t1: pd.Timestamp) -> np.ndarray:
        """Per step, the fraction of the step lying inside [t0, t1]."""
        idx = np.arange(self.n_steps)
        s, e = self.pos(t0), self.pos(t1)
        cov: np.ndarray = np.clip(np.minimum(e, idx + 1) - np.maximum(s, idx), 0.0, 1.0)
        return cov

    def at(self, day: int, hour: float) -> pd.Timestamp:
        """UTC timestamp of local `hour` on local day index `day` (hour may exceed 24)."""
        return (self.start + pd.Timedelta(days=day) + pd.Timedelta(minutes=round(hour * 60))).floor(
            "min"
        )

    def to_local(self, t: pd.Timestamp) -> pd.Timestamp:
        """Naive local wall-clock time of a UTC timestamp."""
        return (t + pd.Timedelta(hours=self.utc_offset_h)).tz_localize(None)

    def day_of(self, t: pd.Timestamp) -> int:
        return int((t - self.start) // pd.Timedelta(days=1))
