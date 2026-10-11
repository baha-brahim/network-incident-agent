"""Read-only facts about the dataset: its clock, regions and the detector's alerts."""

from datetime import datetime

from sqlalchemy import Engine, text

from incident_agent.agent.tools.timeutil import parse_time
from incident_agent.api.schemas import AlertOut, RegionInfo


class DatasetFacts:
    def __init__(
        self,
        now: datetime,
        window_start: datetime,
        window_end: datetime,
        step_minutes: int,
        timezone: str,
        regions: list[RegionInfo],
    ) -> None:
        self.now, self.window_start, self.window_end = now, window_start, window_end
        self.step_minutes, self.timezone, self.regions = step_minutes, timezone, regions


def dataset_facts(engine: Engine) -> DatasetFacts:
    with engine.connect() as conn:
        meta = {r.key: r.value for r in conn.execute(text("SELECT key, value FROM dataset_meta"))}
        regions = [
            RegionInfo(id=r.region_id, name=r.name)
            for r in conn.execute(text("SELECT region_id, name FROM regions ORDER BY region_id"))
        ]
    return DatasetFacts(
        now=parse_time(meta["now"]),
        window_start=parse_time(meta["window_start"]),
        window_end=parse_time(meta["window_end"]),
        step_minutes=int(meta.get("step_minutes", 15)),
        timezone=meta.get("timezone", "Africa/Tunis"),
        regions=regions,
    )


def list_alerts(engine: Engine, now: datetime, limit: int) -> list[AlertOut]:
    """Newest first. Nothing that starts after `now` is shown; one still running is cut at `now`."""
    sql = text(
        "SELECT alert_id, start_at, LEAST(end_at, :now) AS end_at, severity, score, summary, "
        "region_ids, entity_ids, metrics, n_anomalies, status FROM alerts "
        "WHERE start_at <= :now ORDER BY start_at DESC, alert_id DESC LIMIT :n"
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"now": now, "n": limit}).all()
    return [
        AlertOut(
            id=r.alert_id,
            start_at=r.start_at,
            end_at=r.end_at,
            severity=r.severity,
            score=r.score,
            summary=r.summary,
            region_ids=list(r.region_ids),
            entity_ids=list(r.entity_ids),
            metrics=list(r.metrics),
            n_anomalies=r.n_anomalies,
            status=r.status,
        )
        for r in rows
    ]
