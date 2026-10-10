"""Preparing an evaluation database on a tiny world, and running a case against it."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from incident_agent.config import Settings
from incident_agent.evals.cases import load_planned_cases, load_topology
from incident_agent.evals.prepare import DbTargets, loaded_seed, prepare_database, resolve_targets
from incident_agent.evals.rundir import RunDir
from incident_agent.evals.runner import RunOptions, execute_run
from incident_agent.llm.testing import ScriptedRunner
from incident_agent.llm.types import ToolCall
from tests.agent_support import make_report, script_for
from tests.fixtures_world import make_fixture_world
from tests.test_tools_db import EMB

pytestmark = pytest.mark.db

SEED = 0  # what tests/fixtures_world.py writes into dataset_meta
DB_NAME = "incident_agent_test_evalprep"


@pytest.fixture(scope="module")
def targets(test_database_url: str) -> Iterator[DbTargets]:
    settings = Settings(_env_file=None, database_url=test_database_url)  # type: ignore[call-arg]
    found = resolve_targets(SEED, database=DB_NAME, settings=settings)
    admin = create_engine(found.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
    yield found
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture(scope="module")
def prepared(targets: DbTargets) -> Iterator[Engine]:
    logs: list[str] = []
    report = prepare_database(
        targets,
        SEED,
        world_builder=lambda _seed: make_fixture_world(),
        embedder=EMB,
        log=logs.append,
    )
    assert report.created and report.world_loaded and report.detector_run
    engine = create_engine(targets.owner_url)
    yield engine
    engine.dispose()


def test_targets_name_one_database_per_seed(test_database_url: str) -> None:
    settings = Settings(_env_file=None, database_url=test_database_url)  # type: ignore[call-arg]
    dev = make_url(test_database_url).database
    assert resolve_targets(42, settings=settings).name == dev
    other = resolve_targets(7, settings=settings)
    assert other.name == "incident_agent_eval_s7"
    assert other.agent_url.username == "agent_ro" and other.owner_url.username != "agent_ro"
    assert other.admin_url.database == dev


def test_prepare_creates_loads_detects_and_ingests(targets: DbTargets, prepared: Engine) -> None:
    assert loaded_seed(prepared) == "0"
    with prepared.connect() as conn:
        counts = {
            t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
            for t in ("nodes", "cell_kpis", "alarms", "alerts", "anomalies", "runbook_chunks")
        }
        scenarios = conn.execute(text("SELECT count(*) FROM gt.scenarios")).scalar_one()
    assert all(n > 0 for n in counts.values()) and scenarios == 5


def test_the_agent_role_reads_the_world_but_not_the_labels(
    targets: DbTargets, prepared: Engine
) -> None:
    agent = create_engine(targets.agent_url)
    try:
        with agent.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM alarms")).scalar_one() > 0
            assert conn.execute(text("SELECT count(*) FROM runbook_chunks")).scalar_one() > 0
            with pytest.raises(ProgrammingError):
                conn.execute(text("SELECT count(*) FROM gt.scenarios"))
    finally:
        agent.dispose()


def test_prepare_is_repeatable_and_does_not_reload(targets: DbTargets, prepared: Engine) -> None:
    report = prepare_database(
        targets,
        SEED,
        world_builder=lambda _seed: pytest.fail("rebuilt"),
        embedder=EMB,
        log=lambda _m: None,
    )
    assert not report.created and not report.world_loaded and not report.detector_run
    assert report.alerts > 0 and report.rows["scenarios"] == 5


def test_prepare_refuses_to_replace_another_seed(targets: DbTargets, prepared: Engine) -> None:
    with pytest.raises(RuntimeError, match="holds the world of seed 0"):
        prepare_database(targets, 5, embedder=EMB, log=lambda _m: None)


def test_cases_carry_when_their_evidence_became_visible(prepared: Engine) -> None:
    cases = {c.case.scenario_id: c for c in load_planned_cases(prepared, SEED)}
    assert len(cases) == 5
    assert all(c.case.case_id == f"s0-{c.case.scenario_id}-q0" for c in cases.values())
    assert all(c.case.split == "test" for c in cases.values())
    fiber = cases["SCN-001"]
    assert fiber.truth.kind == "fiber_cut" and fiber.truth.evidence
    with prepared.connect() as conn:
        raised = {
            r.alarm_id: r.raised_at
            for r in conn.execute(text("SELECT alarm_id, raised_at FROM alarms"))
        }
    alarms = [r for r in fiber.truth.evidence if r["table"] == "alarms"]
    assert alarms
    for row in alarms:
        assert datetime.fromisoformat(row["visible_from"]) == raised[row["id"]]
    maintenance = [r for r in cases["SCN-003"].truth.evidence if r["table"] == "maintenance"]
    assert maintenance and all(r["visible_from"] is None for r in maintenance)


def test_topology_has_the_dependency_tree(prepared: Engine) -> None:
    topo = load_topology(prepared)
    assert topo.ancestors("S-TUN-001") == ["LNK-TUN-01-A", "AGG-TUN-01", "CORE-UPF-01"]
    assert topo.parents["CORE-DNS-01"] is None


def test_a_case_runs_end_to_end_and_a_rerun_skips_it(
    targets: DbTargets, prepared: Engine, tmp_path: Path
) -> None:
    turn = [
        ToolCall(name="get_alarms", args={"start": "2026-09-02 08:00", "end": "2026-09-02 12:00"})
    ]
    script = script_for([turn, "enough"], make_report())
    opts = RunOptions(
        name="tiny",
        seed=SEED,
        only=["SCN-001"],
        database=DB_NAME,
        runs_dir=tmp_path,
        cache_mode="replay",
    )
    runner = ScriptedRunner(script)
    logs: list[str] = []
    result = execute_run(opts, runner=runner, sleep=lambda _s: None, log=logs.append)
    assert result.executed == ["s0-SCN-001-q0"] and result.stopped is None
    run = RunDir("tiny", tmp_path)
    assert run.case_state("s0-SCN-001-q0") == "done"
    meta = run.read_meta()
    assert meta is not None and meta.seed == SEED and meta.split == "test"
    assert meta.cases_total == 5 and meta.database == DB_NAME
    assert run.read_topology().ancestors("S-TUN-001")
    again = execute_run(opts, runner=ScriptedRunner([]), sleep=lambda _s: None, log=logs.append)
    assert again.executed == [] and again.skipped_done == ["s0-SCN-001-q0"]
    other = RunOptions(**{**opts.__dict__, "variant": "no-gate"})
    with pytest.raises(ValueError, match="already exists with other settings"):
        execute_run(other, runner=ScriptedRunner([]), log=logs.append)
