"""Unit tests of the agent tools that need no database."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine

from incident_agent.agent.tools import TOOLS, execute_tool, tool_schemas
from incident_agent.agent.tools.baseline import Floors, analyse
from incident_agent.agent.tools.common import (
    BODY_CHARS,
    Item,
    assemble,
    estimate_tokens,
    num,
    trim,
)
from incident_agent.agent.tools.run_sql import build_sql
from incident_agent.agent.tools.runbooks import excerpt
from incident_agent.agent.tools.sqlguard import GuardError, check_sql
from incident_agent.agent.tools.timeutil import (
    LOCAL_TZ,
    TimeParseError,
    Window,
    as_utc,
    fmt,
    fmt_duration,
    make_window,
    parse_time,
)
from incident_agent.agent.types import ToolContext

# --- time -------------------------------------------------------------------------------------


def test_naive_time_is_tunis_local() -> None:
    assert parse_time("2026-09-21 16:50") == datetime(2026, 9, 21, 15, 50, tzinfo=UTC)
    assert parse_time("2026-09-21T16:50") == parse_time("2026-09-21 16:50")


def test_explicit_offsets_are_respected() -> None:
    assert parse_time("2026-09-21T15:50Z") == datetime(2026, 9, 21, 15, 50, tzinfo=UTC)
    assert parse_time("2026-09-21T16:50+01:00") == parse_time("2026-09-21 16:50")
    assert parse_time("2026-09-21T10:50-05:00") == datetime(2026, 9, 21, 15, 50, tzinfo=UTC)


def test_date_only_means_local_midnight() -> None:
    assert parse_time("2026-09-21") == datetime(2026, 9, 20, 23, 0, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", "yesterday", "21/09/2026 16:50", "2026-13-40"])
def test_unparseable_time_raises_with_a_hint(bad: str) -> None:
    with pytest.raises(TimeParseError, match="ISO 8601"):
        parse_time(bad)


def test_times_are_shown_in_local_time() -> None:
    assert fmt(datetime(2026, 9, 21, 15, 50, tzinfo=UTC)) == "2026-09-21 16:50"
    assert fmt(None) == "-"
    assert LOCAL_TZ is not None


def test_naive_asked_at_is_taken_as_local_time() -> None:
    assert as_utc(datetime(2026, 9, 21, 16, 50)) == datetime(2026, 9, 21, 15, 50, tzinfo=UTC)
    aware = datetime(2026, 9, 21, 16, 50, tzinfo=UTC)
    assert as_utc(aware) == aware


def test_duration_format() -> None:
    assert fmt_duration(timedelta(minutes=45)) == "45 min"
    assert fmt_duration(timedelta(hours=2, minutes=30)) == "2.5 h"
    assert fmt_duration(timedelta(days=3)) == "3.0 d"


def test_window_is_clamped_to_asked_at() -> None:
    asked = parse_time("2026-09-21 18:00")
    w = make_window("2026-09-21 16:00", "2026-09-21 23:00", asked)
    assert w.end == asked and w.clamped and not w.empty
    assert "cut at asked_at" in w.notes()[0]


def test_window_entirely_after_asked_at_is_empty() -> None:
    asked = parse_time("2026-09-21 18:00")
    w = make_window("2026-09-21 19:00", "2026-09-21 23:00", asked)
    assert w.empty and "nothing is visible" in w.notes()[0]


def test_window_with_end_before_start_is_an_error() -> None:
    with pytest.raises(TimeParseError, match="before start"):
        make_window("2026-09-21 19:00", "2026-09-21 18:00", parse_time("2026-09-22"))


def test_untouched_window_has_no_notes() -> None:
    asked = parse_time("2026-09-22")
    assert Window(parse_time("2026-09-21"), parse_time("2026-09-21 12:00"), asked).notes() == []


# --- baseline and onset on hand-made series ---------------------------------------------------


def _series(
    days: int,
    first_day: str = "2026-09-01",
    dip: tuple[str, str] | None = None,
    factor: float = 0.2,
) -> pd.Series:
    """15-minute series with a daily curve, tiny deterministic noise and an optional dip."""
    start = pd.Timestamp(first_day, tz=LOCAL_TZ)
    idx = pd.date_range(start, periods=days * 96, freq="15min").tz_convert("UTC")
    rng = np.random.default_rng(3)
    local_hour = idx.tz_convert(LOCAL_TZ).hour + idx.tz_convert(LOCAL_TZ).minute / 60
    values = 100 + 50 * np.sin(2 * np.pi * (local_hour - 6) / 24)
    values = values * rng.normal(1.0, 0.005, len(idx))
    if dip is not None:
        lo, hi = pd.Timestamp(dip[0], tz=LOCAL_TZ), pd.Timestamp(dip[1], tz=LOCAL_TZ)
        values = np.where((idx >= lo) & (idx < hi), values * factor, values)
    return pd.Series(values, index=idx)


FLOORS = Floors(rel_floor=0.02)


def _local(ts: pd.Timestamp) -> str:
    return ts.tz_convert(LOCAL_TZ).strftime("%H:%M")


def test_onset_and_recovery_of_a_dip() -> None:
    s = _series(10, dip=("2026-09-10 14:00", "2026-09-10 16:00"))
    start, end = parse_time("2026-09-10 12:00"), parse_time("2026-09-10 20:00")
    a = analyse(s, start, end, FLOORS)
    assert a.run is not None and a.run.direction == "below"
    assert _local(a.index[a.run.first]) == "14:00"
    assert a.recovery is not None and _local(a.index[a.recovery]) == "16:00"
    assert not a.ongoing and not a.before_window
    assert a.n_hist.max() >= 7  # seven earlier weekdays


def test_unrecovered_dip_is_ongoing_at_the_window_end() -> None:
    s = _series(10, dip=("2026-09-10 14:00", "2026-09-10 16:00"))
    a = analyse(s[s.index <= parse_time("2026-09-10 15:00")], parse_time("2026-09-10 12:00"),
                parse_time("2026-09-10 15:00"), FLOORS)  # fmt: skip
    assert a.run is not None and a.ongoing and a.recovery is None
    assert _local(a.index[a.run.first]) == "14:00"


def test_onset_before_the_window_is_found_through_the_lead_in() -> None:
    s = _series(10, dip=("2026-09-10 14:00", "2026-09-10 20:00"))
    a = analyse(s, parse_time("2026-09-10 16:00"), parse_time("2026-09-10 19:00"), FLOORS)
    assert a.run is not None and a.before_window
    assert _local(a.index[a.run.first]) == "14:00"


def test_single_step_blip_is_not_a_deviation() -> None:
    s = _series(10, dip=("2026-09-10 14:00", "2026-09-10 14:15"))
    a = analyse(s, parse_time("2026-09-10 12:00"), parse_time("2026-09-10 20:00"), FLOORS)
    assert a.run is None


def test_normal_day_has_no_deviation() -> None:
    a = analyse(_series(10), parse_time("2026-09-10 00:00"), parse_time("2026-09-10 23:45"), FLOORS)
    assert a.run is None and np.isfinite(a.baseline).all()


def test_baseline_uses_only_earlier_days_of_the_same_type() -> None:
    # 2026-09-12 is a Saturday; the only earlier Saturday has a flat, much higher level.
    s = _series(12)
    sat = s.index.tz_convert(LOCAL_TZ).date == datetime(2026, 9, 5).date()
    s = s.copy()
    s[sat] = 1000.0
    start, end = parse_time("2026-09-12 10:00"), parse_time("2026-09-12 12:00")
    thin = analyse(s, start, end, FLOORS, min_days=2)
    assert np.isnan(thin.baseline).all()  # one earlier Saturday is too little
    assert thin.n_hist.max() == 1
    weekday = analyse(s, parse_time("2026-09-10 10:00"), parse_time("2026-09-10 12:00"), FLOORS)
    assert np.isfinite(weekday.baseline).all() and weekday.baseline.max() < 200


def test_values_of_the_judged_day_do_not_change_its_baseline() -> None:
    s = _series(10)
    start, end = parse_time("2026-09-10 10:00"), parse_time("2026-09-10 12:00")
    before = analyse(s, start, end, FLOORS).baseline
    s2 = s.copy()
    s2[(s2.index >= start) & (s2.index <= end)] = 5.0
    assert np.allclose(analyse(s2, start, end, FLOORS).baseline, before)


def test_missing_values_are_neither_normal_nor_deviating() -> None:
    s = _series(10)
    gap = (s.index >= parse_time("2026-09-10 14:00")) & (s.index < parse_time("2026-09-10 15:00"))
    s[gap] = np.nan
    a = analyse(s, parse_time("2026-09-10 12:00"), parse_time("2026-09-10 20:00"), FLOORS)
    assert a.run is None
    assert int(np.isnan(a.values[a.in_window]).sum()) == 4


# --- body budget ------------------------------------------------------------------------------


def test_number_format_is_compact() -> None:
    assert num(None) == "-"
    assert num(12345.678) == "12346"
    assert num(99.43) == "99.4"
    assert num(0.5) == "0.5"
    assert num(0.0) == "0"
    assert trim("a  b\nc" * 30, 20).endswith("...")


def test_assemble_fits_the_budget_and_reports_what_was_left_out() -> None:
    items = [Item(line=f"row {i} " + "x" * 80, sort=i, data={"k": "a"}) for i in range(100)]
    out = assemble(["header"], items, omitted_line=lambda left: f"Omitted {len(left)} rows.")
    assert len(out.body) <= BODY_CHARS and out.truncated
    assert out.body.startswith("header") and f"Omitted {len(out.omitted)} rows." in out.body
    assert [i.sort for i in out.shown] == sorted(i.sort for i in out.shown)
    assert out.shown[0].sort == 0  # priority order was respected


def test_assemble_without_overflow_shows_everything() -> None:
    items = [Item(line=f"row {i}", sort=i) for i in range(5)]
    out = assemble(["head"], items, omitted_line=lambda left: "never")
    assert not out.truncated and "never" not in out.body and estimate_tokens(out.body) < 50


def test_runbook_excerpt_prefers_sentences_that_match_the_query() -> None:
    content = (
        "Overview of the process. "
        + "Filler sentence about nothing. " * 20
        + "The battery autonomy is one to four hours. "
        + "More filler text goes here. " * 20
    )
    text_, cut = excerpt(content, "battery autonomy", 200)
    assert cut and "battery autonomy" in text_ and len(text_) <= 210
    short, cut = excerpt("Just one short sentence.", "anything", 200)
    assert not cut and short == "Just one short sentence."


# --- run_sql guard ----------------------------------------------------------------------------

GOOD_SQL = [
    "SELECT * FROM alarms LIMIT 5",
    "select count(*) from cell_kpis where ts > '2026-09-02 10:00' and cell_id = 'C-TUN-001-1'",
    "WITH x AS (SELECT node_id FROM nodes WHERE region_id = 'TUN') SELECT count(*) FROM x;",
    "SELECT date_trunc('hour', ts) h, avg(latency_ms) FROM cell_kpis GROUP BY 1 ORDER BY 1",
    "SELECT a.alarm_id, n.name FROM alarms a JOIN nodes n ON n.node_id = a.node_id",
    "SELECT extract(epoch FROM (cleared_at - raised_at)) / 60 AS minutes FROM alarms",
    "SELECT 'a--b' AS s, 'it''s' AS t, '50%' LIKE '5%'",
    "SELECT * FROM generate_series(1, 3) AS g(n)",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY value) FROM core_kpis",
    "SELECT metric, count(*) FILTER (WHERE value > 1) FROM core_kpis GROUP BY metric",
    "SELECT ts, lag(value) OVER (PARTITION BY metric ORDER BY ts) FROM core_kpis",
    "SELECT cast(sector AS text), sector::numeric(4,1) FROM cells",
]


@pytest.mark.parametrize("sql", GOOD_SQL)
def test_guard_accepts_read_only_selects(sql: str) -> None:
    assert check_sql(sql)


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("", "Empty"),
        ("DELETE FROM alarms", "single SELECT"),
        ("UPDATE alarms SET severity = 'minor'", "single SELECT"),
        ("INSERT INTO alarms SELECT * FROM alarms", "single SELECT"),
        ("DROP TABLE alarms", "single SELECT"),
        ("TRUNCATE alarms", "single SELECT"),
        ("EXPLAIN SELECT 1", "single SELECT"),
        ("SELECT 1; SELECT 2", "one statement"),
        ("SELECT 1; DROP TABLE alarms", "one statement"),
        ("SELECT * INTO newtable FROM alarms", "INTO"),
        ("WITH d AS (DELETE FROM alarms RETURNING *) SELECT * FROM d", "DELETE"),
        ("SELECT * FROM alarms FOR UPDATE", "locking"),
        ("SELECT * FROM gt.scenarios", "not accessible"),
        ('SELECT * FROM "gt"."scenarios"', "not accessible"),
        ("SELECT * FROM public.alarms", "not accessible"),
        ("SELECT * FROM pg_catalog.pg_class", "not accessible"),
        ("SELECT * FROM pg_stats", "not accessible"),
        ("SELECT * FROM information_schema.tables", "not accessible"),
        ("SELECT * FROM app.agent_runs", "not accessible"),
        ("SELECT * FROM alerts", "get_anomalies"),
        ("SELECT * FROM anomalies", "get_anomalies"),
        ("SELECT * FROM runbook_chunks", "search_runbooks"),
        ("SELECT * FROM region_kpis_15m", "query_kpis"),
        ("SELECT * FROM dataset_meta", "not available"),
        ("SELECT query_to_xml('select * from public.cell_kpis', true, false, '')", "query_to_xml"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT now()", "now"),
        ("SELECT current_timestamp", "current_timestamp"),
        ("SELECT set_config('a', 'b', false)", "set_config"),
        ("SELECT pg_read_file('/etc/passwd')", "not accessible"),
        ("SELECT 1 -- comment", "Comments"),
        ("SELECT /* x */ 1", "Comments"),
        ("SELECT E'\\x41'", "Escape strings"),
        ("SELECT $$text$$", "'$'"),
        ("SELECT * FROM cells WHERE site_id = 'unterminated", "Unterminated"),
        ("COPY alarms TO STDOUT", "single SELECT"),
        ("SET statement_timeout = 0", "single SELECT"),
        ("SELECT 1 WHERE EXISTS (SELECT 1 FROM public . alarms)", "not accessible"),
    ],
)
def test_guard_rejects(sql: str, fragment: str) -> None:
    with pytest.raises(GuardError) as err:
        check_sql(sql)
    assert fragment.lower() in str(err.value).lower()


def test_guard_rejects_overlong_queries() -> None:
    with pytest.raises(GuardError, match="too long"):
        check_sql("SELECT " + "1," * 3000 + "1")


def test_guard_strips_one_trailing_semicolon() -> None:
    assert check_sql("SELECT 1 ;  ") == "SELECT 1"


def test_shadow_prefix_filters_every_time_series_table() -> None:
    sql = build_sql("SELECT 1", datetime(2026, 9, 21, 15, 50, tzinfo=UTC))
    for table in ("cell_kpis", "core_kpis", "alarms", "changes", "maintenance", "external_events"):
        assert f"{table} AS NOT MATERIALIZED" in sql
    assert sql.count("2026-09-21 15:50:00+00") >= 8
    assert "LIMIT 50" in sql


# --- registry ---------------------------------------------------------------------------------

EXPECTED_TOOLS = {
    "get_anomalies",
    "query_kpis",
    "get_topology",
    "get_alarms",
    "get_changes",
    "get_maintenance",
    "get_external_events",
    "search_runbooks",
    "run_sql",
}


def test_registry_has_every_tool() -> None:
    assert set(TOOLS) == EXPECTED_TOOLS
    assert [s["name"] for s in tool_schemas()] == list(TOOLS)


def _check_schema(node: object, path: str) -> None:
    assert isinstance(node, dict), path
    forbidden = {"$ref", "$defs", "anyOf", "allOf", "oneOf", "title", "default"}
    assert not forbidden & set(node), f"{path} uses {forbidden & set(node)}"
    assert "type" in node, path
    for key, child in node.get("properties", {}).items():
        _check_schema(child, f"{path}.{key}")
    if "items" in node:
        _check_schema(node["items"], f"{path}[]")


@pytest.mark.parametrize("schema", tool_schemas(), ids=lambda s: s["name"])
def test_schemas_are_plain_json_schema(schema: dict[str, object]) -> None:
    assert set(schema) == {"name", "description", "parameters"}
    params = schema["parameters"]
    assert isinstance(params, dict) and params["type"] == "object"
    _check_schema(params, schema["name"])  # type: ignore[arg-type]
    props = params["properties"]
    assert set(params["required"]) <= set(props)
    for prop in props.values():
        assert prop.get("description") or prop.get("enum") or prop["type"] in ("boolean", "integer")


def test_descriptions_are_short() -> None:
    for spec in TOOLS.values():
        sentences = [s for s in spec.description.split(". ") if s.strip()]
        assert 1 <= len(sentences) <= 3, spec.name
        assert len(spec.description) < 420, spec.name


def test_required_arguments_in_schema() -> None:
    by_name = {s["name"]: s["parameters"] for s in tool_schemas()}
    assert set(by_name["get_alarms"]["required"]) == {"start", "end"}
    assert set(by_name["query_kpis"]["required"]) == {"entity_type", "metrics", "start", "end"}
    assert by_name["query_kpis"]["properties"]["entity_type"]["enum"] == [
        "cell",
        "site",
        "region",
        "national",
        "core_node",
    ]
    assert by_name["get_topology"]["required"] == ["node_id"]
    assert by_name["run_sql"]["required"] == ["query"]


@pytest.fixture
def offline_ctx() -> ToolContext:
    """A context whose engine is never used (arguments fail validation first)."""
    return ToolContext(
        engine=create_engine("sqlite://"), asked_at=datetime(2026, 9, 21, tzinfo=UTC)
    )


def test_execute_unknown_tool_returns_an_error(offline_ctx: ToolContext) -> None:
    r = execute_tool("drop_everything", {}, offline_ctx)
    assert r.error and "Unknown tool" in r.error and "get_alarms" in r.error


@pytest.mark.parametrize(
    ("name", "args", "fragment"),
    [
        ("get_alarms", {}, "start"),
        ("get_alarms", {"start": "a", "end": "b", "bogus": 1}, "bogus"),
        ("get_alarms", {"start": "a", "end": "b", "min_severity": "huge"}, "min_severity"),
        (
            "query_kpis",
            {"entity_type": "link", "metrics": ["x"], "start": "a", "end": "b"},
            "entity_type",
        ),
        (
            "query_kpis",
            {
                "entity_type": "site",
                "entity_ids": list("abcdefg"),
                "metrics": ["x"],
                "start": "a",
                "end": "b",
            },
            "entity_ids",
        ),
        (
            "query_kpis",
            {
                "entity_type": "site",
                "entity_ids": ["S"],
                "metrics": list("abcde"),
                "start": "a",
                "end": "b",
            },
            "metrics",
        ),
        ("search_runbooks", {"query": "x" * 5, "k": 7}, "k"),
        ("get_topology", {"node_id": "S-TUN-001", "include": "cousins"}, "include"),
        ("run_sql", {"query": 7}, "query"),
    ],
)
def test_bad_arguments_become_errors_not_exceptions(
    offline_ctx: ToolContext, name: str, args: dict[str, object], fragment: str
) -> None:
    r = execute_tool(name, args, offline_ctx)
    assert r.error and fragment in r.error and r.body == r.error and r.tool == name


def test_execute_tool_survives_a_crashing_tool(
    offline_ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(ctx: ToolContext, args: object) -> None:
        raise RuntimeError("kaput")

    spec = TOOLS["get_topology"]
    monkeypatch.setitem(
        TOOLS, "get_topology", type(spec)(spec.name, spec.description, spec.args_model, boom)
    )  # type: ignore[arg-type]
    r = execute_tool("get_topology", {"node_id": "S-TUN-001"}, offline_ctx)
    assert r.error and "kaput" in r.error
