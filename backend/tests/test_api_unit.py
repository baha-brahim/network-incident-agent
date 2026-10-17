"""API tests without a database or a network: scripted model, canned tools, in-memory runs."""

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from incident_agent.agent.graph import stream
from incident_agent.agent.report import all_refs
from incident_agent.agent.state import AgentEvent
from incident_agent.agent.types import ToolContext, ToolResult
from incident_agent.api.app import create_app
from incident_agent.api.bridge import sse_from_iterator
from incident_agent.api.catalog import CATALOG
from incident_agent.api.demos import MAX_GAP_MS, MIN_STEP_MS, DemoLibrary, replay_frames, retime
from incident_agent.api.enrich import ToolRecorder
from incident_agent.api.events import KEEPALIVE, ApiEvent, envelope
from incident_agent.api.jsonsafe import MAX_DATA_BYTES, cap_data, size_of, to_jsonable
from incident_agent.api.live import day_start, live_events
from incident_agent.api.openapi import OPENAPI_PATH, render
from incident_agent.api.runs import UNKNOWN_RUN, run_events
from incident_agent.api.schemas import RunEvent
from incident_agent.api.services import Services
from incident_agent.llm.testing import RecordedCall, ScriptedRunner
from tests.agent_support import REFERENCE, WINDOW, fake_tools
from tests.api_support import (
    DATASET_NOW,
    QUESTION,
    MemoryRunRepository,
    default_script,
    make_services,
    parse_sse,
)

EVENT = TypeAdapter(RunEvent)
ASKED = datetime.fromisoformat(DATASET_NOW)


def client(services: Services | None = None, **kwargs: Any) -> TestClient:
    return TestClient(create_app(services or make_services()), **kwargs)


def agent_events(script: Any = None, executor: Any = fake_tools) -> list[ApiEvent]:
    """The API events of one scripted run on the canned tools."""
    recorder = ToolRecorder(executor)
    runner = ScriptedRunner(script or default_script())
    return list(
        run_events(
            lambda: stream(
                QUESTION,
                ASKED,
                runner=runner,
                ctx=ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED),
                reference=REFERENCE,
                tool_executor=recorder,
            ),
            recorder,
        )
    )


def of_type(events: list[ApiEvent], type_: str) -> list[ApiEvent]:
    return [e for e in events if e["type"] == type_]


# --- the recorded demos ------------------------------------------------------------------------


def test_the_catalog_and_the_recordings_agree() -> None:
    assert len(CATALOG) == 8
    assert DemoLibrary().ids() == [spec.id for spec in CATALOG]


@pytest.mark.parametrize("demo_id", [spec.id for spec in CATALOG])
def test_every_recording_loads_and_matches_the_event_schema(demo_id: str) -> None:
    demo = DemoLibrary().get(demo_id)
    assert demo is not None
    events = demo.events
    for event in events:
        EVENT.validate_python(event)
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert {e["run_id"] for e in events} == {events[0]["run_id"]}
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert events[-1]["data"]["status"] == "finished"
    times = [e["t_ms"] for e in events]
    assert times[0] == 0 and times == sorted(times)
    assert max(b - a for a, b in pairwise(times)) <= MAX_GAP_MS
    assert demo.recording.duration_ms == times[-1]
    # every call has its result, in order; a citation can be traced to the evidence
    calls = [e["data"]["ref"] for e in of_type(events, "tool_call")]
    results = [e["data"]["ref"] for e in of_type(events, "tool_result")]
    assert calls == results == [f"T{i}" for i in range(1, len(calls) + 1)]
    finished = events[-1]["data"]
    assert set(all_refs(demo.recording.events[-1].data.report)) <= set(finished["evidence"])  # type: ignore[union-attr]
    assert all(finished["evidence"][c]["kind"] == "call" for c in calls)
    for result in of_type(events, "tool_result"):
        assert result["data"]["body"] and "args" in result["data"]
        assert len(result["data"]["refs"]) == min(result["data"]["n_refs"], 60)
    json.dumps(events, allow_nan=False)


def test_titles_and_teasers_do_not_name_a_cause() -> None:
    cause_words = {
        "fiber", "fibre", "cut", "power", "outage", "dns", "config", "push", "maintenance",
        "stadium", "match", "congestion", "capacity", "upgrade", "change", "rollback",
    }  # fmt: skip
    for spec in CATALOG:
        words = set(re.findall(r"[a-z]+", f"{spec.title} {spec.teaser}".lower()))
        assert not words & cause_words, spec.id
        assert len(spec.title) <= 30 and len(spec.teaser) <= 110, spec.id


def test_demo_endpoints() -> None:
    c = client()
    listing = c.get("/api/demos")
    assert listing.status_code == 200
    items = listing.json()
    assert [i["id"] for i in items] == [spec.id for spec in CATALOG]
    first = items[0]
    assert set(first) == {"id", "title", "teaser", "question", "asked_at", "duration_ms", "counts"}
    assert first["counts"]["tool_calls"] > 0 and first["duration_ms"] > 1000

    whole = c.get("/api/demos/fiber-cut").json()
    assert whole["events"][0]["type"] == "run_started" and whole["schema_version"] == 1
    assert len(whole["events"]) == first["counts"]["events"]

    for bad in ("nope", "..%2Fsecrets", "FIBER-CUT"):
        r = c.get(f"/api/demos/{bad}")
        assert r.status_code == 404 and r.json()["error"]["code"] in {"unknown_demo", "not_found"}
    assert c.post("/api/demos/nope/stream").status_code == 404


# --- replay ------------------------------------------------------------------------------------


def test_replay_sends_the_recording_in_order_with_its_timing() -> None:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    services = make_services()
    services.sleep = fake_sleep
    demo = services.demos.get("fiber-cut")
    assert demo is not None
    r = client(services).post("/api/demos/fiber-cut/stream?speed=20")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in r.headers["cache-control"]
    frames = parse_sse(r.text)
    assert [data for _, data in frames] == demo.events
    assert all(name == data["type"] for name, data in frames)
    assert sum(slept) == pytest.approx(demo.recording.duration_ms / 1000 / 20, abs=0.01)
    assert KEEPALIVE in r.text  # the longest pauses are longer than the keep-alive interval


@pytest.mark.parametrize("speed", ["0.5", "21", "fast", "-1"])
def test_replay_speed_is_validated(speed: str) -> None:
    r = client().post(f"/api/demos/fiber-cut/stream?speed={speed}")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    assert r.json()["error"]["fields"][0]["field"] == "speed"


def replay(events: list[ApiEvent], speed: float, keepalive: float) -> tuple[list[float], list[str]]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    async def collect() -> list[str]:
        return [f async for f in replay_frames(events, speed, fake_sleep, keepalive)]

    return slept, asyncio.run(collect())


def timed(*times: int) -> list[ApiEvent]:
    return [envelope(i, "note", "R", t, {"iteration": 1, "text": "x"}) for i, t in enumerate(times)]


def test_replay_pauses_by_the_recorded_gap_divided_by_speed() -> None:
    events = timed(0, 1000, 1000, 4000)
    assert replay(events, 1, 15)[0] == pytest.approx([1.0, 3.0])
    assert replay(events, 4, 15)[0] == pytest.approx([0.25, 0.75])


def test_a_long_pause_is_split_by_keep_alive_comments() -> None:
    slept, frames = replay(timed(0, 3500), 1, 1.0)
    assert slept == pytest.approx([1.0, 1.0, 1.0, 0.5])
    assert frames[0].startswith(":") and frames.count(KEEPALIVE) == 3
    assert sum(f.startswith("event:") for f in frames) == 2


def test_retime_rebuilds_realistic_gaps_and_caps_them() -> None:
    def ev(type_: str, **data: Any) -> ApiEvent:
        return envelope(0, type_, "R", 0, data)

    finished = ev("run_finished", usage={"wall_seconds": 0.1})
    events = [
        ev("run_started"),
        ev("llm_call", latency_ms=1200, wall_ms=3),  # answered from the cache in 3 ms
        ev("scope"),
        ev("tool_call"),
        ev("tool_result", wall_ms=5),  # faster than one step
        ev("tool_call"),
        ev("tool_result", wall_ms=700),
        ev("llm_call", latency_ms=9000, wall_ms=9000),  # one very slow call
        finished,
    ]
    out = retime(events)
    assert [e["t_ms"] for e in out] == [
        0,
        1200,
        1200 + MIN_STEP_MS,
        1200 + 2 * MIN_STEP_MS,
        1200 + 3 * MIN_STEP_MS,
        1200 + 4 * MIN_STEP_MS,
        1200 + 4 * MIN_STEP_MS + 700,
        1200 + 4 * MIN_STEP_MS + 700 + MAX_GAP_MS,
        1200 + 5 * MIN_STEP_MS + 700 + MAX_GAP_MS,
    ]
    assert out[1]["data"]["wall_ms"] == 1200  # what the call took, not what the replay waited
    assert out[-1]["data"]["usage"]["wall_seconds"] == round(out[-1]["t_ms"] / 1000, 2)
    assert events[1]["t_ms"] == 0 and events[1]["data"]["wall_ms"] == 3  # the input is untouched


# --- enrichment ---------------------------------------------------------------------------------


def test_tool_results_carry_what_the_model_saw() -> None:
    events = agent_events()
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert len({e["run_id"] for e in events}) == 1
    assert [e["t_ms"] for e in events] == sorted(e["t_ms"] for e in events)
    for event in events:
        EVENT.validate_python(event)

    by_ref = {e["data"]["ref"]: e["data"] for e in of_type(events, "tool_result")}
    assert [by_ref[f"T{i}"]["tool"] for i in range(1, 8)] == [
        "get_anomalies",
        "get_topology",
        "get_alarms",
        "get_maintenance",
        "get_alarms",
        "get_changes",
        "get_external_events",
    ]
    alarms = by_ref["T3"]
    assert alarms["args"] == WINDOW
    assert alarms["body"].startswith("get_alarms result.\nALM-000001")
    assert alarms["refs"] == [
        {
            "ref": "ALM-000001",
            "kind": "alarm",
            "summary": "critical LINK_LOS on LNK-TUN-01-A raised 09:00, active",
        }
    ]
    assert alarms["n_refs"] == 1 and alarms["duplicate_of"] is None


def test_a_repeated_call_is_marked_and_does_not_shift_the_ones_after_it() -> None:
    by_ref = {e["data"]["ref"]: e["data"] for e in of_type(agent_events(), "tool_result")}
    repeat = by_ref["T5"]
    assert repeat["duplicate_of"] == "T3"
    assert repeat["body"] == "Identical to T3; not run again."
    assert repeat["refs"] == [] and repeat["data"] is None
    # the results after the repeat still carry their own body
    assert by_ref["T6"]["body"].startswith("get_changes result.")
    assert by_ref["T7"]["body"].startswith("get_external_events result.")
    assert by_ref["T4"]["body"].startswith("get_maintenance result.")


def test_run_finished_lists_every_reference_of_the_run() -> None:
    events = agent_events()
    finished = events[-1]
    assert finished["type"] == "run_finished" and finished["data"]["status"] == "finished"
    evidence = finished["data"]["evidence"]
    assert evidence["T3"]["kind"] == "call" and "get_alarms" in evidence["T3"]["summary"]
    assert evidence["ALM-000001"]["kind"] == "alarm"
    assert evidence["MW-0001"]["kind"] == "maintenance"
    assert set(all_refs_of(finished)) <= set(evidence)


def all_refs_of(finished: ApiEvent) -> list[str]:
    report = EVENT.validate_python(finished).data.report  # type: ignore[union-attr]
    return all_refs(report)


def test_tool_data_is_json_safe_and_capped() -> None:
    def rich_tools(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        base = fake_tools(name, args, ctx)
        data = {
            "when": datetime(2026, 9, 2, 10, 0),
            "nan": float("nan"),
            "inf": np.float64("inf"),
            "n": np.int64(7),
            "stamp": pd.Timestamp("2026-09-02T10:00:00Z"),
            "array": np.array([1.0, np.nan, 3.0]),
            "price": Decimal("1.5"),
            "tags": {"b", "a"},
        }
        if name == "get_changes":
            data["rows"] = [{"i": i, "text": "x" * 40} for i in range(5_000)]
        return base.model_copy(update={"data": data})

    events = agent_events(executor=rich_tools)
    json.dumps(events, allow_nan=False)  # raises on NaN, datetimes and numpy values
    results = {
        e["data"]["tool"]: e["data"]
        for e in of_type(events, "tool_result")
        if not e["data"]["duplicate_of"]
    }
    data = results["get_alarms"]["data"]
    assert (
        data["when"] == "2026-09-02T10:00:00+00:00" and data["stamp"] == "2026-09-02T10:00:00+00:00"
    )
    assert data["nan"] is None and data["inf"] is None and data["n"] == 7
    assert data["array"] == [1.0, None, 3.0] and data["price"] == 1.5 and data["tags"] == ["a", "b"]
    assert not results["get_alarms"]["data_truncated"]
    big = results["get_changes"]
    assert big["data_truncated"] and size_of(big["data"]) <= MAX_DATA_BYTES


def test_to_jsonable_and_cap_data() -> None:
    assert to_jsonable(None) is None and to_jsonable(True) is True
    assert to_jsonable(datetime(2026, 1, 1, 12, tzinfo=UTC)) == "2026-01-01T12:00:00+00:00"
    assert to_jsonable(pd.NaT) is None
    assert to_jsonable({1: (1, 2)}) == {"1": [1, 2]}
    assert to_jsonable(object()).startswith("<object")
    huge = {"text": "y" * 100_000, "rows": list(range(100_000))}
    capped, cut = cap_data(huge)
    assert cut and size_of(capped) <= MAX_DATA_BYTES
    assert cap_data({"a": 1}) == ({"a": 1}, False)
    wide = {"rows": [{f"k{i}": "z" * 2_000 for i in range(50)}] * 1_000}
    assert cap_data(wide) == (None, True)  # even 8 rows do not fit


# --- failures ------------------------------------------------------------------------------------


def test_a_crash_becomes_error_events_without_details() -> None:
    def start() -> Iterator[AgentEvent]:
        raise RuntimeError("could not reach postgres://user:hunter2@db/prod")

    events = list(run_events(start, ToolRecorder(fake_tools)))
    assert [e["type"] for e in events] == ["error", "run_finished"]
    assert events[0]["run_id"] == UNKNOWN_RUN
    assert "hunter2" not in json.dumps(events) and "postgres" not in json.dumps(events)
    assert events[1]["data"]["status"] == "error" and events[1]["data"]["report"]["title"]
    for event in events:
        EVENT.validate_python(event)


def test_a_crash_midway_keeps_the_events_before_it() -> None:
    def start() -> Iterator[AgentEvent]:
        yield AgentEvent(type="run_started", run_id="RUN-1", data={"question": "q"})
        raise ValueError("boom")

    events = list(run_events(start, ToolRecorder(fake_tools)))
    assert [e["type"] for e in events] == ["run_started", "error", "run_finished"]
    assert {e["run_id"] for e in events} == {"RUN-1"}


def test_a_failing_conclude_step_still_ends_with_a_valid_run_finished() -> None:
    inner = default_script()

    def script(call: RecordedCall) -> Any:
        if call.purpose == "conclude":
            raise RuntimeError("model unavailable")
        return inner(call)

    events = agent_events(script)
    assert [e["type"] for e in events if e["type"] == "error"] == ["error"]
    assert events[-1]["data"]["status"] == "error"
    for event in events:
        EVENT.validate_python(event)


# --- the live endpoint ----------------------------------------------------------------------------


def test_a_live_investigation_streams_and_is_stored() -> None:
    repo = MemoryRunRepository()
    c = client(make_services(repo=repo))
    r = c.post("/api/investigations/stream", json={"question": QUESTION})

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(r.text)
    events = [data for _, data in frames]
    assert all(name == data["type"] for name, data in frames)
    assert events[0]["type"] == "run_started" and events[-1]["type"] == "run_finished"
    assert events[0]["data"]["asked_at"] == ASKED.isoformat()  # defaults to the dataset's now
    assert [e["seq"] for e in events] == list(range(len(events)))
    for event in events:
        EVENT.validate_python(event)

    run_id = events[0]["run_id"]
    assert repo.events[run_id] == events  # what was streamed is what was stored

    listing = c.get("/api/investigations?limit=5").json()
    assert [row["run_id"] for row in listing] == [run_id]
    row = listing[0]
    assert row["question"] == QUESTION and row["verdict"] == "incident"
    assert row["cause"] == "transport_failure" and row["node_id"] == "LNK-TUN-01-A"
    assert row["confidence"] == "high" and row["trigger"] == "user"
    assert row["llm_calls"] == 5 and row["tool_calls"] == 6

    stored = c.get(f"/api/investigations/{run_id}").json()
    assert stored["events"] == json.loads(json.dumps(events))
    assert stored["report"]["root_cause_node_id"] == "LNK-TUN-01-A" and stored["markdown"]
    assert c.get("/api/investigations/RUN-missing").status_code == 404


def test_asked_at_can_be_earlier_than_the_dataset_now() -> None:
    c = client()
    r = c.post(
        "/api/investigations/stream",
        json={"question": QUESTION, "asked_at": "2026-09-02T10:00:00Z"},
    )
    assert parse_sse(r.text)[0][1]["data"]["asked_at"] == "2026-09-02T10:00:00+00:00"


def test_a_failing_run_is_an_event_not_an_http_error() -> None:
    def broken() -> ScriptedRunner:
        raise RuntimeError("no model")

    services = make_services()
    services.runner_factory = broken
    r = client(services).post("/api/investigations/stream", json={"question": QUESTION})
    assert r.status_code == 200
    types = [name for name, _ in parse_sse(r.text)]
    assert types == ["error", "run_finished"]
    assert cast_repo(services).events == {}


def cast_repo(services: Services) -> MemoryRunRepository:
    assert isinstance(services.repo, MemoryRunRepository)
    return services.repo


def test_a_closed_stream_stops_the_run_and_stores_nothing() -> None:
    repo = MemoryRunRepository()
    services = make_services(repo=repo)
    events = live_events(services, QUESTION, ASKED)
    first = [next(events) for _ in range(4)]
    events.close()  # the client left
    assert repo.events == {}
    assert repo.stopped == [(first[0]["run_id"], "the client disconnected")]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"question": "why?"}, "question"),
        ({"question": "x" * 301}, "question"),
        ({"question": "Why did traffic drop\x00 yesterday?"}, "question"),
        ({"question": "        "}, "question"),
        ({}, "question"),
        ({"question": QUESTION, "asked_at": "yesterday"}, "asked_at"),
    ],
)
def test_live_requests_are_validated_before_anything_runs(body: dict[str, Any], field: str) -> None:
    asked: list[bool] = []
    services = make_services()
    services.runner_factory = lambda: asked.append(True) or ScriptedRunner([])  # type: ignore[func-returns-value]
    r = client(services).post("/api/investigations/stream", json=body)
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "invalid_request" and error["fields"][0]["field"] == field
    assert asked == []


def test_asked_at_cannot_be_after_the_dataset_now() -> None:
    r = client().post(
        "/api/investigations/stream",
        json={"question": QUESTION, "asked_at": "2026-09-03T08:00:01Z"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "asked_at_in_future"


def test_not_json_is_a_validation_error() -> None:
    r = client().post(
        "/api/investigations/stream",
        content=b"question=hello",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422


def test_large_bodies_are_refused() -> None:
    c = client()
    r = c.post("/api/investigations/stream", json={"question": "x" * 20_000})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"

    def chunks() -> Iterator[bytes]:  # no Content-Length: counted as it arrives
        for _ in range(40):
            yield b" " * 1000

    r = c.post("/api/investigations/stream", content=chunks())
    assert r.status_code == 413


# --- limits ---------------------------------------------------------------------------------------


def test_the_daily_limit_returns_429_and_never_starts_a_run() -> None:
    asked: list[bool] = []
    repo = MemoryRunRepository()
    now = datetime.now(UTC)
    repo.user_runs = [now, now]
    services = make_services(repo=repo, live_daily_limit=2)
    services.runner_factory = lambda: asked.append(True) or ScriptedRunner([])  # type: ignore[func-returns-value]
    c = client(services)

    r = c.post("/api/investigations/stream", json={"question": QUESTION})
    assert r.status_code == 429
    assert r.json()["error"] == {
        "code": "daily_limit_reached",
        "message": r.json()["error"]["message"],
        "limit": 2,
        "remaining": 0,
    }
    assert 0 < int(r.headers["retry-after"]) <= 86_401
    assert asked == []
    meta = c.get("/api/meta").json()
    assert meta["live_remaining"] == 0 and meta["live_daily_limit"] == 2


def test_runs_of_earlier_days_do_not_count() -> None:
    repo = MemoryRunRepository()
    repo.user_runs = [datetime(2020, 1, 1, tzinfo=UTC)] * 50
    c = client(make_services(repo=repo, live_daily_limit=1))
    assert c.get("/api/meta").json()["live_remaining"] == 1
    assert c.post("/api/investigations/stream", json={"question": QUESTION}).status_code == 200
    assert c.get("/api/meta").json()["live_remaining"] == 0
    assert c.post("/api/investigations/stream", json={"question": QUESTION}).status_code == 429


def test_a_limit_of_zero_and_a_disabled_live_mode() -> None:
    zero = client(make_services(live_daily_limit=0))
    assert zero.post("/api/investigations/stream", json={"question": QUESTION}).status_code == 429

    off = client(make_services(live_enabled=False))
    r = off.post("/api/investigations/stream", json={"question": QUESTION})
    assert r.status_code == 503 and r.json()["error"]["code"] == "live_disabled"
    meta = off.get("/api/meta").json()
    assert meta["live_enabled"] is False and meta["live_remaining"] == 0
    assert off.post("/api/demos/fiber-cut/stream").status_code == 200  # replays always work


def test_the_day_starts_at_midnight_utc() -> None:
    assert day_start(datetime(2026, 10, 11, 23, 59, tzinfo=UTC)) == datetime(
        2026, 10, 11, tzinfo=UTC
    )


# --- threads, health, meta ------------------------------------------------------------------------


def test_closing_the_sse_response_stops_the_producer() -> None:
    closed = threading.Event()
    produced: list[int] = []

    def events() -> Iterator[ApiEvent]:
        try:
            for i in range(200):
                time.sleep(0.02)
                produced.append(i)
                yield envelope(i, "note", "R", i, {"iteration": 1, "text": "x"})
        finally:
            closed.set()

    async def consume() -> None:
        frames = sse_from_iterator(events, 5.0)
        seen = 0
        async for _ in frames:
            seen += 1
            if seen == 4:
                break
        await frames.aclose()

    asyncio.run(consume())
    assert closed.wait(3)
    assert len(produced) < 200


async def test_a_slow_model_call_does_not_block_other_requests() -> None:
    inner = default_script()

    def script(call: RecordedCall) -> Any:
        if call.purpose == "intake":
            time.sleep(0.8)  # a slow provider
        return inner(call)

    app = create_app(make_services(script=script))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as ac:
        run = asyncio.create_task(
            ac.post("/api/investigations/stream", json={"question": QUESTION})
        )
        await asyncio.sleep(0.2)
        started = time.perf_counter()
        health = await ac.get("/api/health")
        meta = await ac.get("/api/meta")
        waited = time.perf_counter() - started
        assert health.json() == {"status": "ok", "database": True} and meta.status_code == 200
        assert waited < 0.4 and not run.done()
        response = await run
    assert response.status_code == 200
    assert KEEPALIVE in response.text  # the stream stayed alive while the step was slow
    assert parse_sse(response.text)[-1][0] == "run_finished"


def test_health_reports_a_database_that_is_down() -> None:
    services = make_services()
    down = create_engine("sqlite:////no/such/dir/x.db")
    services.engine = lambda: down
    r = client(services).get("/api/health")
    assert r.status_code == 503 and r.json() == {"status": "degraded", "database": False}


def test_meta() -> None:
    meta = (
        client(make_services(live_daily_limit=7, agent_model="gemini:some-model"))
        .get("/api/meta")
        .json()
    )
    assert datetime.fromisoformat(meta["dataset_now"]) == ASKED
    assert meta["step_minutes"] == 15 and meta["timezone"] == "Africa/Tunis"
    assert meta["regions"] == [{"id": "SFX", "name": "Sfax"}, {"id": "TUN", "name": "Grand Tunis"}]
    assert meta["live_enabled"] is True and meta["live_daily_limit"] == 7
    assert meta["live_remaining"] == 7 and meta["model"] == "gemini:some-model"


def test_errors_never_expose_details() -> None:
    class Failing(MemoryRunRepository):
        def count_user_runs_since(self, since: datetime) -> int:
            raise RuntimeError("secret-token in /srv/app/config.py")

    r = client(make_services(repo=Failing()), raise_server_exceptions=False).get("/api/meta")
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal_error", "message": "Something went wrong."}}

    services = make_services()

    def down() -> Any:
        raise OperationalError("SELECT 1", {}, Exception("password=hunter2"))

    services.agent_engine = down
    r = client(services, raise_server_exceptions=False).get("/api/alerts")
    assert r.status_code == 503 and "hunter2" not in r.text
    assert r.json()["error"]["code"] == "database_unavailable"


def test_kpi_requests_are_validated_before_the_database() -> None:
    c = client()
    r = c.get("/api/kpis", params={"entity_type": "site", "metric": "dl_volume_mb"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "entity_id_required"
    r = c.get("/api/kpis", params={"entity_type": "galaxy", "metric": "x"})
    assert r.status_code == 422 and r.json()["error"]["fields"][0]["field"] == "entity_type"
    assert c.get("/api/alerts", params={"limit": 0}).status_code == 422
    assert c.get("/api/alerts", params={"limit": 101}).status_code == 422


def test_cors_is_limited_to_the_configured_origins() -> None:
    c = client(make_services(cors_origins=["https://demo.example.org"]))
    ok = c.get("/api/meta", headers={"Origin": "https://demo.example.org"})
    assert ok.headers["access-control-allow-origin"] == "https://demo.example.org"
    other = c.get("/api/meta", headers={"Origin": "https://evil.example.org"})
    assert "access-control-allow-origin" not in other.headers
    preflight = c.options(
        "/api/investigations/stream",
        headers={
            "Origin": "https://demo.example.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://demo.example.org"
    default = client().get("/api/meta", headers={"Origin": "http://localhost:3000"})
    assert default.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_importing_the_app_connects_to_nothing() -> None:
    code = "import incident_agent.api.app as m; print(m.app.title)"
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://x:y@127.0.0.1:9/none"}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "Network Incident Agent API"


# --- the contract ---------------------------------------------------------------------------------


def test_the_committed_openapi_file_is_current() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == render(), (
        "docs/api/openapi.json is out of date: run `uv run python -m incident_agent.api.openapi`"
    )


def test_the_contract_describes_every_endpoint_and_event() -> None:
    spec = json.loads(render())
    assert set(spec["paths"]) == {
        "/api/ping",
        "/api/health",
        "/api/meta",
        "/api/demos",
        "/api/demos/{demo_id}",
        "/api/demos/{demo_id}/stream",
        "/api/investigations/stream",
        "/api/investigations",
        "/api/investigations/{run_id}",
        "/api/alerts",
        "/api/alerts/{alert_id}/investigate",
        "/api/kpis",
        "/api/topology",
    }
    schemas = spec["components"]["schemas"]
    for name in (
        "RunStartedEvent", "ScopeEvent", "LlmCallEvent", "ToolCallEvent", "ToolResultEvent",
        "NoteEvent", "GateEvent", "ReportEvent", "ErrorEvent", "RunFinishedEvent", "ErrorResponse",
    ):  # fmt: skip
        assert name in schemas
    assert "HTTPValidationError" not in schemas  # errors have one shape
    assert (
        "text/event-stream"
        in spec["paths"]["/api/demos/{demo_id}/stream"]["post"]["responses"]["200"]["content"]
    )
