"""The pure detection pipeline: DataFrames in, DataFrames out."""

from dataclasses import dataclass

import pandas as pd

from incident_agent.detector.alerts import build_alerts
from incident_agent.detector.anomalies import extract_anomalies
from incident_agent.detector.baseline import Scored, score_series
from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.series import DetectorInput, Topology, build_series


@dataclass(frozen=True)
class Prepared:
    """Everything that does not depend on z_threshold / min_steps. Reused by the sweep."""

    scored: Scored
    topology: Topology


@dataclass(frozen=True)
class DetectionResult:
    alerts: pd.DataFrame
    anomalies: pd.DataFrame


def prepare(inp: DetectorInput, cfg: DetectorConfig | None = None) -> Prepared:
    cfg = cfg or DetectorConfig()
    return Prepared(score_series(build_series(inp, cfg), cfg), Topology.from_nodes(inp.nodes))


def detect_prepared(prep: Prepared, cfg: DetectorConfig | None = None) -> DetectionResult:
    cfg = cfg or DetectorConfig()
    anomalies = extract_anomalies(prep.scored, cfg)
    alerts, anomaly_rows = build_alerts(anomalies, prep.scored.series.ts, prep.topology, cfg)
    return DetectionResult(alerts, anomaly_rows)


def detect(inp: DetectorInput, cfg: DetectorConfig | None = None) -> DetectionResult:
    """Run the whole detector on in-memory tables."""
    cfg = cfg or DetectorConfig()
    return detect_prepared(prepare(inp, cfg), cfg)
