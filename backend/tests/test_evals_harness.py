"""The evaluation harness without a database or a model: ordering, resume, quota handling, files,
variants and the results report."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from incident_agent.agent.config import AgentConfig
from incident_agent.agent.state import LLMStep
from incident_agent.agent.types import ToolContext
from incident_agent.config import Settings
from incident_agent.evals.cases import (
    PlannedCase,
    interleave,
    make_case_id,
    parse_only,
    select_cases,
    split_of,
    stratified,
)
from incident_agent.evals.prepare import resolve_targets
from incident_agent.evals.report import write_report
from incident_agent.evals.rundir import RunDir, RunMeta
from incident_agent.evals.runner import (
    VARIANTS,
    QuotaExhausted,
    RunOptions,
    VariantUnavailable,
    _check_or_create_meta,
    agent_config_for,
    executor_for,
    get_variant,
    infra_failure,
    progress_line,
    run_batch,
    run_case,
)
from incident_agent.evals.summary import load_scored_run, summary_json, summary_lines
from incident_agent.evals.types import CaseArtifact, FindingGrade, ReportGrade
from incident_agent.llm.testing import RecordedCall, ScriptedRunner
from incident_agent.llm.types import MalformedOutput, ToolCall
from tests.agent_support import REFERENCE, WINDOW, fake_tools, make_report, script_for
from tests.evals_support import (
    ASKED_AT,
    TOPOLOGY,
    make_artifact,
    make_planned,
    make_result,
    make_truth,
)

RIGHT = {"impact_start": "2026-09-02 17:00", "root_cause_time": "2026-09-02 17:00"}
CHECKS = [
    [ToolCall(name=t, args=dict(WINDOW)) for t in ("get_alarms", "get_maintenance", "get_changes")],
    [ToolCall(name="get_external_events", args=dict(WINDOW))],
]


# --- case ids, ordering, selection ------------------------------------------------------------


def test_ids_and_splits() -> None:
    assert make_case_id(42, "SCN-021", 0) == "s42-SCN-021-q0"
    assert split_of(42) == "dev" and split_of(7) == "test" and split_of(1) == "test"


def test_interleave_is_round_robin() -> None:
    assert interleave([[1, 2, 3], [10], [20, 21]]) == [1, 10, 20, 2, 21, 3]
    assert interleave([]) == []


def _world() -> list[PlannedCase]:
    out: list[PlannedCase] = []
    n = 0
    for kind in ("fiber_cut", "power_outage", "congestion"):
        for diff in ("easy", "easy", "medium", "hard"):
            n += 1
            out.append(make_planned(f"SCN-{n:03d}", kind, diff))
    return out


def test_stratified_order_covers_every_kind_before_repeating() -> None:
    ordered = stratified(_world())
    assert len(ordered) == 12
    assert {c.truth.kind for c in ordered[:3]} == {"fiber_cut", "power_outage", "congestion"}
    assert {c.truth.kind for c in ordered[3:6]} == {"fiber_cut", "power_outage", "congestion"}
    # inside a kind the difficulties alternate rather than all easy cases first
    first_kind = [c.truth.difficulty for c in ordered if c.truth.kind == "congestion"]
    assert first_kind[:3] == ["easy", "medium", "hard"]


def test_stratified_order_is_deterministic_and_input_order_independent() -> None:
    world = _world()
    assert [c.case_id for c in stratified(world)] == [c.case_id for c in stratified(world[::-1])]


def test_select_by_scenario_or_case_id_and_unknown_names_fail() -> None:
    world = stratified(_world())
    picked = select_cases(world, ["SCN-003", "s42-SCN-001-q0"])
    assert {c.case_id for c in picked} == {"s42-SCN-003-q0", "s42-SCN-001-q0"}
    assert [c.case_id for c in picked] == [c.case_id for c in world if c in picked]  # run order
    assert select_cases(world, None) == world
    with pytest.raises(ValueError, match="SCN-999"):
        select_cases(world, ["SCN-001", "SCN-999"])
    assert parse_only("SCN-001, SCN-002,") == ["SCN-001", "SCN-002"]
    assert parse_only(None) is None


# --- failures that are not the agent's --------------------------------------------------------


def _failed_step(error: str, attempts: list[str] | None = None) -> LLMStep:
    return LLMStep(
        node="investigate",
        purpose="t",
        provider="-",
        model="-",
        error=error,
        attempts=attempts or [],
    )


def test_infra_failure_classification() -> None:
    assert infra_failure(make_result()) is None

    daily = infra_failure(
        make_result(
            steps=[
                _failed_step(
                    "AllModelsFailed: All models failed: gemini:m: error (ClientError: 429 "
                    "RESOURCE_EXHAUSTED quota GenerateRequestsPerDayPerProjectPerModel-FreeTier)"
                )
            ]
        )
    )
    assert daily is not None and daily.kind == "daily_quota"

    per_minute = infra_failure(
        make_result(
            steps=[_failed_step("AllModelsFailed: 429 rate limit exceeded. Please retry in 12.5s")]
        )
    )
    assert per_minute is not None and per_minute.kind == "rate_limit"
    assert per_minute.wait_seconds == pytest.approx(13.5)

    cooling = infra_failure(
        make_result(
            steps=[_failed_step("AllModelsFailed: gemini:m: skipped (cooling down for 40s)")]
        )
    )
    assert cooling is not None and cooling.kind == "rate_limit" and cooling.wait_seconds == 60

    outage = infra_failure(
        make_result(steps=[_failed_step("AllModelsFailed: 503 Service Unavailable")])
    )
    assert outage is not None and outage.kind == "transient"

    miss = infra_failure(make_result(steps=[_failed_step("CacheMiss: No cached LLM response")]))
    assert miss is not None and miss.kind == "cache_miss"

    crash = infra_failure(make_result(error="RuntimeError: boom"))
    assert crash is not None and crash.kind == "crash"


def test_a_malformed_model_answer_is_the_agents_failure_not_infrastructure() -> None:
    malformed = make_result(
        steps=[
            _failed_step(
                "AllModelsFailed: gemini:m: error (MalformedOutput: structured output invalid)"
            )
        ],
        error="conclude failed: AllModelsFailed: structured output invalid",
    )
    assert infra_failure(malformed) is None


def test_the_most_severe_failure_wins() -> None:
    steps = [_failed_step("503 unavailable"), _failed_step("429 quota per day exceeded")]
    failure = infra_failure(make_result(steps=steps))
    assert failure is not None and failure.kind == "daily_quota"


# --- one case with a scripted model ------------------------------------------------------------


def _run_case(
    script: Any,
    *,
    sleeps: list[float] | None = None,
    executor: Callable[..., Any] = fake_tools,
    variant: str = "default",
    **kw: Any,
) -> CaseArtifact:
    sleeps = sleeps if sleeps is not None else []
    return run_case(
        make_planned("SCN-001"),
        runner=ScriptedRunner(script),
        engine=create_engine("sqlite://"),
        variant=get_variant(variant),
        run_name="t",
        agent_model="scripted:scripted",
        reference=REFERENCE,
        tool_executor=executor,
        sleep=sleeps.append,
        **kw,
    )


def _good_script() -> Callable[[RecordedCall], Any]:
    return script_for([*CHECKS, "enough"], make_report(**RIGHT))  # type: ignore[no-any-return]


def test_a_case_runs_to_a_saved_result() -> None:
    artifact = _run_case(_good_script())
    assert artifact.error is None and artifact.result is not None
    assert artifact.case.case_id == "s42-SCN-001-q0"
    assert artifact.variant == "default" and artifact.agent_model == "scripted:scripted"
    assert artifact.result.report.root_cause_category == "transport_failure"


def test_a_per_minute_limit_is_waited_out_and_retried() -> None:
    inner = _good_script()
    state = {"failed": False}

    def flaky(call: RecordedCall) -> Any:
        if call.purpose == "intake" and not state["failed"]:
            state["failed"] = True
            return RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 2.0s")
        return inner(call)

    sleeps: list[float] = []
    artifact = _run_case(flaky, sleeps=sleeps)
    assert sleeps == [3.0]
    assert artifact.error is None and artifact.result is not None
    assert artifact.result.report.title == "Fiber cut on LNK-TUN-01-A"


def test_a_daily_quota_stops_the_run() -> None:
    def script(call: RecordedCall) -> Any:
        return RuntimeError(
            "429 You exceeded your current quota: GenerateRequestsPerDayPerProjectPerModel"
        )

    sleeps: list[float] = []
    with pytest.raises(QuotaExhausted, match="daily_quota"):
        _run_case(script, sleeps=sleeps)
    assert sleeps == []


def test_a_limit_that_never_clears_stops_the_run_after_a_few_waits() -> None:
    def script(call: RecordedCall) -> Any:
        return RuntimeError("429 rate limit. Please retry in 5s")

    sleeps: list[float] = []
    with pytest.raises(QuotaExhausted, match="rate_limit"):
        _run_case(script, sleeps=sleeps, max_waits=2)
    assert sleeps == [6.0, 6.0]


def test_a_limit_with_too_long_a_wait_is_not_waited_for() -> None:
    def script(call: RecordedCall) -> Any:
        return RuntimeError("429 rate limit. Please retry in 900s")

    sleeps: list[float] = []
    with pytest.raises(QuotaExhausted):
        _run_case(script, sleeps=sleeps)
    assert sleeps == []


def test_an_outage_that_persists_is_saved_as_an_error_not_a_stop() -> None:
    def script(call: RecordedCall) -> Any:
        return RuntimeError("503 Service Unavailable: high demand")

    sleeps: list[float] = []
    artifact = _run_case(script, sleeps=sleeps, max_waits=2)
    assert len(sleeps) == 2
    assert artifact.error is not None and artifact.error.startswith("transient")


def test_a_crash_is_saved_as_an_error() -> None:
    def boom(name: str, args: dict[str, Any], ctx: ToolContext) -> Any:
        raise RuntimeError("tool exploded")

    artifact = _run_case(_good_script(), executor=boom)
    assert artifact.error is not None and "tool exploded" in artifact.error
    assert artifact.error.startswith("crash")


def test_a_malformed_report_is_a_scored_abstention_not_an_error() -> None:
    inner = _good_script()

    def script(call: RecordedCall) -> Any:
        if call.purpose.startswith("conclude"):
            return MalformedOutput("structured output invalid")
        return inner(call)

    artifact = _run_case(script)
    assert artifact.error is None and artifact.result is not None
    assert artifact.result.report.classification == "inconclusive"


# --- variants ---------------------------------------------------------------------------------


def test_variants_are_registered_and_easy_to_extend() -> None:
    assert set(VARIANTS) >= {"default", "no-gate", "no-runbooks"}
    with pytest.raises(ValueError, match="unknown variant"):
        get_variant("nope")


def test_no_gate_turns_the_gate_off_and_default_leaves_it_on() -> None:
    assert agent_config_for(get_variant("default")).completeness_gate is True
    assert agent_config_for(get_variant("no-gate")).completeness_gate is False
    assert agent_config_for(get_variant("default")) == AgentConfig()


def test_no_runbooks_needs_the_agent_switch_and_uses_it_when_present() -> None:
    variant = get_variant("no-runbooks")
    if "disabled_tools" in AgentConfig.model_fields:
        assert tuple(agent_config_for(variant).disabled_tools) == ("search_runbooks",)  # type: ignore[attr-defined]
    else:
        with pytest.raises(VariantUnavailable, match="disabled_tools"):
            agent_config_for(variant)


def test_a_disabled_tool_is_refused_if_the_model_calls_it_anyway() -> None:
    assert executor_for(get_variant("default")) is None
    execute = executor_for(get_variant("no-runbooks"))
    assert execute is not None
    ctx = ToolContext(engine=create_engine("sqlite://"), asked_at=ASKED_AT)
    result = execute("search_runbooks", {"query": "fibre cut"}, ctx)
    assert result.error is not None and "Unknown tool" in result.error


def test_the_no_gate_variant_runs_without_the_nudge() -> None:
    artifact = _run_case(script_for(["done"], make_report(**RIGHT)), variant="no-gate")
    assert artifact.variant == "no-gate"
    assert artifact.result is not None
    assert not any(n for n in artifact.result.issues if "Not yet checked" in n)


# --- resume, caps and stopping ----------------------------------------------------------------


def _batch(
    tmp_path: Path, make: Callable[[PlannedCase], CaseArtifact] | None = None, **kw: Any
) -> tuple[RunDir, Any, list[str]]:
    run = RunDir("r", tmp_path)
    ran: list[str] = []

    def run_one(planned: PlannedCase) -> CaseArtifact:
        ran.append(planned.case_id)
        if make:
            return make(planned)
        return make_artifact(scenario_id=planned.case.scenario_id)

    result = run_batch(run, stratified(_world()), run_one, **kw)
    return run, result, ran


def test_resume_skips_finished_cases(tmp_path: Path) -> None:
    run, first, ran = _batch(tmp_path, max_cases=5)
    assert len(first.executed) == 5 and first.not_run == 7
    assert [run.case_state(c) for c in ran] == ["done"] * 5
    second_run, second, ran2 = _batch(tmp_path)
    assert len(second.skipped_done) == 5 and len(second.executed) == 7
    assert not set(ran) & set(ran2)
    _, third, ran3 = _batch(tmp_path)
    assert ran3 == [] and len(third.skipped_done) == 12 and third.not_run == 0
    del second_run


def test_errored_cases_are_left_alone_unless_retry_errors(tmp_path: Path) -> None:
    def failing(planned: PlannedCase) -> CaseArtifact:
        return make_artifact(None, scenario_id=planned.case.scenario_id, error="transient: 503")

    run, first, _ = _batch(tmp_path, failing, max_cases=2)
    assert len(first.errors) == 2
    first_id = first.executed[0]
    assert run.case_state(first_id) == "error"
    _, second, ran = _batch(tmp_path, max_cases=3)
    assert len(second.skipped_errors) == 2 and first_id not in ran
    _, third, ran3 = _batch(tmp_path, retry_errors=True, max_cases=4)
    assert first.executed[0] in ran3 and third.skipped_errors == []
    assert run.case_state(first_id) == "done"


def test_a_quota_stop_saves_nothing_for_the_case_in_flight(tmp_path: Path) -> None:
    count = {"n": 0}

    def run_one(planned: PlannedCase) -> CaseArtifact:
        count["n"] += 1
        if count["n"] == 3:
            raise QuotaExhausted("daily_quota: 429")
        return make_artifact(scenario_id=planned.case.scenario_id)

    run = RunDir("r", tmp_path)
    result = run_batch(run, stratified(_world()), run_one)
    assert len(result.executed) == 2
    assert result.stopped == "daily_quota: 429"
    assert result.not_run == 10
    assert len(list(run.cases_dir.glob("*.json"))) == 2
    resumed = run_batch(
        run, stratified(_world()), lambda p: make_artifact(scenario_id=p.case.scenario_id)
    )
    assert len(resumed.executed) == 10 and resumed.stopped is None


def test_max_cases_zero_runs_nothing(tmp_path: Path) -> None:
    _, result, ran = _batch(tmp_path, max_cases=0)
    assert ran == [] and result.not_run == 12


def test_progress_is_reported_per_case(tmp_path: Path) -> None:
    seen: list[tuple[int, int, str]] = []
    _batch(tmp_path, max_cases=2, progress=lambda n, t, a: seen.append((n, t, a.case.case_id)))
    assert [(n, t) for n, t, _ in seen] == [(1, 2), (2, 2)]


def test_progress_line_has_id_verdict_calls_tokens_and_seconds() -> None:
    artifact = make_artifact(make_result(make_report(**RIGHT)))
    line = progress_line(3, 11, artifact, TOPOLOGY)
    for part in (
        "[3/11]",
        "s42-SCN-001-q0",
        "incident/transport_failure@LNK-TUN-01-A",
        "ok",
        "tokens=22000",
    ):
        assert part in line
    err = progress_line(1, 2, make_artifact(None, error="crash: x"), TOPOLOGY)
    assert "ERROR" in err and "crash: x" in err
    wrong = make_artifact(make_result(make_report(root_cause_node_id="S-TUN-003", **RIGHT)))
    assert "WRONG" in progress_line(1, 1, wrong, TOPOLOGY)


# --- files ------------------------------------------------------------------------------------


def test_artifacts_round_trip_and_are_stable_on_disk(tmp_path: Path) -> None:
    run = RunDir("r", tmp_path)
    artifact = make_artifact(make_result(make_report(**RIGHT)))
    run.save_artifact(artifact)
    path = run.artifact_path(artifact.case.case_id)
    first = path.read_bytes()
    assert run.load_artifact(artifact.case.case_id) == artifact
    run.save_artifact(artifact)
    assert path.read_bytes() == first
    assert b"\r" not in first and first.endswith(b"\n")
    data = json.loads(first)
    assert list(data) == sorted(data)
    assert run.case_state(artifact.case.case_id) == "done"
    assert run.case_state("nothing") == "missing"
    run.save_artifact(make_artifact(None, scenario_id="SCN-002", error="crash"))
    assert run.case_state("s42-SCN-002-q0") == "error"
    assert len(run.load_artifacts()) == 2


# --- the results report -----------------------------------------------------------------------


def _write_run(
    root: Path,
    name: str,
    seed: int,
    artifacts: list[CaseArtifact],
    *,
    variant: str = "default",
    total: int = 34,
) -> RunDir:
    run = RunDir(name, root)
    run.write_meta(
        RunMeta(
            name=name,
            seed=seed,
            split="dev" if seed == 42 else "test",
            variant=variant,
            agent_model="gemini:gemini-3.5-flash-lite",
            questions="first",
            cases_total=total,
            database="db",
            created_at="2026-10-10T00:00:00+00:00",
            updated_at="2026-10-10T00:00:00+00:00",
        )
    )
    run.write_topology(TOPOLOGY)
    for a in artifacts:
        run.save_artifact(a)
    return run


def _artifacts(seed: int, variant: str, wrong: bool = False) -> list[CaseArtifact]:
    ok = make_result(make_report(**RIGHT))
    bad = make_result(make_report(root_cause_category="bad_change", **RIGHT))
    return [
        make_artifact(ok, scenario_id="SCN-001", seed=seed, variant=variant),
        make_artifact(
            bad if wrong else ok,
            scenario_id="SCN-002",
            seed=seed,
            variant=variant,
            truth=make_truth(kind="power_outage", root_cause_node_id="LNK-TUN-01-A"),
        ),
        make_artifact(
            None, scenario_id="SCN-003", seed=seed, variant=variant, error="transient: 503"
        ),
    ]


def test_report_from_one_partial_run_without_grades(tmp_path: Path) -> None:
    run = _write_run(tmp_path / "runs", "smoke-dev", 42, _artifacts(42, "default"))
    out = tmp_path / "out"
    written = write_report([run], out)
    names = {p.name for p in written}
    assert {"evaluation.md", "evaluation.json"} <= names
    assert any(n.endswith(".png") for n in names)
    assert all(p.stat().st_size > 0 for p in written)
    md = (out / "evaluation.md").read_text(encoding="utf-8")
    assert "Partial results" in md and "2 of 34" in md
    assert "No test-world run is included yet" in md
    assert "Not yet measured" in md
    assert "optimistic" in md
    assert "1 more ended in an infrastructure error" in md
    assert "ERROR" in md
    data = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
    assert data["runs"][0]["partial"] is True
    assert data["runs"][0]["overall"]["n_errors"] == 1
    assert data["runs"][0]["faithfulness"]["graded"] == 0
    assert b"\r" not in (out / "evaluation.md").read_bytes()


def test_report_with_test_dev_ablation_and_grades(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    dev = _write_run(root, "baseline-dev", 42, _artifacts(42, "default"), total=3)
    test = _write_run(root, "baseline-test", 7, _artifacts(7, "default", wrong=True), total=3)
    ablation = _write_run(
        root, "nogate-dev", 42, _artifacts(42, "no-gate", wrong=True), variant="no-gate", total=3
    )
    graded = ReportGrade(
        case_id="s7-SCN-001-q0",
        grader="groq:x",
        findings=[
            FindingGrade(index=0, verdict="supported"),
            FindingGrade(index=1, verdict="unsupported"),
        ],
    )
    (test.grades_dir).mkdir(parents=True)
    (test.grades_dir / "s7-SCN-001-q0.json").write_text(graded.model_dump_json(), encoding="utf-8")
    out = tmp_path / "out"
    write_report([dev, ablation, test], out)
    md = (out / "evaluation.md").read_text(encoding="utf-8")
    assert md.index("baseline-test") < md.index("baseline-dev")  # the test world comes first
    assert "## Ablations" in md and "nogate-dev (no-gate)" in md
    assert "gained none; lost s42-SCN-002-q0" in md
    assert "0.50" in md and "1 of 2" in md  # faithfulness of one graded report
    assert "Not yet measured" not in md
    assert "No test-world run is included yet" not in md
    assert "## What the agent gets wrong" in md and "s7-SCN-002-q0" in md
    data = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
    assert [r["run"]["name"] for r in data["runs"]] == [
        "baseline-test",
        "baseline-dev",
        "nogate-dev",
    ]
    assert data["ablations"][0]["lost"] == ["s42-SCN-002-q0"]


def test_report_needs_runs_that_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_report([RunDir("missing", tmp_path)], tmp_path / "out")


# --- hard-profile worlds ----------------------------------------------------------------------


def test_hard_worlds_have_their_own_ids_split_and_database() -> None:
    assert make_case_id(101, "SCN-012", 0, "hard") == "h101-SCN-012-q0"
    assert make_case_id(42, "SCN-012", 0) == "s42-SCN-012-q0"
    assert split_of(101, "hard") == "test" and split_of(42, "hard") == "test"
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url="postgresql+psycopg://u:p@localhost:5433/incident_agent"
    )
    hard = resolve_targets(101, settings=settings, profile="hard")
    assert hard.name == "incident_agent_eval_hard_s101"
    assert resolve_targets(42, settings=settings, profile="hard").name.endswith("hard_s42")
    assert resolve_targets(7, settings=settings).name == "incident_agent_eval_s7"
    assert resolve_targets(42, settings=settings).name == "incident_agent"
    assert hard.agent_url.username == "agent_ro" and hard.agent_url.database == hard.name


def test_a_run_name_cannot_mix_profiles(tmp_path: Path) -> None:
    run = RunDir("mix", tmp_path)
    hard = RunOptions(name="mix", seed=101, profile="hard")
    meta = _check_or_create_meta(run, hard, "m", 34, "incident_agent_eval_hard_s101")
    assert meta.profile == "hard" and meta.split == "test"
    run.write_meta(meta)
    assert run.read_meta() == meta
    assert json.loads(run.meta_path.read_text(encoding="utf-8"))["profile"] == "hard"
    _check_or_create_meta(run, hard, "m", 34, "incident_agent_eval_hard_s101")  # the same world
    with pytest.raises(ValueError, match="profile is 'hard' in the run, 'default' now"):
        _check_or_create_meta(run, RunOptions(name="mix", seed=101), "m", 34, "db")


def test_runs_recorded_before_profiles_existed_still_load(tmp_path: Path) -> None:
    run = _write_run(tmp_path, "old", 7, _artifacts(7, "default"), total=3)
    data = json.loads(run.meta_path.read_text(encoding="utf-8"))
    del data["profile"]
    run.meta_path.write_text(json.dumps(data), encoding="utf-8")
    meta = run.read_meta()
    assert meta is not None and meta.profile == "default"
    write_report([run], tmp_path / "out")  # scores and reports as before
    md = (tmp_path / "out" / "evaluation.md").read_text(encoding="utf-8")
    assert "By trap" not in md and "hard-profile" not in md


def test_the_report_breaks_results_down_by_trap_only_when_there_are_traps(tmp_path: Path) -> None:
    ok = make_result(make_report(**RIGHT))
    bad = make_result(make_report(root_cause_category="bad_change", **RIGHT))
    trap = "trap=change_on_root_node; Fibre cut."
    arts = [
        make_artifact(ok, scenario_id="SCN-001", seed=101, truth=make_truth(notes=trap)),
        make_artifact(bad, scenario_id="SCN-002", seed=101, truth=make_truth(notes=trap)),
        make_artifact(
            ok,
            scenario_id="SCN-003",
            seed=101,
            truth=make_truth(notes="trap=missing_alarm; Fibre cut."),
        ),
        make_artifact(ok, scenario_id="SCN-004", seed=101),
    ]
    run = RunDir("hard-run", tmp_path / "runs")
    run.write_meta(
        RunMeta(
            name="hard-run",
            seed=101,
            split="test",
            profile="hard",
            variant="default",
            agent_model="gemini:gemini-3.5-flash-lite",
            questions="first",
            cases_total=4,
            database="incident_agent_eval_hard_s101",
            created_at="2026-10-10T00:00:00+00:00",
            updated_at="2026-10-10T00:00:00+00:00",
        )
    )
    run.write_topology(TOPOLOGY)
    for a in arts:
        run.save_artifact(a)
    scored = load_scored_run(run)
    assert [s.trap for s in scored.scores] == [
        "change_on_root_node",
        "change_on_root_node",
        "missing_alarm",
        None,
    ]
    summary = summary_json(scored)
    assert summary["by_trap"]["change_on_root_node"]["rca_lenient"]["k"] == 1
    assert summary["by_trap"]["change_on_root_node"]["n_cases"] == 2
    assert summary["by_trap"]["no trap"]["n_cases"] == 1
    assert (
        summary["cases"][0]["trap"] == "change_on_root_node" and "trap" not in summary["cases"][3]
    )
    assert any("change_on_root_node" in line for line in summary_lines(scored))
    out = tmp_path / "out"
    write_report([run], out)
    md = (out / "evaluation.md").read_text(encoding="utf-8")
    assert "**By trap**" in md and "change_on_root_node" in md and "seed 101 (hard, test)" in md
    data = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
    assert set(data["runs"][0]["by_trap"]) == {"change_on_root_node", "missing_alarm", "no trap"}
    # Worlds without traps keep the old layout.
    plain = load_scored_run(_write_run(tmp_path / "p", "plain", 7, _artifacts(7, "default")))
    assert "by_trap" not in summary_json(plain)
    assert all("trap" not in c for c in summary_json(plain)["cases"])
