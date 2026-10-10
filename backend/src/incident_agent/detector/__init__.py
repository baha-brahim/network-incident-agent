"""Anomaly detector: robust-z baseline per series, runs of abnormal steps, grouped into alerts."""

from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.pipeline import DetectionResult, detect
from incident_agent.detector.series import DetectorInput

__all__ = ["DetectionResult", "DetectorConfig", "DetectorInput", "detect"]
