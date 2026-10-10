"""Trace store: one row per run and one per LLM or tool step, in schema `app`.

Uses the owner engine (`get_engine()`); the agent's read-only role cannot see this schema. The UI,
replay mode and evaluations read from here.
"""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, text

if TYPE_CHECKING:
    from incident_agent.agent.state import CallRecord, LLMStep, RunResult


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


class TraceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

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
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app.agent_runs (run_id, question, asked_at, trigger, alert_id, "
                    "status, started_at, config) VALUES (:id, :q, :at, :trigger, :alert, "
                    "'running', :now, CAST(:cfg AS jsonb))"
                ),
                {
                    "id": run_id,
                    "q": question,
                    "at": asked_at,
                    "trigger": trigger,
                    "alert": alert_id,
                    "now": datetime.now(UTC),
                    "cfg": _json(config or {}),
                },
            )

    def log_step(
        self,
        run_id: str,
        seq: int,
        kind: str,
        node: str,
        name: str,
        input_: dict[str, Any],
        output: dict[str, Any],
        *,
        step: "LLMStep | None" = None,
        call: "CallRecord | None" = None,
    ) -> None:
        values: dict[str, Any] = {
            "run_id": run_id,
            "seq": seq,
            "kind": kind,
            "node": node,
            "name": name,
            "call_ref": call.ref if call else None,
            "input": _json(input_),
            "output": _json(output),
            "provider": step.provider if step else None,
            "model": step.model if step else None,
            "input_tokens": step.input_tokens if step else None,
            "output_tokens": step.output_tokens if step else None,
            "latency_ms": step.latency_ms if step else (call.wall_ms if call else None),
            "wall_ms": step.wall_ms if step else None,
            "cached": step.cached if step else None,
            "fell_back": step.fell_back if step else None,
            "error": (step.error if step else call.error if call else None),
            "now": datetime.now(UTC),
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO app.agent_steps (run_id, seq, kind, node, name, call_ref, input, "
                    "output, provider, model, input_tokens, output_tokens, latency_ms, wall_ms, "
                    "cached, fell_back, error, created_at) VALUES (:run_id, :seq, :kind, :node, "
                    ":name, :call_ref, CAST(:input AS jsonb), CAST(:output AS jsonb), :provider, "
                    ":model, :input_tokens, :output_tokens, :latency_ms, :wall_ms, :cached, "
                    ":fell_back, :error, :now)"
                ),
                values,
            )

    def finish_run(self, result: "RunResult") -> None:
        usage = result.usage
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE app.agent_runs SET status = :status, finished_at = :now, "
                    "wall_seconds = :wall, scope = CAST(:scope AS jsonb), "
                    "report = CAST(:report AS jsonb), markdown = :md, llm_calls = :llm, "
                    "tool_calls = :tools, input_tokens = :tin, output_tokens = :tout, "
                    "models_used = :models, fell_back = :fb, issues = CAST(:issues AS jsonb), "
                    "error = :error WHERE run_id = :id"
                ),
                {
                    "id": result.run_id,
                    "status": result.status,
                    "now": datetime.now(UTC),
                    "wall": usage.wall_seconds,
                    "scope": _json(result.scope.model_dump(mode="json") if result.scope else None),
                    "report": _json(result.report.model_dump(mode="json")),
                    "md": result.markdown,
                    "llm": usage.llm_calls,
                    "tools": usage.tool_calls,
                    "tin": usage.input_tokens,
                    "tout": usage.output_tokens,
                    "models": result.models_used,
                    "fb": result.fell_back,
                    "issues": _json(result.issues),
                    "error": result.error,
                },
            )

    def fail_run(self, run_id: str, error: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE app.agent_runs SET status = 'error', finished_at = :now, error = :e "
                    "WHERE run_id = :id"
                ),
                {"id": run_id, "now": datetime.now(UTC), "e": error[:2000]},
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT * FROM app.agent_runs WHERE run_id = :id"), {"id": run_id}
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def get_steps(self, run_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM app.agent_steps WHERE run_id = :id ORDER BY seq"),
                {"id": run_id},
            ).mappings()
            return [dict(r) for r in rows]
