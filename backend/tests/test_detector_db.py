"""Detector tests that need Postgres (`docker compose up -d`)."""

import pytest
from sqlalchemy import Engine, text

from incident_agent.db.loader import load_world
from incident_agent.detector import DetectorInput, detect
from incident_agent.detector.store import read_input, run_detector
from tests.fixtures_world import make_fixture_world

pytestmark = pytest.mark.db


@pytest.fixture
def loaded(db_engine: Engine) -> None:
    load_world(make_fixture_world(), db_engine)


FIBER_SQL = "SELECT summary, region_ids, severity FROM alerts WHERE 'S-TUN-001' = ANY(entity_ids)"


def test_run_writes_alerts_and_anomalies_with_valid_keys(db_engine: Engine, loaded: None) -> None:
    result, counts = run_detector(db_engine)
    assert counts["alerts"] == len(result.alerts) > 0
    assert counts["anomalies"] == len(result.anomalies) > 0
    with db_engine.connect() as conn:
        n_alerts = conn.execute(text("SELECT count(*) FROM alerts")).scalar_one()
        n_anoms = conn.execute(text("SELECT count(*) FROM anomalies")).scalar_one()
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM anomalies a "
                "LEFT JOIN alerts l ON l.alert_id = a.alert_id WHERE l.alert_id IS NULL"
            )
        ).scalar_one()
        fiber = conn.execute(text(FIBER_SQL)).one()
    assert (n_alerts, n_anoms) == (counts["alerts"], counts["anomalies"])
    assert orphans == 0
    assert "S-TUN-001" in fiber.summary
    assert fiber.region_ids == ["TUN"]
    assert fiber.severity in {"low", "medium", "high"}


def test_database_and_in_memory_runs_agree(db_engine: Engine, loaded: None) -> None:
    from_db = detect(read_input(db_engine))
    in_memory = detect(DetectorInput.from_world(make_fixture_world()))
    assert list(from_db.alerts["summary"]) == list(in_memory.alerts["summary"])
    assert list(from_db.alerts["start_at"]) == list(in_memory.alerts["start_at"])


def test_run_replaces_previous_output(db_engine: Engine, loaded: None) -> None:
    run_detector(db_engine)
    _, counts = run_detector(db_engine)
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alerts")).scalar_one() == counts["alerts"]


def test_agent_ro_can_read_alerts_and_anomalies(
    db_engine: Engine, agent_ro_engine: Engine, loaded: None
) -> None:
    _, counts = run_detector(db_engine)
    with agent_ro_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alerts")).scalar_one() == counts["alerts"]
        assert (
            conn.execute(text("SELECT count(*) FROM anomalies")).scalar_one() == counts["anomalies"]
        )
        assert (
            conn.execute(text("SELECT count(*) FROM alerts WHERE severity = 'high'")).scalar_one()
            >= 1
        )
