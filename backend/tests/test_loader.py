"""Loader tests that need Postgres (`docker compose up -d`)."""

import math
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from incident_agent.config import get_settings
from incident_agent.db.loader import load_world
from incident_agent.simulator.world import World
from tests.fixtures_world import at, make_fixture_world

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="module")
def world() -> World:
    return make_fixture_world()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    eng = create_engine(get_settings().database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def agent_engine() -> Iterator[Engine]:
    url = make_url(get_settings().database_url).set(username="agent_ro", password="agent_ro")
    eng = create_engine(url)
    yield eng
    eng.dispose()


def expected_counts(world: World) -> dict[str, int]:
    return {name: len(df) for name, df in world.tables().items()}


def table_counts(engine: Engine, world: World) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            name: conn.execute(
                text(f"SELECT count(*) FROM {'gt' if name == 'scenarios' else 'public'}.{name}")
            ).scalar_one()
            for name in world.tables()
        }


def test_load_world_counts(engine: Engine, world: World) -> None:
    counts = load_world(world, engine)
    assert counts == expected_counts(world)
    assert table_counts(engine, world) == expected_counts(world)


def test_reload_is_idempotent(engine: Engine, world: World) -> None:
    load_world(world, engine)
    load_world(world, engine)
    assert table_counts(engine, world) == expected_counts(world)


def test_values_round_trip(engine: Engine, world: World) -> None:
    load_world(world, engine)
    with engine.connect() as conn:
        cleared = conn.execute(
            text("SELECT cleared_at FROM alarms WHERE alarm_id = 'ALM-000003'")
        ).scalar_one()
        scenario = conn.execute(
            text(
                "SELECT affected_node_ids, evidence, start_at, is_incident "
                "FROM gt.scenarios WHERE scenario_id = 'SCN-001'"
            )
        ).one()
        attrs = conn.execute(
            text("SELECT attrs FROM nodes WHERE node_id = 'LNK-TUN-01-A'")
        ).scalar_one()
    assert cleared is None
    assert scenario.affected_node_ids == ["LNK-TUN-01-A"]
    assert scenario.evidence[0] == {"table": "alarms", "id": "ALM-000001"}
    assert scenario.start_at == world.scenarios.loc[0, "start_at"]
    assert scenario.is_incident is True
    assert attrs == {"medium": "fiber"}


def test_agent_ro_can_read_public_but_not_gt(
    engine: Engine, agent_engine: Engine, world: World
) -> None:
    load_world(world, engine)
    with agent_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM public.cell_kpis")).scalar_one() > 0
        assert conn.execute(text("SELECT count(*) FROM public.region_kpis_15m")).scalar_one() > 0
    with agent_engine.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("SELECT * FROM gt.scenarios"))


def test_region_kpis_view(engine: Engine, world: World) -> None:
    load_world(world, engine)
    kpis = world.cell_kpis.merge(world.cells, on="cell_id").merge(
        world.nodes[["node_id", "region_id"]], left_on="site_id", right_on="node_id"
    )
    with engine.connect() as conn:
        n_rows = conn.execute(text("SELECT count(*) FROM region_kpis_15m")).scalar_one()
        assert n_rows == kpis.groupby(["region_id", "ts"]).ngroups

        # One hour into the fiber cut, two TUN sites (6 cells) are down.
        cut_ts = world.scenarios.loc[0, "start_at"] + pd.Timedelta(hours=1)
        row = conn.execute(
            text(
                "SELECT dl_volume_mb, min_availability_pct, cells_down, latency_ms, "
                "rrc_success_pct FROM region_kpis_15m WHERE region_id = 'TUN' AND ts = :ts"
            ),
            {"ts": cut_ts.to_pydatetime()},
        ).one()
        tun_now = kpis[(kpis["region_id"] == "TUN") & (kpis["ts"] == cut_ts)]
        assert row.dl_volume_mb == pytest.approx(tun_now["dl_volume_mb"].sum())
        assert row.min_availability_pct == 0
        assert row.cells_down == 6
        assert 30 < row.latency_ms < 100
        assert 99 < row.rrc_success_pct < 100


def test_down_cells_have_null_quality_kpis(engine: Engine, world: World) -> None:
    load_world(world, engine)
    down = world.cell_kpis["availability_pct"] == 0
    with engine.connect() as conn:
        null_rows = conn.execute(
            text(
                "SELECT count(*) FROM cell_kpis WHERE rrc_success_pct IS NULL "
                "AND drop_rate_pct IS NULL AND latency_ms IS NULL AND availability_pct = 0"
            )
        ).scalar_one()
        any_null = conn.execute(
            text(
                "SELECT count(*) FROM cell_kpis WHERE availability_pct > 0 AND "
                "(rrc_success_pct IS NULL OR drop_rate_pct IS NULL OR latency_ms IS NULL)"
            )
        ).scalar_one()
        volumes = conn.execute(
            text("SELECT max(dl_volume_mb) FROM cell_kpis WHERE availability_pct = 0")
        ).scalar_one()
    assert null_rows == down.sum() > 0
    assert any_null == 0
    assert volumes == 0


def test_view_handles_a_fully_down_region(engine: Engine, world: World) -> None:
    load_world(world, engine)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT dl_volume_mb, cells_down, latency_ms, drop_rate_pct, rrc_success_pct "
                "FROM region_kpis_15m WHERE region_id = 'SFX' AND ts = :ts"
            ),
            {"ts": at(3, 1.5)},
        ).one()
        up = conn.execute(
            text("SELECT latency_ms FROM region_kpis_15m WHERE region_id = 'SFX' AND ts = :ts"),
            {"ts": at(3, 5)},
        ).scalar_one()
    assert row.cells_down == 6
    assert row.dl_volume_mb == 0
    assert row.latency_ms is None and row.drop_rate_pct is None and row.rrc_success_pct is None
    assert up is not None and not math.isnan(up)


def test_loader_rejects_nan_in_non_nullable_float(engine: Engine, world: World) -> None:
    bad = world.cell_kpis.copy()
    bad.loc[0, "dl_volume_mb"] = float("nan")
    broken = replace(world, cell_kpis=bad)
    with pytest.raises(ValueError, match="not nullable"):
        load_world(broken, engine)
