"""Investigations started by a detector alert: the question an alert asks, and running one."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, text

from incident_agent.agent.tools.timeutil import STEP, as_utc, fmt_hm
from incident_agent.api.live import day_start, live_events, seconds_to_next_day
from incident_agent.api.runs import UNKNOWN_RUN
from incident_agent.api.schemas import AlertRunOut, InvestigationSummary
from incident_agent.api.services import Services
from incident_agent.detector.config import CELL_METRICS, CORE_METRICS, DetectorConfig

# A run that is still marked running after this long is taken as dead; the alert may be retried.
IN_PROGRESS_WINDOW = timedelta(minutes=15)
MAX_QUESTION_CHARS = 300
MAX_NAMED_ENTITIES = 4
SEVERITIES = ("low", "medium", "high")

METRIC_LABELS = {m.name: m.label for m in (*CELL_METRICS, *CORE_METRICS)}
_VERBS = {"drop": "dropping", "spike": "spiking"}


class UnknownAlert(LookupError):
    """No such alert, or it starts after the dataset's now."""


class AlertLimitReached(Exception):
    def __init__(self, limit: int, retry_after: int) -> None:
        super().__init__(f"the limit of {limit} alert investigations per day is reached")
        self.limit, self.retry_after = limit, retry_after


@dataclass(frozen=True)
class AlertQuestion:
    alert_id: str
    question: str
    asked_at: datetime


@dataclass(frozen=True)
class VisibleAnomaly:
    entity_type: str
    entity_id: str
    region_id: str | None
    metric: str
    direction: str


@dataclass(frozen=True)
class PendingAlert:
    alert_id: str
    severity: str
    question: AlertQuestion


def alert_asked_at(
    start_at: datetime, now: datetime, cfg: DetectorConfig | None = None
) -> datetime:
    """When the detector could first raise an alert that started at `start_at`, plus one step.

    It needs `min_steps` abnormal steps in a row, and the data of the last one takes a step to
    land. The investigation is asked at that moment, so it never sees the alert's later course.
    The result is never later than `now`, the end of the data.
    """
    cfg = cfg or DetectorConfig()
    return min(as_utc(start_at) + (cfg.min_steps + 1) * STEP, as_utc(now))


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


def _what(anomalies: Sequence[VisibleAnomaly]) -> str:
    phrases: list[str] = []
    for direction, verb in _VERBS.items():
        labels = [
            label
            for name, label in METRIC_LABELS.items()
            if any(a.metric == name and a.direction == direction for a in anomalies)
        ]
        if labels:
            phrases.append(f"{_join(labels)} {verb}")
    return " and ".join(phrases)


def _entity_list(entities: Sequence[str], named: int) -> str:
    if len(entities) <= named:
        return _join(entities)
    return f"{', '.join(entities[:named])} and {len(entities) - named} more"


def _regions(ids: Sequence[str], names: dict[str, str]) -> str:
    return " and ".join(names.get(i, i) for i in ids)


def question_text(
    alert_id: str,
    asked_at: datetime,
    anomalies: Sequence[VisibleAnomaly],
    region_names: dict[str, str],
    alert_region_ids: Sequence[str] = (),
    alert_metrics: Sequence[str] = (),
) -> str:
    """The one sentence an alert asks, from what is visible at `asked_at` (8 to 300 characters).

    With no anomaly visible yet, the alert's own regions and metrics stand in for them.
    """
    head = f"Detector alert {alert_id} at {fmt_hm(asked_at)}:"
    tail = "What is causing it?"
    if not anomalies:
        labels = [label for name, label in METRIC_LABELS.items() if name in alert_metrics]
        where = (
            f"in {_regions(alert_region_ids, region_names)}" if alert_region_ids else "nationwide"
        )
        return f"{head} abnormal {_join(labels) if labels else 'KPIs'} {where}. {tail}"

    what = _what(anomalies)
    entities = sorted({a.entity_id for a in anomalies if a.entity_type != "region"})
    if entities:
        preposition = "at"
        region_ids = sorted({a.region_id for a in anomalies if a.region_id})
        context = f" ({_regions(region_ids, region_names)})" if region_ids else ""
    else:
        preposition, context = "in", ""
        entities = sorted({region_names.get(a.entity_id, a.entity_id) for a in anomalies})
    sentence = ""
    for named in range(MAX_NAMED_ENTITIES, 0, -1):
        where = f"{preposition} {_entity_list(entities, named)}{context}"
        sentence = f"{head} {what} {where}. {tail}"
        if len(sentence) <= MAX_QUESTION_CHARS:
            break
    return sentence[:MAX_QUESTION_CHARS]


def alert_question(engine: Engine, alert_id: str, now: datetime) -> AlertQuestion | None:
    """None for an unknown alert, or one that starts after `now`."""
    with engine.connect() as conn:
        alert = conn.execute(
            text("SELECT start_at, region_ids, metrics FROM alerts WHERE alert_id = :id"),
            {"id": alert_id},
        ).first()
        if alert is None or alert.start_at > now:
            return None
        asked_at = alert_asked_at(alert.start_at, now)
        rows = conn.execute(
            text(
                "SELECT entity_type, entity_id, region_id, metric, direction FROM anomalies "
                "WHERE alert_id = :id AND start_at <= :asked ORDER BY start_at, anomaly_id"
            ),
            {"id": alert_id, "asked": asked_at},
        ).all()
        names = {
            r.region_id: r.name for r in conn.execute(text("SELECT region_id, name FROM regions"))
        }
    anomalies = [
        VisibleAnomaly(r.entity_type, r.entity_id, r.region_id, r.metric, r.direction) for r in rows
    ]
    question = question_text(
        alert_id, asked_at, anomalies, names, list(alert.region_ids), list(alert.metrics)
    )
    return AlertQuestion(alert_id, question, asked_at)


def alert_remaining(svc: Services) -> int:
    used = svc.runs.count_alert_runs_since(day_start(svc.clock()))
    return max(0, svc.settings.alert_daily_limit - used)


def run_alert(svc: Services, alert_id: str) -> AlertRunOut:
    """Investigate an alert to the end, in this thread, unless it already has a run.

    Raises `UnknownAlert`, or `AlertLimitReached` when a new run would exceed the daily limit.
    The run is stored like a live run (trigger `alert`), so the run view shows it.
    """
    now = as_utc(svc.facts().now)
    asked = alert_question(svc.agent_engine(), alert_id, now)
    if asked is None:
        raise UnknownAlert(alert_id)
    clock = svc.clock()
    existing = svc.runs.find_alert_run(alert_id, clock - IN_PROGRESS_WINDOW)
    if existing is not None:
        return AlertRunOut(created=False, run=existing)
    if alert_remaining(svc) <= 0:
        raise AlertLimitReached(svc.settings.alert_daily_limit, seconds_to_next_day(clock))

    events = list(
        live_events(svc, asked.question, asked.asked_at, trigger="alert", alert_id=alert_id)
    )
    run_id = events[0]["run_id"] if events else UNKNOWN_RUN
    stored = svc.runs.get_summary(run_id)
    if stored is None:  # the run died before it had a row: report it as the error it was
        stored = InvestigationSummary(
            run_id=run_id,
            question=asked.question,
            asked_at=asked.asked_at,
            started_at=clock,
            status="error",
            trigger="alert",
            alert_id=alert_id,
        )
    return AlertRunOut(created=True, run=stored)


def pending_alerts(svc: Services, limit: int, min_severity: str = "medium") -> list[PendingAlert]:
    """Alerts up to the dataset's now that have no run of any status, newest first."""
    now = as_utc(svc.facts().now)
    wanted = list(SEVERITIES[SEVERITIES.index(min_severity) :])
    with svc.agent_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT alert_id, severity FROM alerts "
                "WHERE start_at <= :now AND severity = ANY(:severities) "
                "ORDER BY start_at DESC, alert_id DESC"
            ),
            {"now": now, "severities": wanted},
        ).all()
    done = svc.runs.latest_alert_run_ids([r.alert_id for r in rows])
    pending: list[PendingAlert] = []
    for row in rows:
        if row.alert_id in done:
            continue
        question = alert_question(svc.agent_engine(), row.alert_id, now)
        if question is not None:
            pending.append(PendingAlert(row.alert_id, row.severity, question))
        if len(pending) == limit:
            break
    return pending
