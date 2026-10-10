"""Aggregation of case scores: rates with Wilson intervals, means with bootstrap intervals,
percentiles, groupings, and the calibration table."""

from collections import Counter
from collections.abc import Callable, Sequence

from pydantic import BaseModel, Field

from incident_agent.evals.scoring import CONFIDENCE_LEVELS, CaseScore
from incident_agent.evals.stats import bootstrap_mean_ci, mean, percentile, wilson_interval


class Rate(BaseModel):
    k: int
    n: int
    value: float | None  # None when n == 0
    lo: float | None
    hi: float | None


class MeanStat(BaseModel):
    n: int
    mean: float | None
    median: float | None
    lo: float | None
    hi: float | None


class Dist(BaseModel):
    n: int
    mean: float | None
    p50: float | None
    p95: float | None
    max: float | None


class CalibrationRow(BaseModel):
    confidence: str
    accuracy: Rate  # rca_lenient among the reports with this confidence


class Aggregate(BaseModel):
    n_cases: int  # scored cases
    n_errors: int  # infrastructure errors, not counted anywhere below
    verdict_correct: Rate
    abstention: Rate
    category_correct: Rate
    category_in_top3: Rate
    node_exact: Rate
    node_acceptable_or_exact: Rate
    rca_strict: Rate
    rca_lenient: Rate
    confident_wrong: Rate  # high confidence and not rca_lenient, out of all scored cases
    high_confidence_wrong: Rate  # the same, out of the high-confidence reports only
    node_counts: dict[str, int]
    cause_time_error_min: MeanStat
    impact_start_error_min: MeanStat
    evidence_found: MeanStat
    evidence_cited: MeanStat
    tool_precision: MeanStat
    tool_recall: MeanStat
    confounder_counts: dict[str, int]
    repaired: Rate
    citation_issues: MeanStat
    clean: Rate
    calibration: list[CalibrationRow]
    model_calls: Dist
    tool_calls: Dist
    input_tokens: Dist
    output_tokens: Dist
    total_tokens: Dist
    wall_seconds: Dist
    cost_usd: Dist | None  # None when no case has a list price
    cost_total_usd: float | None
    extra: dict[str, float] = Field(default_factory=dict)


def rate(k: int, n: int) -> Rate:
    if n == 0:
        return Rate(k=0, n=0, value=None, lo=None, hi=None)
    lo, hi = wilson_interval(k, n)
    return Rate(k=k, n=n, value=k / n, lo=lo, hi=hi)


def rate_of(scores: Sequence[CaseScore], pred: Callable[[CaseScore], bool]) -> Rate:
    return rate(sum(1 for s in scores if pred(s)), len(scores))


def mean_stat(values: Sequence[float]) -> MeanStat:
    if not values:
        return MeanStat(n=0, mean=None, median=None, lo=None, hi=None)
    lo, hi = bootstrap_mean_ci(values)
    return MeanStat(n=len(values), mean=mean(values), median=percentile(values, 50), lo=lo, hi=hi)


def dist(values: Sequence[float]) -> Dist:
    return Dist(
        n=len(values),
        mean=mean(values),
        p50=percentile(values, 50),
        p95=percentile(values, 95),
        max=max(values) if values else None,
    )


def _present(values: Sequence[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def calibration(scored: Sequence[CaseScore]) -> list[CalibrationRow]:
    return [
        CalibrationRow(
            confidence=level,
            accuracy=rate_of([s for s in scored if s.confidence == level], lambda s: s.rca_lenient),
        )
        for level in CONFIDENCE_LEVELS
    ]


def aggregate(scores: Sequence[CaseScore]) -> Aggregate:
    scored = [s for s in scores if s.status == "scored"]
    high = [s for s in scored if s.confidence == "high"]
    costs = _present([s.cost_usd for s in scored])
    return Aggregate(
        n_cases=len(scored),
        n_errors=len(scores) - len(scored),
        verdict_correct=rate_of(scored, lambda s: s.verdict_correct),
        abstention=rate_of(scored, lambda s: s.abstained),
        category_correct=rate_of(scored, lambda s: s.category_correct),
        category_in_top3=rate_of(scored, lambda s: s.category_in_top3),
        node_exact=rate_of(scored, lambda s: s.node_match == "exact"),
        node_acceptable_or_exact=rate_of(scored, lambda s: s.node_match in ("exact", "acceptable")),
        rca_strict=rate_of(scored, lambda s: s.rca_strict),
        rca_lenient=rate_of(scored, lambda s: s.rca_lenient),
        confident_wrong=rate_of(scored, lambda s: s.confident_wrong),
        high_confidence_wrong=rate_of(high, lambda s: s.confident_wrong),
        node_counts=dict(sorted(Counter(s.node_match or "none" for s in scored).items())),
        cause_time_error_min=mean_stat(_present([s.cause_time_error_min for s in scored])),
        impact_start_error_min=mean_stat(_present([s.impact_start_error_min for s in scored])),
        evidence_found=mean_stat(_present([s.evidence_found for s in scored])),
        evidence_cited=mean_stat(_present([s.evidence_cited for s in scored])),
        tool_precision=mean_stat(_present([s.tool_precision for s in scored])),
        tool_recall=mean_stat(_present([s.tool_recall for s in scored])),
        confounder_counts=dict(
            sorted(Counter(s.confounder_outcome for s in scored if s.confounder_outcome).items())
        ),
        repaired=rate_of(scored, lambda s: s.repaired),
        citation_issues=mean_stat([float(s.citation_issues) for s in scored]),
        clean=rate_of(scored, lambda s: s.clean),
        calibration=calibration(scored),
        model_calls=dist([float(s.model_calls) for s in scored]),
        tool_calls=dist([float(s.tool_calls) for s in scored]),
        input_tokens=dist([float(s.input_tokens) for s in scored]),
        output_tokens=dist([float(s.output_tokens) for s in scored]),
        total_tokens=dist([float(s.total_tokens) for s in scored]),
        wall_seconds=dist([s.wall_seconds for s in scored]),
        cost_usd=dist(costs) if costs else None,
        cost_total_usd=sum(costs) if costs else None,
    )


def group_by(scores: Sequence[CaseScore], key: Callable[[CaseScore], str]) -> dict[str, Aggregate]:
    groups: dict[str, list[CaseScore]] = {}
    for s in scores:
        groups.setdefault(key(s), []).append(s)
    return {k: aggregate(v) for k, v in sorted(groups.items())}


def kind_of_case(s: CaseScore) -> str:
    return s.kind


def difficulty_of_case(s: CaseScore) -> str:
    return s.difficulty


def class_of_case(s: CaseScore) -> str:
    return "real incident" if s.is_incident else "red herring"
