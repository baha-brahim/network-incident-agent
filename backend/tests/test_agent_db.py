"""A scripted investigation against the fixture world, the trace store, and the app schema."""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from incident_agent.agent import investigate
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import Finding, TimelineEntry
from incident_agent.agent.store import TraceStore
from incident_agent.agent.tools import execute_tool
from incident_agent.agent.types import ToolContext
from incident_agent.db.loader import load_world
from incident_agent.llm.testing import ScriptedRunner
from incident_agent.llm.types import ToolCall
from tests.agent_support import make_report
from tests.fixtures_world import at, make_fixture_world
from tests.test_tools_db import EMB, _insert_detector_rows

pytestmark = pytest.mark.db

ASKED = at(1, 20)  # the fiber cut (day 1 18:00-22:00) is still running


def setup_world(db_engine: Engine) -> Iterator[Engine]:
    """Load the fixture world, runbooks and alerts into the test database; clean up afterwards."""
    from incident_agent.rag.ingest import ingest

    load_world(make_fixture_world(), db_engine)
    ingest(engine=db_engine, embedder=EMB)
    _insert_detector_rows(db_engine)
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies WHERE anomaly_id LIKE 'ANM-T%'"))
        conn.execute(text("DELETE FROM alerts WHERE alert_id LIKE 'ALR-T%'"))
        conn.execute(text("DELETE FROM app.agent_runs WHERE question LIKE 'TEST:%'"))


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


def window(start: str, end: str, **more: Any) -> dict[str, Any]:
    return {"start": start, "end": end, **more}


def scripted(report_over: dict[str, Any] | None = None) -> ScriptedRunner:
    span = window("2026-09-02 16:00", "2026-09-02 20:00")
    intake = {
        "symptom": "sites S-TUN-001 and S-TUN-002 are down",
        "window_start": "2026-09-02 17:30",
        "window_end": None,
        "region_ids": ["TUN"],
        "node_ids": ["S-TUN-001"],
        "nationwide": False,
        "ongoing": True,
    }
    turns: list[list[ToolCall] | str] = [
        [
            ToolCall(name="get_alarms", args={**span, "node_ids": ["LNK-TUN-01-A"]}),
            ToolCall(
                name="query_kpis",
                args={
                    "entity_type": "site",
                    "entity_ids": ["S-TUN-001"],
                    "metrics": ["availability_pct"],
                    **span,
                },
            ),
        ],
        [
            ToolCall(name="get_maintenance", args={**span, "node_ids": ["S-TUN-001"]}),
            ToolCall(name="get_changes", args={**span, "node_ids": ["S-TUN-001"]}),
            ToolCall(name="get_external_events", args={**span, "region_id": "TUN"}),
        ],
        [ToolCall(name="search_runbooks", args={"query": "fiber cut LINK_LOS differential"})],
        "The link alarm precedes the site alarm; no window, change or event covers it.",
    ]
    report = make_report(
        timeline=[
            TimelineEntry(time="2026-09-02 18:00", event="LOS on the link", refs=["ALM-000001"])
        ],
        findings=[
            Finding(claim="Critical LINK_LOS on the link", basis="observed", refs=["ALM-000001"]),
            Finding(claim="Site down follows", basis="observed", refs=["ALM-000002", "T4"]),
            Finding(claim="No maintenance covers it", basis="observed", refs=["T5"]),
        ],
        impact_start="2026-09-02 18:00",
    ).model_copy(update=report_over or {})

    def script(call: Any) -> Any:
        if call.purpose == "intake":
            return intake
        if call.purpose.startswith("investigate"):
            return turns[min(call.index - 1, len(turns) - 1)]
        return report

    return ScriptedRunner(script)


def run(world: Engine, agent_ro_engine: Engine, runner: ScriptedRunner, store: TraceStore | None):  # type: ignore[no-untyped-def]
    ctx = ToolContext(engine=agent_ro_engine, asked_at=ASKED, embedder=EMB)
    return investigate(
        "TEST: Why are the sites S-TUN-001 and S-TUN-002 down?",
        ASKED,
        runner=runner,
        ctx=ctx,
        store=store,
        reference=Reference.load(agent_ro_engine),
    )


def test_full_run_on_the_fixture_world_writes_a_trace(
    world: Engine, agent_ro_engine: Engine
) -> None:
    result = run(world, agent_ro_engine, scripted(), TraceStore(world))

    assert result.status == "finished", result.issues
    assert result.report.root_cause_node_id == "LNK-TUN-01-A"
    assert result.scope is not None and result.scope.window_end == ASKED  # ongoing: ends at now
    tools = [c.tool for c in result.calls]
    assert tools[:2] == ["get_anomalies", "get_topology"]  # orient
    assert {"get_alarms", "query_kpis", "get_maintenance", "search_runbooks"} <= set(tools)
    assert all(not c.error for c in result.calls), [c.headline for c in result.calls if c.error]
    assert "ALM-000001" in result.evidence
    assert any(ref.startswith("RB-") for ref in result.evidence)
    assert result.report.findings[1].refs == ["ALM-000002", "T4"]
    # No future leaks: the cut is still running at asked_at, so the clear time is unknown.
    assert "22:00" not in result.markdown

    store = TraceStore(world)
    run_row = store.get_run(result.run_id)
    assert run_row is not None
    assert run_row["status"] == "finished" and run_row["trigger"] == "user"
    assert run_row["llm_calls"] == result.usage.llm_calls
    assert run_row["tool_calls"] == result.usage.tool_calls
    assert run_row["report"]["root_cause_node_id"] == "LNK-TUN-01-A"
    assert run_row["markdown"] == result.markdown and run_row["models_used"] == [
        "scripted:scripted"
    ]
    steps = store.get_steps(result.run_id)
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    assert {s["kind"] for s in steps} == {"llm", "tool"}
    assert sum(s["kind"] == "llm" for s in steps) == result.usage.llm_calls
    tool_steps = [s for s in steps if s["kind"] == "tool"]
    assert [s["call_ref"] for s in tool_steps][:3] == ["T1", "T2", "T3"]
    assert "ALM-000001" in tool_steps[2]["output"]["body"]
    llm_steps = [s for s in steps if s["kind"] == "llm"]
    assert llm_steps[0]["node"] == "intake" and llm_steps[-1]["node"] == "conclude"
    assert llm_steps[0]["provider"] == "scripted" and llm_steps[0]["input_tokens"] > 0
    assert "CASE FILE" in llm_steps[-1]["input"]["message"]


def test_the_agent_role_cannot_read_the_app_schema(world: Engine, agent_ro_engine: Engine) -> None:
    run(world, agent_ro_engine, scripted(), TraceStore(world))
    for query in ("SELECT * FROM app.agent_runs", "SELECT count(*) FROM app.agent_steps"):
        with (
            agent_ro_engine.connect() as conn,
            pytest.raises(DBAPIError, match="permission denied"),
        ):
            conn.execute(text(query))
    # The model-facing SQL tool says no as well, without raising.
    ctx = ToolContext(engine=agent_ro_engine, asked_at=ASKED, embedder=EMB)
    reply = execute_tool("run_sql", {"query": "SELECT * FROM app.agent_runs"}, ctx)
    assert reply.error


def test_run_without_a_store_writes_nothing(world: Engine, agent_ro_engine: Engine) -> None:
    with world.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM app.agent_runs")).scalar_one()
    result = run(world, agent_ro_engine, scripted(), None)
    assert result.status == "finished"
    with world.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.agent_runs")).scalar_one() == before


def test_a_broken_store_does_not_stop_the_investigation(
    world: Engine, agent_ro_engine: Engine
) -> None:
    class Broken(TraceStore):
        def start_run(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("database is on fire")

    result = run(world, agent_ro_engine, scripted(), Broken(world))
    assert result.status == "finished"
    assert any("trace store disabled" in i for i in result.issues)


def test_future_data_is_not_reachable_through_the_agent(
    world: Engine, agent_ro_engine: Engine
) -> None:
    """Asked mid-incident, an alarm that clears later is reported as active, never as cleared."""
    result = run(world, agent_ro_engine, scripted(), None)
    alarm_call = next(c for c in result.calls if c.tool == "get_alarms")
    assert "active" in alarm_call.body and "cleared" not in alarm_call.body.replace(
        "not cleared", ""
    )
