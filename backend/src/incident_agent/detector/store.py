"""Thin Postgres layer: read KPI tables, replace the `anomalies` and `alerts` tables."""

from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

from incident_agent.db.session import get_engine
from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.pipeline import DetectionResult, detect
from incident_agent.detector.series import DetectorInput

_CELL_KPI_COLUMNS = (
    "ts, cell_id, dl_volume_mb, active_users, rrc_success_pct, drop_rate_pct, "
    "latency_ms, prb_util_pct, availability_pct"
)


def read_input(engine: Engine | None = None) -> DetectorInput:
    """Load nodes, cells and KPIs. Needs only SELECT rights, so `agent_ro` works too."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        nodes = pd.read_sql(
            text("SELECT node_id, node_type, region_id, parent_id FROM nodes"), conn
        )
        cells = pd.read_sql(text("SELECT cell_id, site_id FROM cells"), conn)
        cell_kpis = pd.read_sql(text(f"SELECT {_CELL_KPI_COLUMNS} FROM cell_kpis"), conn)
        core_kpis = pd.read_sql(text("SELECT ts, node_id, metric, value FROM core_kpis"), conn)
    for df, col in ((cell_kpis, "ts"), (core_kpis, "ts")):
        df[col] = pd.to_datetime(df[col], utc=True)
    return DetectorInput(nodes, cells, cell_kpis, core_kpis)


def _value(value: Any) -> Any:
    """A DataFrame cell as a plain Python value that psycopg can adapt."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if value is None or (isinstance(value, float) and value != value):
        return None
    return value.item() if hasattr(value, "item") else value


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): _value(v) for k, v in rec.items()} for rec in df.to_dict(orient="records")]


def write_result(result: DetectionResult, engine: Engine | None = None) -> dict[str, int]:
    """Replace the contents of `anomalies` and `alerts` in one transaction."""
    engine = engine or get_engine()
    alerts, anomalies = _records(result.alerts), _records(result.anomalies)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies"))
        conn.execute(text("DELETE FROM alerts"))
        if alerts:
            conn.execute(
                text(
                    "INSERT INTO alerts (alert_id, start_at, end_at, region_ids, entity_ids, "
                    "metrics, severity, score, n_anomalies, summary, status) VALUES "
                    "(:alert_id, :start_at, :end_at, :region_ids, :entity_ids, :metrics, "
                    ":severity, :score, :n_anomalies, :summary, :status)"
                ),
                alerts,
            )
        if anomalies:
            conn.execute(
                text(
                    "INSERT INTO anomalies (anomaly_id, alert_id, entity_type, entity_id, "
                    "region_id, metric, direction, start_at, end_at, n_steps, peak_z, "
                    "baseline_value, observed_value) VALUES (:anomaly_id, :alert_id, "
                    ":entity_type, :entity_id, :region_id, :metric, :direction, :start_at, "
                    ":end_at, :n_steps, :peak_z, :baseline_value, :observed_value)"
                ),
                anomalies,
            )
    return {"alerts": len(alerts), "anomalies": len(anomalies)}


def run_detector(
    engine: Engine | None = None, cfg: DetectorConfig | None = None
) -> tuple[DetectionResult, dict[str, int]]:
    """Read KPIs from Postgres, detect, and replace the output tables."""
    result = detect(read_input(engine), cfg)
    return result, write_result(result, engine)
