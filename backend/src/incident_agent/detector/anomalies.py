"""From z-scores to anomalies: runs of abnormal steps in a direction of interest."""

from dataclasses import dataclass

import numpy as np

from incident_agent.detector.baseline import Scored
from incident_agent.detector.config import DetectorConfig, Direction


@dataclass(frozen=True)
class Anomaly:
    """One entity, one metric, one continuous interval away from its baseline.

    `start` and `end` are inclusive step indices into the series' time axis.
    """

    entity_type: str
    entity_id: str
    region_id: str | None
    metric: str
    direction: Direction
    start: int
    end: int
    peak_z: float
    baseline_value: float
    observed_value: float

    @property
    def n_steps(self) -> int:
        return self.end - self.start + 1


def find_runs(mask: np.ndarray) -> list[tuple[int, int, int]]:
    """All maximal runs of True in each row of `mask`, as (row, first_col, last_col)."""
    n_rows, n_cols = mask.shape
    width = n_cols + 2
    padded = np.zeros((n_rows, width), dtype=np.int8)
    padded[:, 1:-1] = mask
    step = np.diff(padded.ravel())
    first = np.flatnonzero(step == 1) + 1
    last = np.flatnonzero(step == -1)
    rows = first // width
    return list(
        zip(rows.tolist(), (first % width - 1).tolist(), (last % width - 1).tolist(), strict=True)
    )


def _bridge(runs: list[tuple[int, int, int]], gap: int) -> list[tuple[int, int, int]]:
    """Join runs of the same row that are separated by at most `gap` normal steps."""
    out: list[tuple[int, int, int]] = []
    for row, first, last in runs:  # find_runs yields rows in order, runs left to right
        if out and out[-1][0] == row and first - out[-1][2] - 1 <= gap:
            out[-1] = (row, out[-1][1], last)
        else:
            out.append((row, first, last))
    return out


def extract_anomalies(scored: Scored, cfg: DetectorConfig) -> list[Anomaly]:
    """Runs of at least `cfg.min_steps` steps beyond `cfg.z_threshold`, sorted by start time."""
    s = scored.series
    found: list[Anomaly] = []
    for direction, sign in (("drop", -1.0), ("spike", 1.0)):
        rows = np.array(
            [i for i, spec in enumerate(s.spec) if direction in spec.directions], dtype=int
        )
        if len(rows) == 0:
            continue
        signed = scored.z[rows] * sign  # positive = abnormal in this direction
        with np.errstate(invalid="ignore"):
            mask = signed >= cfg.z_threshold
        for local_row, first, last in _bridge(find_runs(mask), cfg.bridge_gap):
            if last - first + 1 < cfg.min_steps:
                continue
            idx = int(rows[local_row])
            window = np.nan_to_num(signed[local_row, first : last + 1], nan=-np.inf)
            worst = first + int(np.argmax(window))
            found.append(
                Anomaly(
                    entity_type=str(s.entity_type[idx]),
                    entity_id=str(s.entity_id[idx]),
                    region_id=s.region_id[idx],
                    metric=str(s.metric[idx]),
                    direction="drop" if sign < 0 else "spike",
                    start=first,
                    end=last,
                    peak_z=float(scored.z[idx, worst]),
                    baseline_value=float(scored.baseline[idx, worst]),
                    observed_value=float(s.values[idx, worst]),
                )
            )
    found.sort(key=lambda a: (a.start, a.entity_id, a.metric, a.direction, a.end))
    return found
