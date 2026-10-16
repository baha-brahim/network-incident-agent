"""The faithfulness grader: items, evidence text, packing into requests, verdicts, arithmetic."""

from typing import Any

import pytest

from incident_agent.agent.report import Finding, HypothesisEntry
from incident_agent.agent.types import EvidenceRef
from incident_agent.evals import grader
from incident_agent.evals.grader import (
    OMITTED,
    VERDICT_DEFINITIONS,
    VERDICTS,
    VerdictBatch,
    build_items,
    cut,
    evidence_text,
    faithfulness,
    grade_report,
    plan_batches,
)
from incident_agent.evals.types import FindingGrade, ReportGrade
from incident_agent.llm.testing import ScriptedRunner
from incident_agent.llm.types import AllModelsFailed, Attempt
from tests.grading_support import (
    TRUTH_KIND,
    TRUTH_NOTES,
    make_artifact,
    make_call,
    make_report,
    make_result,
    verdict_script,
)

# --- items ---------------------------------------------------------------------------------


def test_items_are_the_root_cause_then_every_finding_in_order() -> None:
    items = build_items(make_report())
    assert [i.index for i in items] == [-1, 0, 1, 2]
    assert [i.number for i in items] == [0, 1, 2, 3]
    assert [i.basis for i in items] == ["root cause", "observed", "observed", "inferred"]
    assert "Stated conclusion: incident, transport_failure at LNK-TUN-02-C" in items[0].claim


def test_root_cause_cites_the_matching_confirmed_hypothesis() -> None:
    hyps = [
        HypothesisEntry(category="power_failure", node_id="S-X", verdict="rejected",
                        reason="r", refs=["T9"]),
        HypothesisEntry(category="transport_failure", node_id="OTHER", verdict="confirmed",
                        reason="r", refs=["T8"]),
        HypothesisEntry(category="transport_failure", node_id="LNK-TUN-02-C",
                        verdict="confirmed", reason="r", refs=["T1", "T1", "ALM-000472"]),
    ]  # fmt: skip
    items = build_items(make_report(hypotheses=hyps))
    assert items[0].refs == ("T1", "ALM-000472")  # same node wins; duplicates dropped


def test_root_cause_falls_back_to_a_same_category_hypothesis_then_to_the_findings() -> None:
    same_category = [
        HypothesisEntry(category="transport_failure", node_id="OTHER", verdict="unresolved",
                        reason="r", refs=["T2"]),
    ]  # fmt: skip
    assert build_items(make_report(hypotheses=same_category))[0].refs == ("T2",)
    items = build_items(make_report(hypotheses=[]))
    assert items[0].refs == ("T1", "ALM-000472", "T2", "S-TUN-012")


def test_a_finding_without_references_is_still_an_item() -> None:
    report = make_report([Finding(claim="Nothing cited.", basis="inferred", refs=[])])
    assert [i.refs for i in build_items(report)][1] == ()


# --- evidence text -------------------------------------------------------------------------


def test_call_evidence_is_tool_arguments_and_output() -> None:
    text = evidence_text("T2", make_result()).text
    assert text.startswith("T2 get_changes(start=2026-09-21 15:00, node_ids=['S-TUN-012'])")
    assert "No changes on S-TUN-012" in text


def test_a_repeated_call_shows_the_output_of_the_original() -> None:
    text = evidence_text("T3", make_result()).text
    assert "(repeat of T1; same output)" in text and "ALM-000472" in text


def test_a_call_error_and_tool_truncation_are_visible() -> None:
    calls = [make_call("T1", "run_sql", "partial", error="timeout", truncated=True)]
    text = evidence_text("T1", make_result(calls=calls, evidence={})).text
    assert "error: timeout" in text and "the tool itself cut its output" in text


def test_row_evidence_is_the_summary_and_the_listing_line_with_its_continuation() -> None:
    ev = evidence_text("ALM-000472", make_result())
    assert ev.found and not ev.shortened
    assert ev.text.startswith("ALM-000472 (alarm): alarm critical LINK_LOS on LNK-TUN-02-C")
    assert "Listed by T1 (get_alarms):" in ev.text
    assert "2026-09-21 16:50 ALM-000472 critical LINK_LOS" in ev.text
    assert "detail line one of the alarm" in ev.text and "detail line two" in ev.text
    assert "ALM-000474" not in ev.text  # the next row is not part of this one


def test_a_row_the_call_output_does_not_list_names_its_source_call() -> None:
    calls = [make_call("T1", "get_anomalies", "2 alerts, no row ids here", row_refs=["ANM-000001"])]
    ev = {"ANM-000001": EvidenceRef(ref="ANM-000001", kind="anomaly", summary="S-1 drop")}
    text = evidence_text("ANM-000001", make_result(calls=calls, evidence=ev)).text
    assert "Returned by T1 (get_anomalies)." in text


def test_an_id_that_only_contains_the_ref_is_not_a_listing() -> None:
    body = "ALM-0004720 other row\nALM-000472 the row"
    calls = [make_call("T1", "get_alarms", body, row_refs=["ALM-000472"])]
    ev = {"ALM-000472": EvidenceRef(ref="ALM-000472", kind="alarm", summary="s")}
    text = evidence_text("ALM-000472", make_result(calls=calls, evidence=ev)).text
    assert "the row" in text and "other row" not in text


def test_a_reference_the_report_cannot_back_is_marked_missing() -> None:
    ev = evidence_text("T99", make_result())
    assert not ev.found and "not in the report's evidence" in ev.text


def test_a_node_reference_is_its_summary_only() -> None:
    assert evidence_text("S-TUN-012", make_result()).text == "S-TUN-012 (node): node site, TUN"


# --- cutting -------------------------------------------------------------------------------


def test_cut_leaves_short_text_alone_and_marks_what_it_removes() -> None:
    assert cut("short", 100) == ("short", False)
    text = "\n".join(f"line {n}" for n in range(100))
    out, shortened = cut(text, 120)
    assert shortened
    assert out.splitlines()[-1].startswith("[... shortened:")
    assert "line 99" not in out
    assert all(line.startswith(("line", "[...")) for line in out.splitlines())  # whole lines only
    assert cut(text, 120) == (out, True)  # deterministic


# --- packing -------------------------------------------------------------------------------


def call_body(n: int, size: int) -> str:
    return "\n".join(f"row {n}-{k} " + "x" * 60 for k in range(size // 70))


def big_result(n_findings: int = 6, size: int = 1900):  # type: ignore[no-untyped-def]
    calls = [make_call(f"T{n}", "get_alarms", call_body(n, size)) for n in range(1, n_findings + 1)]
    findings = [
        Finding(claim=f"Claim number {n}.", basis="observed", refs=[f"T{n}"])
        for n in range(1, n_findings + 1)
    ]
    evidence = {c.ref: EvidenceRef(ref=c.ref, kind="call", summary=c.headline) for c in calls}
    hyps = [HypothesisEntry(category="transport_failure", node_id="LNK-TUN-02-C",
                            verdict="confirmed", reason="r", refs=["T1"])]  # fmt: skip
    return make_result(make_report(findings, hypotheses=hyps), calls=calls, evidence=evidence)


def test_a_small_report_is_one_request() -> None:
    result = make_result()
    batches = plan_batches(build_items(result.report), result)
    assert len(batches) == 1 and len(batches[0].items) == 4


def test_a_large_report_is_split_and_no_item_is_lost_or_repeated() -> None:
    result = big_result()
    items = build_items(result.report)
    batches = plan_batches(items, result, budget=2500)
    assert len(batches) > 1
    assert [i.index for b in batches for i in b.items] == [i.index for i in items]  # in order
    assert all(grader.estimate(b) <= 2500 for b in batches)
    for b in batches:  # every cited reference has its text in its batch
        assert {r for i in b.items for r in i.refs} <= set(b.evidence)


def test_packing_is_deterministic() -> None:
    result = big_result()
    items = build_items(result.report)
    a = plan_batches(items, result, budget=2500)
    b = plan_batches(items, result, budget=2500)
    assert [x.messages() for x in a] == [x.messages() for x in b]


def test_an_item_too_large_alone_is_shortened_not_dropped() -> None:
    result = big_result(n_findings=1, size=1900)
    items = build_items(result.report)
    batches = plan_batches(items, result, budget=700)
    assert [i.index for b in batches for i in b.items] == [-1, 0]
    for batch in batches:
        ev = batch.evidence["T1"]
        assert ev.shortened
        assert "shortened" in ev.text or ev.text == OMITTED


def test_the_most_extreme_squeeze_omits_text_but_keeps_every_claim() -> None:
    result = big_result(n_findings=1, size=1900)
    items = build_items(result.report)
    batches = plan_batches(items, result, budget=100)
    assert [i.index for b in batches for i in b.items] == [-1, 0]
    assert all(b.evidence["T1"].text == OMITTED for b in batches)
    assert any("Claim number 1." in grader.render_request(b) for b in batches)


def test_the_request_shows_each_reference_once_and_numbers_the_claims() -> None:
    result = make_result()
    [batch] = plan_batches(build_items(result.report), result)
    text = grader.render_request(batch)
    assert text.count("### T1\n") == 1  # cited by the root cause and by finding 1
    assert "[0] (root cause)" in text and "[1] (observed) Link LNK-TUN-02-C" in text
    assert "cites: T1, ALM-000472" in text
    assert "[3] (inferred)" in text and "cites: S-TUN-012" in text


def test_a_claim_without_references_says_so() -> None:
    report = make_report([Finding(claim="Bare claim.", basis="inferred", refs=[])], hypotheses=[])
    result = make_result(report)
    [batch] = plan_batches(build_items(report), result)
    assert "cites: (nothing)" in grader.render_request(batch)


def test_the_prompt_carries_the_rubric_and_nothing_from_the_truth() -> None:
    artifact = make_artifact()
    assert artifact.result is not None
    items = build_items(artifact.result.report)
    [batch] = plan_batches(items, artifact.result)
    prompt = "\n".join(text for _, text in batch.messages())
    for name, definition in VERDICT_DEFINITIONS.items():
        assert f"- {name}: {definition}" in prompt
    assert TRUTH_NOTES not in prompt and TRUTH_KIND not in prompt


# --- grading -------------------------------------------------------------------------------


def test_grade_report_returns_one_grade_per_item() -> None:
    runner = ScriptedRunner(verdict_script({0: "supported", 1: "unsupported", 2: "supported",
                                           3: "partially_supported"}))  # fmt: skip
    grade = grade_report(make_artifact(), runner)
    assert [(f.index, f.verdict) for f in grade.findings] == [
        (-1, "supported"), (0, "unsupported"), (1, "supported"), (2, "partially_supported"),
    ]  # fmt: skip
    assert grade.case_id == "s42-SCN-001-q0" and grade.grader == "scripted:scripted"
    assert len(runner.calls) == 1
    assert grade.extra["usage"]["calls"] == 1 and grade.extra["batches"] == 1
    assert grade.extra["reasoning"] is False and grade.extra["no_verdict"] == []


def test_the_judge_is_called_with_the_structured_schema() -> None:
    runner = ScriptedRunner(verdict_script())
    grade_report(make_artifact(), runner)
    assert runner.calls[0].schema is VerdictBatch
    assert runner.calls[0].tools is None


def test_a_split_report_costs_one_call_per_batch_and_loses_nothing(monkeypatch) -> None:
    result = big_result()
    runner = ScriptedRunner(verdict_script())
    grade = grade_report(make_artifact(result=result), runner, budget=2500)
    assert len(runner.calls) > 1
    assert len(grade.findings) == 7
    assert grade.extra["batches"] == len(runner.calls)


def test_a_missing_verdict_is_asked_again_for_that_item_only() -> None:
    runner = ScriptedRunner(verdict_script({0: "supported", 1: "supported", 3: "supported"}))
    grade = grade_report(make_artifact(), runner)
    # the first answer left out claim 2; the second call is asked about claim 2 alone
    assert len(runner.calls) == 2
    second = runner.calls[1].messages[-1].text
    assert "[2] (observed)" in second and "[1] (" not in second
    assert grade.extra["no_verdict"] == [1]
    assert grade.findings[2].verdict == "not_verifiable"
    assert "no verdict" in grade.findings[2].reason


def test_a_verdict_for_an_unknown_claim_number_is_ignored() -> None:
    runner = ScriptedRunner(verdict_script({0: "supported", 1: "supported", 2: "supported",
                                           3: "supported", 9: "unsupported"}))  # fmt: skip
    grade = grade_report(make_artifact(), runner)
    assert sorted(f.index for f in grade.findings) == [-1, 0, 1, 2]


def test_a_crashed_case_cannot_be_graded() -> None:
    with pytest.raises(ValueError, match="no result"):
        grade_report(make_artifact(error="quota"), ScriptedRunner(verdict_script()))


def test_usage_is_summed_over_calls() -> None:
    runner = ScriptedRunner(verdict_script({0: "supported"}))
    grade = grade_report(make_artifact(), runner)
    usage = grade.extra["usage"]
    assert usage["calls"] == 2 and usage["input_tokens"] > 0
    assert usage["live_tokens"] == usage["input_tokens"] + usage["output_tokens"]


JSON_FAILED = (
    "BadRequestError: Error code: 400 - {'error': {'message': \"Failed to generate JSON.\", "
    "'code': 'json_validate_failed'}}"
)


def flaky(script: Any, errors: list[str]) -> Any:
    """A judge that raises the given errors on its first calls, then answers with `script`."""
    pending = list(errors)

    def judge(call: Any) -> Any:
        return failing(pending.pop(0)) if pending else script(call)

    return judge


def test_an_answer_in_invalid_json_is_asked_again() -> None:
    malformed = "MalformedOutput: structured output invalid (finish_reason=stop)"
    runner = ScriptedRunner(flaky(verdict_script(), [JSON_FAILED, malformed]))
    grade = grade_report(make_artifact(), runner)
    assert len(runner.calls) == 3 and grade.extra["usage"]["calls"] == 1
    assert {f.verdict for f in grade.findings} == {"supported"}


def test_invalid_json_every_time_still_fails_after_the_retries() -> None:
    runner = ScriptedRunner(flaky(verdict_script(), [JSON_FAILED] * 3))
    with pytest.raises(AllModelsFailed):
        grade_report(make_artifact(), runner)
    assert len(runner.calls) == 1 + grader.FORMAT_RETRIES


def test_a_rate_limit_is_not_retried_by_the_grader() -> None:
    runner = ScriptedRunner(flaky(verdict_script(), ["Rate limit reached: tokens per day (TPD)"]))
    with pytest.raises(AllModelsFailed):
        grade_report(make_artifact(), runner)
    assert len(runner.calls) == 1
    skipped = AllModelsFailed([Attempt(model="groq:m", status="skipped", error="cooling down")])
    assert not grader.is_bad_format(skipped) and grader.is_bad_format(failing(JSON_FAILED))


def test_the_daily_limit_is_recognised_in_the_attempts() -> None:
    daily = failing("Rate limit reached ... tokens per day (TPD)")
    minute = failing("Rate limit reached ... tokens per minute (TPM)")
    assert grader.is_daily_limit(daily) and not grader.is_daily_limit(minute)


# --- faithfulness --------------------------------------------------------------------------


def failing(error: str) -> AllModelsFailed:
    return AllModelsFailed([Attempt(model="groq:m", status="error", error=error)])


def grades(*verdicts: str) -> list[FindingGrade]:
    return [FindingGrade(index=i, verdict=v) for i, v in enumerate(verdicts)]  # type: ignore[arg-type]


def test_faithfulness_scores_supported_one_partial_half_unsupported_zero() -> None:
    f = faithfulness(grades("supported", "partially_supported", "unsupported", "supported"))
    assert f.score == pytest.approx((1 + 0.5 + 0 + 1) / 4)
    assert f.n_items == 4 and f.n_scored == 4 and f.n_not_verifiable == 0


def test_not_verifiable_items_are_counted_apart_and_left_out_of_the_mean() -> None:
    f = faithfulness(grades("supported", "not_verifiable", "unsupported", "not_verifiable"))
    assert f.score == pytest.approx(0.5)
    assert f.n_items == 4 and f.n_scored == 2 and f.n_not_verifiable == 2
    assert f.counts == {"supported": 1, "partially_supported": 0, "unsupported": 1,
                        "not_verifiable": 2}  # fmt: skip


def test_faithfulness_is_undefined_when_nothing_can_be_scored() -> None:
    assert faithfulness(grades("not_verifiable")).score is None
    assert faithfulness([]).score is None


def test_all_four_verdicts_have_a_definition() -> None:
    assert set(VERDICT_DEFINITIONS) == set(VERDICTS)


# --- files ---------------------------------------------------------------------------------


def test_a_grade_survives_a_json_round_trip() -> None:
    grade = grade_report(make_artifact(), ScriptedRunner(verdict_script()))
    again = ReportGrade.model_validate_json(grade.model_dump_json())
    assert again == grade
