"""Where the API keeps live runs: the trace store plus the streamed event list, in schema `app`."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Engine, text

from incident_agent.agent.report import Report
from incident_agent.agent.store import TraceStore
from incident_agent.api.events import ApiEvent, dumps
from incident_agent.api.schemas import InvestigationDetail, InvestigationSummary


class RunRepository(Protocol):
    def trace_store(self, client_hash: str | None = None) -> TraceStore | None:
        """The store the agent writes its trace to, or None to run without one.

        With a `client_hash`, the runs it starts are filed under that client.
        """

    def count_user_runs_since(self, since: datetime) -> int: ...

    def count_client_runs_since(self, client_hash: str, since: datetime) -> int:
        """User runs of one client that started at or after `since`."""

    def count_alert_runs_since(self, since: datetime) -> int: ...

    def save_events(self, run_id: str, events: list[ApiEvent]) -> None: ...

    def mark_stopped(self, run_id: str, reason: str) -> None:
        """A run that was cut short: close its trace row as an error."""

    def list_runs(self, limit: int) -> list[InvestigationSummary]: ...

    def get_run(self, run_id: str) -> InvestigationDetail | None: ...

    def get_summary(self, run_id: str) -> InvestigationSummary | None:
        """One run without its events, whether or not they were stored."""

    def find_alert_run(self, alert_id: str, running_since: datetime) -> InvestigationSummary | None:
        """The newest run of the alert that finished, or is running and started at or after
        `running_since`: an investigation that must not be started a second time."""

    def latest_alert_run_ids(
        self, alert_ids: list[str], *, stored_only: bool = False
    ) -> dict[str, str]:
        """The newest run of each alert that has one (only runs with stored events if asked)."""


_SUMMARY_COLUMNS = (
    "r.run_id, r.question, r.asked_at, r.started_at, r.status, r.trigger, r.alert_id, r.report, "
    "r.llm_calls, r.tool_calls, r.input_tokens, r.output_tokens, r.wall_seconds, r.models_used"
)


def _summary(row: Any) -> InvestigationSummary:
    report = row.report or {}
    return InvestigationSummary(
        run_id=row.run_id,
        question=row.question,
        asked_at=row.asked_at,
        started_at=row.started_at,
        status=row.status,
        trigger=row.trigger,
        alert_id=row.alert_id,
        title=report.get("title"),
        verdict=report.get("classification"),
        cause=report.get("root_cause_category"),
        node_id=report.get("root_cause_node_id"),
        confidence=report.get("confidence"),
        llm_calls=row.llm_calls,
        tool_calls=row.tool_calls,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        seconds=row.wall_seconds,
        models_used=list(row.models_used or []),
    )


class ClientTraceStore(TraceStore):
    """A trace store that files each run it starts under a client, once the run row exists."""

    def __init__(self, engine: Engine, client_hash: str) -> None:
        super().__init__(engine)
        self.client_hash = client_hash

    def start_run(
        self,
        run_id: str,
        question: str,
        asked_at: datetime,
        *,
        trigger: str = "user",
        alert_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().start_run(
            run_id, question, asked_at, trigger=trigger, alert_id=alert_id, config=config
        )
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE app.agent_runs SET client_hash = :hash WHERE run_id = :id"),
                {"hash": self.client_hash, "id": run_id},
            )


class PgRunRepository:
    def __init__(self, engine: Callable[[], Engine]) -> None:
        self._engine = engine

    def trace_store(self, client_hash: str | None = None) -> TraceStore | None:
        if client_hash is None:
            return TraceStore(self._engine())
        return ClientTraceStore(self._engine(), client_hash)

    def count_user_runs_since(self, since: datetime) -> int:
        with self._engine().connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM app.agent_runs "
                    "WHERE trigger = 'user' AND started_at >= :since"
                ),
                {"since": since},
            ).scalar_one()
        return int(count)

    def count_client_runs_since(self, client_hash: str, since: datetime) -> int:
        with self._engine().connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM app.agent_runs "
                    "WHERE trigger = 'user' AND client_hash = :hash AND started_at >= :since"
                ),
                {"hash": client_hash, "since": since},
            ).scalar_one()
        return int(count)

    def count_alert_runs_since(self, since: datetime) -> int:
        with self._engine().connect() as conn:
            count = conn.execute(
                text(
                    "SELECT count(*) FROM app.agent_runs "
                    "WHERE trigger = 'alert' AND started_at >= :since"
                ),
                {"since": since},
            ).scalar_one()
        return int(count)

    def save_events(self, run_id: str, events: list[ApiEvent]) -> None:
        with self._engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app.run_events (run_id, events) "
                    "VALUES (:id, CAST(:events AS jsonb)) "
                    "ON CONFLICT (run_id) DO UPDATE SET events = EXCLUDED.events"
                ),
                {"id": run_id, "events": dumps(events)},
            )

    def mark_stopped(self, run_id: str, reason: str) -> None:
        TraceStore(self._engine()).fail_run(run_id, reason)

    def list_runs(self, limit: int) -> list[InvestigationSummary]:
        sql = text(
            f"SELECT {_SUMMARY_COLUMNS} FROM app.agent_runs r "
            "JOIN app.run_events e ON e.run_id = r.run_id ORDER BY r.started_at DESC LIMIT :n"
        )
        with self._engine().connect() as conn:
            return [_summary(row) for row in conn.execute(sql, {"n": limit})]

    def get_run(self, run_id: str) -> InvestigationDetail | None:
        sql = text(
            f"SELECT {_SUMMARY_COLUMNS}, r.markdown, r.issues, e.events FROM app.agent_runs r "
            "JOIN app.run_events e ON e.run_id = r.run_id WHERE r.run_id = :id"
        )
        with self._engine().connect() as conn:
            row = conn.execute(sql, {"id": run_id}).first()
        if row is None:
            return None
        return InvestigationDetail(
            **_summary(row).model_dump(),
            report=Report.model_validate(row.report) if row.report else None,
            markdown=row.markdown,
            issues=list(row.issues or []),
            events=row.events,
        )

    def get_summary(self, run_id: str) -> InvestigationSummary | None:
        sql = text(f"SELECT {_SUMMARY_COLUMNS} FROM app.agent_runs r WHERE r.run_id = :id")
        with self._engine().connect() as conn:
            row = conn.execute(sql, {"id": run_id}).first()
        return None if row is None else _summary(row)

    def find_alert_run(self, alert_id: str, running_since: datetime) -> InvestigationSummary | None:
        sql = text(
            f"SELECT {_SUMMARY_COLUMNS} FROM app.agent_runs r WHERE r.alert_id = :alert "
            "AND (r.status = 'finished' OR (r.status = 'running' AND r.started_at >= :since)) "
            "ORDER BY r.started_at DESC LIMIT 1"
        )
        with self._engine().connect() as conn:
            row = conn.execute(sql, {"alert": alert_id, "since": running_since}).first()
        return None if row is None else _summary(row)

    def latest_alert_run_ids(
        self, alert_ids: list[str], *, stored_only: bool = False
    ) -> dict[str, str]:
        if not alert_ids:
            return {}
        join = "JOIN" if stored_only else "LEFT JOIN"
        sql = text(
            "SELECT DISTINCT ON (r.alert_id) r.alert_id, r.run_id FROM app.agent_runs r "
            f"{join} app.run_events e ON e.run_id = r.run_id WHERE r.alert_id = ANY(:ids) "
            "ORDER BY r.alert_id, r.started_at DESC"
        )
        with self._engine().connect() as conn:
            return {row.alert_id: row.run_id for row in conn.execute(sql, {"ids": alert_ids})}
