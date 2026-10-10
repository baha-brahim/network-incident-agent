"""Scoring, aggregation and statistics of the evaluation: pure, no database, no model."""

from datetime import timedelta
from typing import Any

import pytest

from incident_agent.agent.report import DismissedSignal, HypothesisEntry
from incident_agent.agent.state import LLMStep
from incident_agent.evals.aggregate import aggregate, calibration, group_by, kind_of_case
from incident_agent.evals.pricing import estimate_cost
from incident_agent.evals.scoring import (
    CaseScore,
    acceptable_nodes,
    category_in_top3,
    classify_node,
    confounder_outcomes,
    evidence_shares,
    faithfulness,
    score_case,
    time_error_min,
    tool_overlap,
    verification_counts,
    visible_at,
    worst_outcome,
)
from incident_agent.evals.stats import bootstrap_mean_ci, mean, percentile, wilson_interval
from incident_agent.evals.types import FindingGrade, ReportGrade
from tests.agent_support import make_report
from tests.evals_support import (
    ASKED_AT,
    CAUSE_AT,
    TOPOLOGY,
    make_artifact,
    make_call,
    make_result,
    make_truth,
)

RIGHT: dict[str, Any] = {
    "impact_start": "2026-09-02 17:00",
    "root_cause_time": "2026-09-02 17:00",
}


def score(report_over: dict[str, Any] | None = None, **result_kw: Any) -> CaseScore:
    report = make_report(**{**RIGHT, **(report_over or {})})
    return score_case(make_artifact(make_result(report, **result_kw)), TOPOLOGY)


# --- the verdict, category and node -----------------------------------------------------------


def test_a_correct_report_is_correct_in_every_way() -> None:
    s = score(calls=[make_call("T1", "get_alarms", rows=["ALM-000001"])])
    assert (s.verdict_correct, s.category_correct, s.category_in_top3) == (True, True, True)
    assert s.node_match == "exact"
    assert s.rca_strict and s.rca_lenient
    assert not s.abstained and not s.confident_wrong
    assert s.cause_time_error_min == 0.0 and s.impact_start_error_min == 0.0


def test_wrong_category_fails_the_root_cause_but_not_the_verdict() -> None:
    s = score({"root_cause_category": "bad_change", "hypotheses": []})
    assert s.verdict_correct and not s.category_correct and not s.category_in_top3
    assert not s.rca_strict and not s.rca_lenient
    assert s.confident_wrong  # make_report is high confidence


def test_inconclusive_is_an_abstention_and_never_correct() -> None:
    s = score(
        {"classification": "inconclusive", "root_cause_category": "unknown", "confidence": "low"}
    )
    assert s.abstained and not s.verdict_correct
    assert not s.rca_lenient and not s.confident_wrong


def test_red_herring_verdicts() -> None:
    truth = make_truth(
        kind="planned_maintenance",
        is_incident=False,
        root_cause_category="planned_maintenance",
        root_cause_node_id="LNK-TUN-01-A",
    )
    ok = make_report(
        classification="planned_maintenance", root_cause_category="planned_maintenance", **RIGHT
    )
    s = score_case(make_artifact(make_result(ok), truth=truth), TOPOLOGY)
    assert s.truth_classification == "planned_maintenance" and s.rca_strict
    as_incident = make_report(**RIGHT)
    s = score_case(make_artifact(make_result(as_incident), truth=truth), TOPOLOGY)
    assert not s.verdict_correct and not s.category_correct


def test_category_in_top3_uses_the_first_three_hypotheses_only() -> None:
    def hyp(cat: str) -> HypothesisEntry:
        return HypothesisEntry(category=cat, node_id=None, verdict="rejected", reason="r", refs=[])  # type: ignore[arg-type]

    report = make_report(
        root_cause_category="bad_change",
        hypotheses=[
            hyp("capacity"),
            hyp("bad_change"),
            hyp("power_failure"),
            hyp("transport_failure"),
        ],
    )
    assert not category_in_top3(report, "transport_failure")
    assert category_in_top3(report, "power_failure")
    assert category_in_top3(report, "bad_change")  # the stated cause itself


# --- node matching ----------------------------------------------------------------------------


def test_exact_related_and_wrong_nodes() -> None:
    truth = make_truth()  # fibre cut on LNK-TUN-01-A
    assert classify_node("LNK-TUN-01-A", truth, TOPOLOGY) == "exact"
    assert classify_node(" LNK-TUN-01-A ", truth, TOPOLOGY) == "exact"
    assert classify_node("S-TUN-001", truth, TOPOLOGY) == "related"  # descendant
    assert classify_node("AGG-TUN-01", truth, TOPOLOGY) == "related"  # ancestor
    assert classify_node("CORE-UPF-01", truth, TOPOLOGY) == "related"
    assert classify_node("LNK-TUN-01-B", truth, TOPOLOGY) == "wrong"  # a sibling
    assert classify_node("S-TUN-003", truth, TOPOLOGY) == "wrong"
    assert classify_node(None, truth, TOPOLOGY) == "wrong"


def test_no_acceptable_peers_for_single_node_causes() -> None:
    for kind in ("fiber_cut", "power_outage", "dns_degradation", "link_degradation", "alarm_storm"):
        truth = make_truth(kind=kind, affected_node_ids=["LNK-TUN-01-A", "S-TUN-001"])
        assert acceptable_nodes(truth) == set()


def test_peers_of_a_group_config_push_and_of_congestion() -> None:
    push = make_truth(
        kind="config_push",
        root_cause_node_id="S-TUN-001",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
    )
    assert classify_node("S-TUN-002", push, TOPOLOGY) == "acceptable"
    assert classify_node("S-TUN-001", push, TOPOLOGY) == "exact"
    assert classify_node("LNK-TUN-01-A", push, TOPOLOGY) == "related"  # the parent link
    congestion = make_truth(
        kind="congestion",
        root_cause_node_id="S-TUN-001",
        affected_node_ids=["S-TUN-001", "S-TUN-003"],
    )
    assert classify_node("S-TUN-003", congestion, TOPOLOGY) == "acceptable"
    stadium = make_truth(
        kind="stadium_event",
        root_cause_node_id="S-TUN-001",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
    )
    assert classify_node("S-TUN-002", stadium, TOPOLOGY) == "acceptable"


def test_a_config_push_to_a_router_has_no_peers() -> None:
    push = make_truth(
        kind="config_push",
        root_cause_node_id="AGG-TUN-01",
        affected_node_ids=["S-TUN-001", "S-TUN-002", "S-TUN-003"],
    )
    assert acceptable_nodes(push) == set()
    assert classify_node("S-TUN-001", push, TOPOLOGY) == "related"
    assert classify_node("AGG-TUN-01", push, TOPOLOGY) == "exact"


def test_a_null_label_is_matched_only_by_null() -> None:
    holiday = make_truth(kind="public_holiday", root_cause_node_id=None, affected_node_ids=[])
    assert classify_node(None, holiday, TOPOLOGY) == "exact"
    assert classify_node("S-TUN-001", holiday, TOPOLOGY) == "wrong"


def test_acceptable_node_makes_lenient_but_not_strict() -> None:
    truth = make_truth(
        kind="config_push",
        root_cause_category="bad_change",
        root_cause_node_id="S-TUN-001",
        affected_node_ids=["S-TUN-001", "S-TUN-002"],
    )
    report = make_report(root_cause_category="bad_change", root_cause_node_id="S-TUN-002", **RIGHT)
    s = score_case(make_artifact(make_result(report), truth=truth), TOPOLOGY)
    assert s.node_match == "acceptable" and s.rca_lenient and not s.rca_strict


# --- times ------------------------------------------------------------------------------------


def test_time_errors_are_absolute_minutes_and_null_when_absent() -> None:
    assert time_error_min("2026-09-02 17:30", CAUSE_AT) == 30.0
    assert time_error_min("2026-09-02 16:45", CAUSE_AT) == 15.0
    assert time_error_min(None, CAUSE_AT) is None
    assert time_error_min("", CAUSE_AT) is None
    assert time_error_min("sometime yesterday", CAUSE_AT) is None
    s = score({"impact_start": None, "root_cause_time": "2026-09-02 17:10"})
    assert s.impact_start_error_min is None and s.cause_time_error_min == 10.0


# --- evidence ---------------------------------------------------------------------------------


def test_evidence_that_did_not_exist_yet_is_not_expected() -> None:
    later = (ASKED_AT + timedelta(hours=1)).isoformat()
    truth = make_truth(
        evidence=[
            {"table": "alarms", "id": "ALM-000001", "visible_from": CAUSE_AT.isoformat()},
            {"table": "alarms", "id": "ALM-000002", "visible_from": later},
            {"table": "changes", "id": "CHG-1", "visible_from": ASKED_AT.isoformat()},
            {"table": "maintenance", "id": "MW-0001", "visible_from": None},
            {"table": "maintenance", "id": "MW-0002"},
        ]
    )
    assert [visible_at(r, ASKED_AT) for r in truth.evidence] == [True, False, True, True, True]
    result = make_result(
        make_report(findings=[], hypotheses=[], timeline=[], dismissed_signals=[]),
        calls=[make_call("T1", "get_alarms", rows=["ALM-000001", "CHG-1"])],
    )
    n, found, cited = evidence_shares(truth, result, ASKED_AT)
    assert n == 4 and found == 0.5 and cited == 0.0


def test_found_is_about_tool_results_and_cited_is_about_the_report() -> None:
    truth = make_truth(
        evidence=[
            {"table": "alarms", "id": "ALM-000001", "visible_from": None},
            {"table": "alarms", "id": "ALM-000002", "visible_from": None},
            {"table": "alarms", "id": "ALM-000003", "visible_from": None},
        ]
    )
    calls = [
        make_call("T1", "get_alarms", rows=["ALM-000001", "ALM-000002"]),
        make_call("T2", "run_sql", body="ALM-000003 raised 17:00"),  # in a body, not in row_refs
        make_call("T3", "get_alarms", rows=["ALM-000009"], duplicate_of="T1"),
    ]
    report = make_report()  # cites ALM-000001 only
    n, found, cited = evidence_shares(truth, make_result(report, calls=calls), ASKED_AT)
    assert (n, found) == (3, 1.0)
    assert cited == pytest.approx(1 / 3)


def test_no_visible_evidence_gives_null_shares() -> None:
    truth = make_truth(evidence=[])
    assert evidence_shares(truth, make_result(), ASKED_AT) == (0, None, None)


# --- confounders ------------------------------------------------------------------------------


def _confounded(report_over: dict[str, Any], calls: list[Any]) -> list[str]:
    truth = make_truth(
        confounders=[{"table": "changes", "id": "CHG-9", "why": "harmless", "visible_from": None}]
    )
    result = make_result(make_report(**report_over), calls=calls)
    return list(confounder_outcomes(truth, result, ASKED_AT))


def test_confounder_dismissed_blamed_ignored_or_not_seen() -> None:
    seen = [make_call("T1", "get_changes", rows=["CHG-9"])]
    dismissed = [DismissedSignal(ref="CHG-9", reason="harmless firmware patch")]
    assert _confounded({"dismissed_signals": dismissed}, seen) == ["dismissed"]
    blame = HypothesisEntry(
        category="transport_failure", node_id=None, verdict="confirmed", reason="r", refs=["CHG-9"]
    )
    assert _confounded({"hypotheses": [blame]}, seen) == ["blamed"]
    assert _confounded({"root_cause_summary": "The change CHG-9 broke it."}, seen) == ["blamed"]
    assert _confounded({}, seen) == ["seen_ignored"]
    assert _confounded({}, []) == ["not_seen"]


def test_citing_a_confounder_in_a_rejected_hypothesis_is_not_blaming_it() -> None:
    rejected = HypothesisEntry(
        category="bad_change", node_id=None, verdict="rejected", reason="r", refs=["CHG-9"]
    )
    seen = [make_call("T1", "get_changes", rows=["CHG-9"])]
    assert _confounded({"hypotheses": [rejected]}, seen) == ["seen_ignored"]


def test_the_worst_outcome_of_a_case_and_none_without_confounders() -> None:
    assert worst_outcome(["dismissed", "blamed"]) == "blamed"
    assert worst_outcome(["dismissed", "not_seen"]) == "not_seen"
    assert worst_outcome([]) is None
    assert score().confounder_outcome is None


# --- tools, verification, efficiency ----------------------------------------------------------


def test_tool_overlap_counts_the_models_choices_only() -> None:
    calls = [
        make_call("T1", "get_anomalies", node="orient"),
        make_call("T2", "get_alarms"),
        make_call("T3", "get_alarms", duplicate_of="T2"),
        make_call("T4", "get_maintenance"),
    ]
    precision, recall = tool_overlap(make_result(calls=calls), ["get_alarms", "query_kpis"])
    assert precision == 0.5 and recall == 0.5
    assert tool_overlap(make_result(calls=[]), ["get_alarms"]) == (None, 0.0)
    assert tool_overlap(make_result(calls=calls), []) == (0.0, None)


def test_verification_counts() -> None:
    assert verification_counts(make_result()) == (0, 0, False)
    repaired = make_result(issues=["[repaired] a", "[repaired] b", "unresolved: c"])
    assert verification_counts(repaired) == (2, 1, True)
    unrepaired = make_result(
        issues=["unresolved: x", "Removed 1 finding(s) without a valid reference."]
    )
    assert verification_counts(unrepaired) == (1, 1, False)
    steps = [LLMStep(node="repair", purpose="repair 1", provider="gemini", model="m")]
    assert verification_counts(make_result(steps=steps))[2] is True


def test_efficiency_cost_and_wall_time() -> None:
    steps = [
        LLMStep(node="investigate", purpose="t", provider="gemini", model="m", latency_ms=1500),
        LLMStep(node="conclude", purpose="c", provider="gemini", model="m", latency_ms=500),
        LLMStep(node="conclude", purpose="c", provider="-", model="-", latency_ms=9999, error="x"),
    ]
    calls = [make_call("T1", "get_alarms", wall_ms=250)]
    s = score(steps=steps, calls=calls, input_tokens=10_000_000, output_tokens=1_000_000)
    assert s.wall_seconds == 2.25  # failed steps are not counted
    assert s.total_tokens == 11_000_000
    assert s.cost_usd == pytest.approx(0.30 * 10 + 2.50 * 1)
    assert estimate_cost("groq:something", 1, 1) is None


def test_clean_means_no_other_model_answered() -> None:
    assert score().clean
    assert not score(models=["gemini:gemini-3.5-flash-lite", "gemini:gemini-3.1-flash-lite"]).clean
    assert not score(fell_back=True).clean


def test_confident_and_wrong() -> None:
    assert score({"confidence": "high", "root_cause_node_id": "S-TUN-003"}).confident_wrong
    assert not score({"confidence": "medium", "root_cause_node_id": "S-TUN-003"}).confident_wrong
    assert not score({"confidence": "high"}).confident_wrong


def test_an_infrastructure_error_is_not_scored() -> None:
    s = score_case(make_artifact(None, error="daily_quota: 429"), TOPOLOGY)
    assert s.status == "error" and s.error == "daily_quota: 429"
    assert not s.rca_lenient and s.node_match is None
    agg = aggregate([s, score()])
    assert (agg.n_cases, agg.n_errors) == (1, 1)
    assert agg.rca_lenient.n == 1


# --- faithfulness -----------------------------------------------------------------------------


def test_faithfulness_arithmetic() -> None:
    def grade(*verdicts: str) -> ReportGrade:
        return ReportGrade(
            case_id="c",
            grader="g",
            findings=[FindingGrade(index=i, verdict=v) for i, v in enumerate(verdicts)],  # type: ignore[arg-type]
        )

    assert (
        faithfulness(grade("supported", "partially_supported", "unsupported", "supported")) == 0.625
    )
    assert faithfulness(grade("supported", "not_verifiable")) == 1.0  # not_verifiable left out
    assert faithfulness(grade("not_verifiable")) is None
    assert faithfulness(grade()) is None


# --- aggregation ------------------------------------------------------------------------------


def _scores() -> list[CaseScore]:
    right = score()
    wrong_high = score({"root_cause_category": "bad_change", "confidence": "high"})
    wrong_low = score({"root_cause_category": "capacity", "confidence": "low"})
    medium = score({"confidence": "medium"})
    return [
        right.model_copy(update={"case_id": "a", "kind": "fiber_cut"}),
        wrong_high.model_copy(update={"case_id": "b", "kind": "fiber_cut"}),
        wrong_low.model_copy(update={"case_id": "c", "kind": "congestion"}),
        medium.model_copy(update={"case_id": "d", "kind": "congestion"}),
    ]


def test_aggregate_rates_and_intervals() -> None:
    agg = aggregate(_scores())
    assert agg.n_cases == 4
    assert (agg.rca_lenient.k, agg.rca_lenient.n) == (2, 4)
    assert agg.rca_lenient.value == 0.5
    assert agg.rca_lenient.lo is not None and agg.rca_lenient.hi is not None
    assert agg.rca_lenient.lo < 0.5 < agg.rca_lenient.hi
    assert agg.verdict_correct.k == 4
    assert agg.confident_wrong.k == 1
    assert (agg.high_confidence_wrong.k, agg.high_confidence_wrong.n) == (1, 2)
    assert agg.node_counts == {"exact": 4}


def test_calibration_table_has_every_level() -> None:
    rows = {r.confidence: r.accuracy for r in calibration(_scores())}
    assert (rows["low"].k, rows["low"].n) == (0, 1)
    assert (rows["medium"].k, rows["medium"].n) == (1, 1)
    assert (rows["high"].k, rows["high"].n) == (1, 2)


def test_grouping_by_kind() -> None:
    groups = group_by(_scores(), kind_of_case)
    assert list(groups) == ["congestion", "fiber_cut"]
    assert groups["fiber_cut"].rca_lenient.k == 1


def test_aggregate_of_nothing_is_empty_not_an_error() -> None:
    agg = aggregate([])
    assert agg.n_cases == 0 and agg.rca_lenient.value is None
    assert agg.total_tokens.p50 is None and agg.cost_usd is None
    assert agg.cause_time_error_min.mean is None


def test_distributions_have_percentiles() -> None:
    scores = [
        score(input_tokens=1000 * n, output_tokens=0).model_copy(update={"case_id": str(n)})
        for n in range(1, 11)
    ]
    agg = aggregate(scores)
    assert agg.total_tokens.p50 == 5500
    assert agg.total_tokens.p95 == pytest.approx(9550)
    assert agg.total_tokens.max == 10_000


# --- statistics -------------------------------------------------------------------------------


def test_wilson_interval_known_values() -> None:
    lo, hi = wilson_interval(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-3), pytest.approx(0.7634, abs=1e-3))
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-3)
    lo, hi = wilson_interval(11, 11)
    assert lo == pytest.approx(0.7412, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_wilson_interval_narrows_with_more_data() -> None:
    small = wilson_interval(8, 10)
    large = wilson_interval(80, 100)
    assert large[1] - large[0] < small[1] - small[0]


def test_bootstrap_interval() -> None:
    assert bootstrap_mean_ci([4.0, 4.0, 4.0]) == (4.0, 4.0)
    assert bootstrap_mean_ci([7.0]) == (7.0, 7.0)
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    lo, hi = bootstrap_mean_ci(values)
    assert lo < 5.5 < hi and lo >= 1.0 and hi <= 10.0
    assert bootstrap_mean_ci(values) == (lo, hi)  # seeded: repeatable
    with pytest.raises(ValueError):
        bootstrap_mean_ci([])


def test_percentile_and_mean() -> None:
    assert percentile([], 50) is None and mean([]) is None
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5
    assert mean([1, 2, 3]) == 2
