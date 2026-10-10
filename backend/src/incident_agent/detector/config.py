"""Every threshold of the detector in one frozen dataclass."""

from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["drop", "spike"]


@dataclass(frozen=True)
class MetricSpec:
    """How one metric is monitored.

    The z-score denominator is `1.4826 * MAD + abs_floor + rel_floor * |median|`. The floor stops
    a near-constant series (availability is 100 almost always) from producing huge z-scores on
    harmless wiggles.
    """

    name: str
    directions: tuple[Direction, ...]
    abs_floor: float = 0.0
    rel_floor: float = 0.0
    label: str = ""  # used in alert summaries


CELL_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("dl_volume_mb", ("drop", "spike"), rel_floor=0.02, label="traffic"),
    MetricSpec("active_users", ("drop", "spike"), rel_floor=0.02, label="active users"),
    MetricSpec("availability_pct", ("drop",), abs_floor=1.0, label="availability"),
    MetricSpec("rrc_success_pct", ("drop",), abs_floor=0.1, label="RRC success"),
    MetricSpec("drop_rate_pct", ("spike",), abs_floor=0.05, rel_floor=0.05, label="drop rate"),
    MetricSpec("latency_ms", ("spike",), rel_floor=0.03, label="latency"),
    MetricSpec("prb_util_pct", ("spike",), abs_floor=1.0, rel_floor=0.02, label="PRB utilisation"),
)

CORE_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("query_success_pct", ("drop",), abs_floor=0.1, label="DNS query success"),
    MetricSpec("resolution_ms", ("spike",), abs_floor=0.5, rel_floor=0.05, label="DNS resolution"),
    MetricSpec("throughput_gbps", ("drop", "spike"), rel_floor=0.02, label="UPF throughput"),
    MetricSpec("session_count", ("drop", "spike"), rel_floor=0.02, label="UPF sessions"),
    MetricSpec("attach_success_pct", ("drop",), abs_floor=0.05, label="attach success"),
)


@dataclass(frozen=True)
class DetectorConfig:
    # Detection
    z_threshold: float = 3.5  # robust z beyond which a step is "abnormal"
    min_steps: int = 3  # consecutive abnormal steps needed (a 1-step blip never fires)
    bridge_gap: int = 1  # abnormal runs separated by at most this many normal steps are joined
    # Baseline
    timezone: str = "Africa/Tunis"  # defines day type and time-of-day slot
    pool_slots: int = 2  # a slot's baseline pools +-this many neighbouring slots
    min_baseline_samples: int = 8  # fewer valid samples than this: no baseline, no detection
    # Grouping
    merge_gap_steps: int = 2  # anomalies closer than this in time count as overlapping
    nationwide_min_regions: int = 3  # this many regions at the same time = one nationwide alert
    # Severity score: 2*ln(1+peak_z) + ln(1+hours) + ln(1+entities)
    medium_score: float = 9.0
    high_score: float = 12.0
    peak_z_cap: float = 100.0
    summary_max_sites: int = 5
    cell_metrics: tuple[MetricSpec, ...] = field(default=CELL_METRICS, repr=False)
    core_metrics: tuple[MetricSpec, ...] = field(default=CORE_METRICS, repr=False)
