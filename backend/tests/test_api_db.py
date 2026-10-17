"""The API against Postgres: the fixture world, the real trace store, the `app` schema."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from incident_agent.api.app import create_app
from incident_agent.api.clients import hash_address
from incident_agent.api.live import day_start, live_events
from incident_agent.api.repository import PgRunRepository
from incident_agent.api.schemas import RunEvent
from incident_agent.api.services import Services
from incident_agent.config import Settings
from tests.api_support import parse_sse
from tests.fixtures_world import NOW, at
from tests.test_agent_db import ASKED, scripted, setup_world
from tests.test_tools_db import EMB

pytestmark = pytest.mark.db

EVENT = TypeAdapter(RunEvent)
QUESTION = "TEST: Why are the sites S-TUN-001 and S-TUN-002 down?"


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


def services(world: Engine, agent_ro_engine: Engine, **settings: Any) -> Services:
    return Services(
        settings=Settings(_env_file=None, **settings),
        engine=lambda: world,
        agent_engine=lambda: agent_ro_engine,
        runner_factory=scripted,
        embedder=EMB,
    )


@pytest.fixture
def api(world: Engine, agent_ro_engine: Engine) -> TestClient:
    return TestClient(create_app(services(world, agent_ro_engine)))


def start_live(c: TestClient) -> list[dict[str, Any]]:
    r = c.post(
        "/api/investigations/stream", json={"question": QUESTION, "asked_at": ASKED.isoformat()}
    )
    assert r.status_code == 200, r.text
    return [data for _, data in parse_sse(r.text)]


# --- live runs and the app schema -------------------------------------------------------------


def test_a_live_run_streams_enriched_events_and_is_stored(
    api: TestClient, world: Engine, agent_ro_engine: Engine
) -> None:
    events = start_live(api)
    for event in events:
        EVENT.validate_python(event)
    assert events[-1]["data"]["status"] == "finished", events[-1]["data"]["issues"]
    run_id = events[0]["run_id"]

    results = {e["data"]["ref"]: e["data"] for e in events if e["type"] == "tool_result"}
    kpi = next(r for r in results.values() if r["tool"] == "query_kpis")
    assert kpi["args"]["entity_ids"] == ["S-TUN-001"] and kpi["body"]
    chart = kpi["data"]["chart"]
    assert chart[0]["entity_id"] == "S-TUN-001" and chart[0]["metric"] == "availability_pct"
    assert min(v for v in chart[0]["values"] if v is not None) < 50  # the outage is in the series
    alarms = next(r for r in results.values() if r["tool"] == "get_alarms")
    assert alarms["refs"][0]["ref"] == "ALM-000001" and alarms["data"]["rows"]
    evidence = events[-1]["data"]["evidence"]
    assert evidence["ALM-000001"]["kind"] == "alarm" and evidence["T1"]["kind"] == "call"

    with world.connect() as conn:
        stored = conn.execute(
            text("SELECT events FROM app.run_events WHERE run_id = :id"), {"id": run_id}
        ).scalar_one()
        row = conn.execute(
            text("SELECT status, trigger FROM app.agent_runs WHERE run_id = :id"), {"id": run_id}
        ).one()
    assert stored == json.loads(json.dumps(events))
    assert (row.status, row.trigger) == ("finished", "user")

    listed = api.get("/api/investigations?limit=3").json()
    assert listed[0]["run_id"] == run_id and listed[0]["cause"] == "transport_failure"
    assert listed[0]["input_tokens"] > 0
    detail = api.get(f"/api/investigations/{run_id}").json()
    assert detail["events"] == stored and detail["markdown"] and detail["issues"] is not None


def test_the_agent_role_cannot_read_the_stored_events(
    api: TestClient, agent_ro_engine: Engine
) -> None:
    start_live(api)
    with agent_ro_engine.connect() as conn, pytest.raises(DBAPIError, match="permission denied"):
        conn.execute(text("SELECT * FROM app.run_events"))


def test_deleting_a_run_deletes_its_events(world: Engine) -> None:
    with world.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.agent_runs (run_id, question, asked_at, trigger, status, "
                "started_at) VALUES ('RUN-T-ev', 'TEST: x', now(), 'user', 'finished', now())"
            )
        )
    repo = PgRunRepository(lambda: world)
    repo.save_events("RUN-T-ev", [{"seq": 0}])
    repo.save_events("RUN-T-ev", [{"seq": 0}, {"seq": 1}])  # saving again replaces
    with world.begin() as conn:
        n = conn.execute(
            text("SELECT jsonb_array_length(events) FROM app.run_events WHERE run_id = 'RUN-T-ev'")
        ).scalar()
        assert n == 2
        conn.execute(text("DELETE FROM app.agent_runs WHERE run_id = 'RUN-T-ev'"))
        left = conn.execute(
            text("SELECT count(*) FROM app.run_events WHERE run_id = 'RUN-T-ev'")
        ).scalar_one()
        assert left == 0


def test_a_closed_stream_marks_the_trace_and_keeps_no_events(
    world: Engine, agent_ro_engine: Engine
) -> None:
    svc = services(world, agent_ro_engine)
    run = live_events(svc, QUESTION, ASKED)
    first = [next(run) for _ in range(5)]
    run.close()
    run_id = first[0]["run_id"]
    with world.connect() as conn:
        row = conn.execute(
            text("SELECT status, error FROM app.agent_runs WHERE run_id = :id"), {"id": run_id}
        ).one()
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.run_events WHERE run_id = :id"), {"id": run_id}
            ).scalar_one()
            == 0
        )
    assert row.status == "error" and "disconnected" in row.error


def used_today(world: Engine) -> int:
    return PgRunRepository(lambda: world).count_user_runs_since(day_start(datetime.now(UTC)))


def test_runs_are_filed_under_a_salted_hash_of_their_client(
    world: Engine, agent_ro_engine: Engine
) -> None:
    svc = services(
        world,
        agent_ro_engine,
        live_daily_limit=1000,
        live_per_client_daily_limit=1,
        client_hash_salt="pepper",
    )
    c = TestClient(create_app(svc))
    mine, other = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}, {"X-Forwarded-For": "203.0.113.8"}
    body = {"question": QUESTION, "asked_at": ASKED.isoformat()}

    first = c.post("/api/investigations/stream", json=body, headers=mine)
    assert first.status_code == 200, first.text
    run_id = parse_sse(first.text)[0][1]["run_id"]
    expected = hash_address("203.0.113.7", svc.settings)
    with world.connect() as conn:
        stored = conn.execute(
            text("SELECT client_hash, trigger FROM app.agent_runs WHERE run_id = :id"),
            {"id": run_id},
        ).one()
        leaked = conn.execute(
            text("SELECT count(*) FROM app.agent_runs WHERE agent_runs::text LIKE '%203.0.113.%'")
        ).scalar_one()
    assert tuple(stored) == (expected, "user") and leaked == 0

    assert c.get("/api/meta", headers=mine).json()["live_client_remaining"] == 0
    assert c.get("/api/meta", headers=other).json()["live_client_remaining"] == 1
    refused = c.post("/api/investigations/stream", json=body, headers=mine)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "client_limit_reached"
    assert c.post("/api/investigations/stream", json=body, headers=other).status_code == 200


def test_the_client_index_exists(world: Engine) -> None:
    with world.connect() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_agent_runs_client'")
        ).scalar_one()
    assert "(client_hash, started_at)" in definition


def test_the_daily_limit_counts_todays_user_runs(world: Engine, agent_ro_engine: Engine) -> None:
    svc = services(
        world,
        agent_ro_engine,
        live_daily_limit=used_today(world) + 1,
        live_per_client_daily_limit=1000,  # this test is about the shared limit
    )
    c = TestClient(create_app(svc))
    assert c.get("/api/meta").json()["live_remaining"] == 1
    start_live(c)
    assert c.get("/api/meta").json()["live_remaining"] == 0
    r = c.post("/api/investigations/stream", json={"question": QUESTION})
    assert r.status_code == 429 and r.json()["error"]["code"] == "daily_limit_reached"

    before = used_today(world)
    with world.begin() as conn:  # a run of another trigger, or of yesterday, does not count
        conn.execute(
            text(
                "INSERT INTO app.agent_runs (run_id, question, asked_at, trigger, status, "
                "started_at) VALUES ('RUN-T-old', 'TEST: old', now(), 'user', 'finished', :old), "
                "('RUN-T-alert', 'TEST: alert', now(), 'alert', 'finished', now())"
            ),
            {"old": datetime.now(UTC) - timedelta(days=2)},
        )
    assert used_today(world) == before


# --- the network ------------------------------------------------------------------------------


def test_meta_and_health(api: TestClient) -> None:
    assert api.get("/api/health").json() == {"status": "ok", "database": True}
    meta = api.get("/api/meta").json()
    assert datetime.fromisoformat(meta["dataset_now"]) == NOW
    assert [r["id"] for r in meta["regions"]] == ["SFX", "TUN"]
    assert meta["step_minutes"] == 15 and meta["live_enabled"] is True


def test_alerts_newest_first(api: TestClient) -> None:
    rows = api.get("/api/alerts").json()
    assert [r["id"] for r in rows] == ["ALR-T3", "ALR-T1"]
    assert rows[1]["region_ids"] == ["TUN"] and rows[1]["severity"] == "high"
    assert rows[1]["summary"].startswith("Traffic and availability drop")
    assert [r["id"] for r in api.get("/api/alerts?limit=1").json()] == ["ALR-T3"]


def kpis(api: TestClient, **params: Any) -> Any:
    return api.get("/api/kpis", params=params)


def test_kpis_for_a_site_during_an_outage(api: TestClient) -> None:
    r = kpis(
        api, entity_type="site", entity_id="S-SFX-001", metric="availability_pct",
        start=at(3, 0).isoformat(), end=at(3, 4).isoformat(),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    series = r.json()
    assert series["entity_id"] == "S-SFX-001" and series["unit"] == "%"
    assert series["step_minutes"] == 15 and len(series["values"]) == len(series["baseline"])
    assert datetime.fromisoformat(series["start"]) == at(3, 0)
    assert series["baseline_available"] and not series["clamped_to_now"]
    assert min(v for v in series["values"] if v is not None) < 50
    dev = series["deviation"]
    assert dev["direction"] == "below" and not dev["ongoing"]
    assert abs(datetime.fromisoformat(dev["onset"]) - at(3, 1)) <= timedelta(minutes=15)


def test_kpis_never_show_the_future(api: TestClient) -> None:
    r = kpis(
        api, entity_type="region", entity_id="TUN", metric="dl_volume_mb",
        start=at(3, 6).isoformat(), end=at(3, 20).isoformat(),
    )  # fmt: skip
    series = r.json()
    assert series["clamped_to_now"] and datetime.fromisoformat(series["end"]) == NOW
    last = datetime.fromisoformat(series["start"]) + timedelta(
        minutes=series["step_minutes"] * (len(series["values"]) - 1)
    )
    assert last <= NOW
    # without a window: the 24 hours up to the dataset's now
    day = kpis(api, entity_type="national", metric="dl_volume_mb").json()
    assert datetime.fromisoformat(day["end"]) == NOW and len(day["values"]) == 97
    assert day["entity_id"] == "NATIONAL"
    # a start after now has nothing to show
    late = kpis(
        api, entity_type="national", metric="dl_volume_mb",
        start=(NOW + timedelta(hours=1)).isoformat(),
    )  # fmt: skip
    assert late.status_code == 422


def test_kpis_are_downsampled_and_limited_to_a_week(api: TestClient) -> None:
    r = kpis(
        api, entity_type="site", entity_id="S-TUN-001", metric="active_users",
        start=at(0, 0).isoformat(), end=NOW.isoformat(),
    )  # fmt: skip
    series = r.json()
    assert len(series["values"]) <= 200 and series["step_minutes"] == 30
    long = kpis(
        api, entity_type="national", metric="active_users",
        start=(NOW - timedelta(days=8)).isoformat(),
    )  # fmt: skip
    assert long.status_code == 422 and "7 days" in long.json()["error"]["message"]


def test_kpis_local_time_core_nodes_and_errors(api: TestClient) -> None:
    local = kpis(
        api, entity_type="core_node", entity_id="CORE-DNS-01", metric="resolution_ms",
        start="2026-09-04 02:00", end="2026-09-04 04:00",
    )  # fmt: skip
    series = local.json()
    assert datetime.fromisoformat(series["start"]) == at(3, 2) and series["unit"] == "ms"
    assert len(series["values"]) == 9

    missing = kpis(api, entity_type="site", entity_id="S-NOPE-1", metric="active_users")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "unknown_entity"
    bad = kpis(api, entity_type="site", entity_id="S-TUN-001", metric="happiness")
    assert bad.status_code == 422 and "happiness" in bad.json()["error"]["message"]
    wrong = kpis(api, entity_type="site", entity_id="LNK-TUN-01-A", metric="active_users")
    assert wrong.status_code == 404 and "transport_link" in wrong.json()["error"]["message"]


def test_topology_of_a_site_a_link_and_a_cell(api: TestClient) -> None:
    site = api.get("/api/topology", params={"node_id": "S-TUN-001"}).json()
    assert [n["id"] for n in site["chain"]] == [
        "S-TUN-001", "LNK-TUN-01-A", "AGG-TUN-01", "CORE-UPF-01",
    ]  # fmt: skip
    assert [n["id"] for n in site["siblings"]] == ["S-TUN-002"] and site["n_children"] == 0
    assert [n["id"] for n in site["shared_core"]] == ["CORE-AMF-01", "CORE-DNS-01"]
    assert site["node"]["type"] == "site" and site["node"]["region_id"] == "TUN"

    link = api.get("/api/topology", params={"node_id": "lnk-tun-01-a"}).json()
    assert [n["id"] for n in link["children"]] == ["S-TUN-001", "S-TUN-002"]
    assert link["n_sites_below"] == 2 and [n["id"] for n in link["siblings"]] == ["LNK-TUN-01-B"]

    cell = api.get("/api/topology", params={"node_id": "C-TUN-001-1"}).json()
    assert cell["node"]["id"] == "S-TUN-001" and "cell of S-TUN-001" in cell["note"]

    core = api.get("/api/topology", params={"node_id": "CORE-DNS-01"}).json()
    assert core["chain"][0]["id"] == "CORE-DNS-01" and core["shared_core"] == []


def test_topology_errors(api: TestClient) -> None:
    unknown = api.get("/api/topology", params={"node_id": "S-TUN-0011"})
    assert unknown.status_code == 404 and "S-TUN-001" in unknown.json()["error"]["message"]
    region = api.get("/api/topology", params={"node_id": "TUN"})
    assert region.status_code == 404 and region.json()["error"]["code"] == "not_a_node"
    assert api.get("/api/topology").status_code == 422
