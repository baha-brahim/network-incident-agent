"""Cohen's kappa against hand-computed values, pairing, the report-level bootstrap, formatting."""

import pytest

from incident_agent.evals.agreement import (
    Pair,
    bootstrap_kappa,
    cohen_kappa,
    collapse,
    compare_raters,
    confusion_matrix,
    format_agreement,
    pair_items,
    percent_agreement,
)
from incident_agent.evals.types import FindingGrade, ReportGrade


def test_kappa_two_classes_by_hand() -> None:
    # 50 items: both yes 20, A yes / B no 5, A no / B yes 10, both no 15.
    # po = 35/50 = 0.7; pe = 0.5 * 0.6 + 0.5 * 0.4 = 0.5; kappa = 0.2 / 0.5 = 0.4
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert percent_agreement(a, b) == pytest.approx(0.7)


def test_kappa_three_classes_by_hand() -> None:
    # po = 4/6; A has x2 y2 z2, B has x2 y3 z1; pe = (2*2 + 2*3 + 2*1) / 36 = 1/3
    # kappa = (2/3 - 1/3) / (1 - 1/3) = 0.5
    a = ["x", "x", "y", "y", "z", "z"]
    b = ["x", "y", "y", "y", "z", "x"]
    assert cohen_kappa(a, b) == pytest.approx(0.5)


def test_kappa_is_one_for_perfect_agreement_and_minus_one_for_a_full_swap() -> None:
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)
    assert cohen_kappa(["a", "b"], ["b", "a"]) == pytest.approx(-1.0)


def test_kappa_is_undefined_when_a_rater_uses_one_class() -> None:
    assert cohen_kappa(["a", "a", "a"], ["a", "a", "a"]) is None  # 0 / 0
    assert cohen_kappa(["a", "a", "a", "a"], ["a", "b", "a", "b"]) is None  # one rater constant
    assert cohen_kappa([], []) is None


def test_collapse_keeps_only_supported() -> None:
    assert [collapse(v) for v in ("supported", "partially_supported", "unsupported")] == [
        "supported", "other", "other",
    ]  # fmt: skip


def grade(case_id: str, *verdicts: str, start: int = 0) -> ReportGrade:
    return ReportGrade(
        case_id=case_id,
        grader="x",
        findings=[
            FindingGrade(index=start + i, verdict=v)  # type: ignore[arg-type]
            for i, v in enumerate(verdicts)
        ],
    )


def test_pairing_keeps_only_items_both_raters_graded() -> None:
    a = [grade("c1", "supported", "unsupported", "supported"), grade("c2", "supported")]
    b = [grade("c1", "supported", "supported"), grade("c3", "supported")]
    pairs = pair_items(a, b)
    assert pairs == [Pair("c1", 0, "supported", "supported"),
                     Pair("c1", 1, "unsupported", "supported")]  # fmt: skip


def test_confusion_matrix_rows_are_the_first_rater() -> None:
    pairs = [
        Pair("c", 0, "supported", "unsupported"),
        Pair("c", 1, "supported", "unsupported"),
        Pair("c", 2, "unsupported", "unsupported"),
    ]
    m = confusion_matrix(pairs)
    assert m["supported"]["unsupported"] == 2 and m["unsupported"]["unsupported"] == 1
    assert sum(sum(row.values()) for row in m.values()) == 3


def make_pairs() -> list[Pair]:
    verdicts = ["supported", "partially_supported", "unsupported", "not_verifiable"]
    pairs = []
    for case in range(12):
        for i in range(4):
            a = verdicts[(case + i) % 4]
            b = a if (case + i) % 5 else verdicts[(case + i + 1) % 4]
            pairs.append(Pair(f"c{case:02d}", i, a, b))
    return pairs


def test_bootstrap_interval_brackets_the_estimate_and_is_reproducible() -> None:
    pairs = make_pairs()
    first = bootstrap_kappa(pairs, collapsed=False, resamples=300)
    again = bootstrap_kappa(pairs, collapsed=False, resamples=300)
    assert first == again
    assert first.kappa is not None and first.ci_low is not None and first.ci_high is not None
    assert first.ci_low <= first.kappa <= first.ci_high
    assert first.resamples_used > 250


def test_the_bootstrap_resamples_reports_not_items() -> None:
    # Two reports whose items agree inside a report: report A all yes/yes, report B all no/no.
    # Item resampling would almost never produce a one-class sample; resampling reports does,
    # in half the draws, and those draws have undefined kappa and are skipped.
    pairs = [Pair("A", i, "supported", "supported") for i in range(5)]
    pairs += [Pair("B", i, "unsupported", "unsupported") for i in range(5)]
    result = bootstrap_kappa(pairs, collapsed=False, resamples=400)
    assert result.kappa == pytest.approx(1.0)
    assert 120 < result.resamples_used < 280  # about half of the 400 draws kept both reports


def test_a_single_report_gives_no_interval() -> None:
    pairs = [Pair("A", 0, "supported", "supported"), Pair("A", 1, "unsupported", "supported"),
             Pair("A", 2, "unsupported", "unsupported")]  # fmt: skip
    result = bootstrap_kappa(pairs, collapsed=False, resamples=100)
    assert result.kappa is not None and result.ci_low is None
    assert "too few reports" in result.note


def test_the_degenerate_case_is_reported_as_undefined() -> None:
    pairs = [Pair("A", i, "supported", "supported") for i in range(4)]
    result = bootstrap_kappa(pairs, collapsed=False, names=("human", "grader"))
    assert result.kappa is None and result.status == "undefined"
    assert "human and grader used a single verdict" in result.note
    assert bootstrap_kappa([], collapsed=True).note == "no items graded by both raters"


def test_compare_raters_and_the_summary_text() -> None:
    a = [grade("c1", "supported", "unsupported", "supported", "partially_supported"),
         grade("c2", "supported", "unsupported", "unsupported", "supported")]  # fmt: skip
    b = [grade("c1", "supported", "unsupported", "unsupported", "partially_supported"),
         grade("c2", "supported", "supported", "unsupported", "supported")]  # fmt: skip
    ag = compare_raters("human", a, "grader", b, resamples=100)
    assert ag.n_items == 8 and ag.n_reports == 2
    assert ag.percent_agreement == pytest.approx(6 / 8)
    # four-class: po .75; A and B both have s4 u3 p1; pe = (16 + 9 + 1) / 64 = 26/64
    assert ag.kappa_4class.kappa == pytest.approx((0.75 - 26 / 64) / (1 - 26 / 64))
    # binary: both have 4 supported and 4 other; 6 of 8 agree; pe = (16 + 16) / 64 = 0.5
    assert ag.kappa_binary.kappa == pytest.approx((0.75 - 0.5) / 0.5)
    text = format_agreement(ag)
    assert "human vs grader: 8 items in 2 reports, agreement 75%" in text
    assert "kappa, four verdicts" in text and "confusion (rows human, columns grader)" in text
