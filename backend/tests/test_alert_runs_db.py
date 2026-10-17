"""Alert-triggered investigations on the fixture world: questions, the webhook, the CLI."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from incident_agent.api import autopilot
from incident_agent.api.alert_runs import alert_question, pending_alerts
from incident_agent.api.app import create_app
from incident_agent.api.live import day_start
from incident_agent.api.repository import PgRunRepository
from incident_agent.api.services import Services
from incident_agent.config import Settings
from tests.fixtures_world import NOW, at
from tests.test_agent_db import scripted, setup_world
from tests.test_tools_db import EMB

pytestmark = pytest.mark.db

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


def clear_alert_runs(world: Engine) -> None:
    with world.begin() as conn:
        conn.execute(text("DELETE FROM app.agent_runs WHERE alert_id LIKE 'ALR-T%'"))


@pytest.fixture(autouse=True)
def no_alert_runs(world: Engine) -> Iterator[None]:
    clear_alert_runs(world)
    yield
    clear_alert_runs(world)


class Setup:
    """Services on the test database; counts how often a model would have been asked."""

    def __init__(self, world: Engine, agent_ro_engine: Engine, **settings: Any) -> None:
        self.world = world
        self.runners = 0
        self.services = Services(
            settings=Settings(
                _env_file=None,
                **{"alert_webhook_token": TOKEN, "alert_daily_limit": 50, **settings},
            ),
            engine=lambda: world,
            agent_engine=lambda: agent_ro_engine,
            runner_factory=self.runner,
            embedder=EMB,
        )

    def runner(self) -> Any:
        self.runners += 1
        return scripted()

    @property
    def client(self) -> TestClient:
        return TestClient(create_app(self.services))

    def run_rows(self) -> list[tuple[str, str, str]]:
        with self.world.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT alert_id, trigger, status FROM app.agent_runs "
                    "WHERE alert_id LIKE 'ALR-T%' ORDER BY started_at"
                )
            )
            return [(r.alert_id, r.trigger, r.status) for r in rows]

    def used_today(self) -> int:
        return PgRunRepository(lambda: self.world).count_alert_runs_since(
            day_start(datetime.now(UTC))
        )


@pytest.fixture
def setup(world: Engine, agent_ro_engine: Engine) -> Setup:
    return Setup(world, agent_ro_engine)


def insert_anomaly(
    world: Engine, anomaly_id: str, alert_id: str, entity: str, start: datetime
) -> None:
    with world.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO anomalies (anomaly_id, alert_id, entity_type, entity_id, region_id, "
                "metric, direction, start_at, end_at, n_steps, peak_z, baseline_value, "
                "observed_value) VALUES (:a, :al, 'site', :e, 'TUN', 'active_users', 'drop', :s, "
                ":s, 4, -9.0, 100.0, 10.0)"
            ),
            {"a": anomaly_id, "al": alert_id, "e": entity, "s": start},
        )


# --- the question -------------------------------------------------------------------------------


def test_the_question_of_an_alert(world: Engine, agent_ro_engine: Engine) -> None:
    q = alert_question(agent_ro_engine, "ALR-T1", NOW)
    assert q is not None
    assert q.asked_at == at(1, 19)  # one hour after the start, not the alert's end
    assert q.question == (
        "Detector alert ALR-T1 at 19:00: traffic and availability dropping at "
        "S-TUN-001 and S-TUN-002 (Grand Tunis). What is causing it?"
    )


def test_an_anomaly_that_starts_later_is_not_named(world: Engine, agent_ro_engine: Engine) -> None:
    insert_anomaly(world, "ANM-T9", "ALR-T1", "S-TUN-003", at(1, 20))
    try:
        q = alert_question(agent_ro_engine, "ALR-T1", NOW)
        assert q is not None and "S-TUN-003" not in q.question
        assert "active users" not in q.question
    finally:
        with world.begin() as conn:
            conn.execute(text("DELETE FROM anomalies WHERE anomaly_id = 'ANM-T9'"))


def test_the_question_is_asked_at_now_for_an_alert_that_just_started(
    world: Engine, agent_ro_engine: Engine
) -> None:
    just_after = at(3, 1) + timedelta(minutes=20)
    q = alert_question(agent_ro_engine, "ALR-T3", just_after)
    assert q is not None and q.asked_at == just_after
    assert "S-SFX-001 (Sfax)" in q.question


def test_unknown_and_future_alerts_have_no_question(world: Engine, agent_ro_engine: Engine) -> None:
    assert alert_question(agent_ro_engine, "ALR-NOPE", NOW) is None
    assert alert_question(agent_ro_engine, "ALR-T3", at(3, 0.5)) is None  # starts at 01:00


def test_an_alert_without_visible_anomalies_falls_back_to_its_regions_and_metrics(
    world: Engine, agent_ro_engine: Engine
) -> None:
    with world.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, start_at, end_at, region_ids, entity_ids, metrics, "
                "severity, score, n_anomalies, summary) VALUES ('ALR-T9', :s, :e, ARRAY['TUN'], "
                "ARRAY['S-TUN-003'], ARRAY['dl_volume_mb'], 'low', 5, 1, 'x')"
            ),
            {"s": at(2, 0), "e": at(2, 1)},
        )
    try:
        q = alert_question(agent_ro_engine, "ALR-T9", NOW)
        assert q is not None
        assert q.question == (
            "Detector alert ALR-T9 at 01:00: abnormal traffic in Grand Tunis. What is causing it?"
        )
    finally:
        with world.begin() as conn:
            conn.execute(text("DELETE FROM alerts WHERE alert_id = 'ALR-T9'"))


# --- the webhook --------------------------------------------------------------------------------


def test_the_webhook_stores_a_run_that_the_run_view_and_the_alert_list_show(
    setup: Setup,
) -> None:
    client = setup.client
    r = client.post("/api/alerts/ALR-T1/investigate", headers=AUTH)

    assert r.status_code == 200, r.text
    body = r.json()
    run = body["run"]
    assert body["created"] is True and run["status"] == "finished", run
    assert run["trigger"] == "alert" and run["alert_id"] == "ALR-T1"
    assert setup.run_rows() == [("ALR-T1", "alert", "finished")]

    detail = client.get(f"/api/investigations/{run['run_id']}").json()
    assert detail["alert_id"] == "ALR-T1" and detail["events"][0]["data"]["trigger"] == "alert"
    assert detail["events"][-1]["type"] == "run_finished"
    assert detail["question"].startswith("Detector alert ALR-T1 at 19:00")

    alerts = {a["id"]: a for a in client.get("/api/alerts").json()}
    assert alerts["ALR-T1"]["run_id"] == run["run_id"] and alerts["ALR-T3"]["run_id"] is None
    listed = client.get("/api/investigations").json()
    assert next(x for x in listed if x["run_id"] == run["run_id"])["alert_id"] == "ALR-T1"

    again = client.post("/api/alerts/ALR-T1/investigate", headers=AUTH)
    assert again.json()["created"] is False and again.json()["run"]["run_id"] == run["run_id"]
    assert setup.runners == 1 and len(setup.run_rows()) == 1


def test_the_webhook_refuses_unknown_alerts_and_bad_tokens(setup: Setup) -> None:
    client = setup.client
    assert client.post("/api/alerts/ALR-NOPE/investigate", headers=AUTH).status_code == 404
    assert client.post("/api/alerts/ALR-T1/investigate").status_code == 401
    assert setup.runners == 0 and setup.run_rows() == []


def test_the_daily_limit_counts_alert_runs_in_the_database(
    world: Engine, agent_ro_engine: Engine
) -> None:
    probe = Setup(world, agent_ro_engine)
    capped = Setup(world, agent_ro_engine, alert_daily_limit=probe.used_today() + 1)
    client = capped.client
    assert client.post("/api/alerts/ALR-T1/investigate", headers=AUTH).status_code == 200
    r = client.post("/api/alerts/ALR-T3/investigate", headers=AUTH)
    assert r.status_code == 429 and r.json()["error"]["code"] == "alert_limit_reached"
    assert capped.runners == 1


# --- the command line ---------------------------------------------------------------------------


def test_pending_lists_alerts_without_a_run_and_calls_no_model(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    assert autopilot.main(["pending"], setup.services) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [line.split()[0] for line in lines] == ["ALR-T3", "ALR-T1"]  # newest first
    assert "[medium]" in lines[0] and "asked at 2026-09-04 02:00: Detector alert ALR-T3" in lines[0]

    autopilot.main(["pending", "--min-severity", "high"], setup.services)
    assert [x.split()[0] for x in capsys.readouterr().out.strip().splitlines()] == ["ALR-T1"]
    autopilot.main(["pending", "--limit", "1"], setup.services)
    assert [x.split()[0] for x in capsys.readouterr().out.strip().splitlines()] == ["ALR-T3"]
    assert setup.runners == 0 and setup.run_rows() == []

    setup.client.post("/api/alerts/ALR-T3/investigate", headers=AUTH)  # now it has a run
    assert [p.alert_id for p in pending_alerts(setup.services, 10, "low")] == ["ALR-T1"]


def test_a_dry_run_prints_the_question_and_starts_nothing(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    assert autopilot.main(["run", "ALR-T1", "--dry-run"], setup.services) == 0
    out = capsys.readouterr().out
    assert "ALR-T1 asked at 2026-09-02 19:00: Detector alert ALR-T1 at 19:00" in out
    assert autopilot.main(["sweep", "--dry-run", "--limit", "5"], setup.services) == 0
    assert capsys.readouterr().out.count("Detector alert") == 2  # one line per pending alert
    assert autopilot.main(["run", "ALR-NOPE", "--dry-run"], setup.services) == 1
    assert setup.runners == 0 and setup.run_rows() == []


def test_run_investigates_one_alert_and_prints_the_verdict(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    assert autopilot.main(["run", "ALR-T1"], setup.services) == 0
    out = capsys.readouterr().out
    assert "(started) status=finished verdict=incident cause=transport_failure" in out
    assert "node=LNK-TUN-01-A" in out
    assert autopilot.main(["run", "ALR-T1"], setup.services) == 0
    assert "(already investigated)" in capsys.readouterr().out
    assert setup.runners == 1


def test_sweep_respects_its_limit(setup: Setup, capsys: pytest.CaptureFixture[str]) -> None:
    assert autopilot.main(["sweep", "--limit", "1", "--min-severity", "low"], setup.services) == 0
    assert setup.run_rows() == [("ALR-T3", "alert", "finished")]  # the newest one
    assert capsys.readouterr().out.count("ALR-T3") == 1
    assert setup.runners == 1


def test_sweep_stops_when_the_daily_limit_is_reached(
    world: Engine, agent_ro_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    limit = Setup(world, agent_ro_engine).used_today() + 1
    capped = Setup(world, agent_ro_engine, alert_daily_limit=limit)
    autopilot.main(["sweep", "--limit", "3", "--min-severity", "low"], capped.services)
    out = capsys.readouterr().out
    assert capped.runners == 1 and len(capped.run_rows()) == 1
    assert "limit" in out and "stopping" in out
