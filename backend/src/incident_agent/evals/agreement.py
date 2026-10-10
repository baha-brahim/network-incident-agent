"""Agreement between two raters of the same items (a person and the grader, or two grader runs).

Items are paired on (case_id, finding index); an item graded by only one rater is left out. Cohen's
kappa is computed at item level for the four verdicts and for supported vs everything else. Items
of one report are correlated, so the bootstrap resamples reports, not items.

Kappa is undefined when one rater uses a single verdict for every paired item: the chance-corrected
measure carries no information then (the formula gives 0, or 0/0 if both raters use the same single
verdict). It is reported as undefined, with the reason, and percent agreement is still given.
"""

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from incident_agent.evals.grader import SCORE, VERDICTS
from incident_agent.evals.types import ReportGrade

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260101


@dataclass(frozen=True)
class Pair:
    case_id: str
    index: int
    a: str
    b: str


def pair_items(a: Sequence[ReportGrade], b: Sequence[ReportGrade]) -> list[Pair]:
    """Items graded by both raters, ordered by case then finding index."""
    left = {(g.case_id, f.index): f.verdict for g in a for f in g.findings}
    right = {(g.case_id, f.index): f.verdict for g in b for f in g.findings}
    return [Pair(c, i, left[(c, i)], right[(c, i)]) for (c, i) in sorted(left) if (c, i) in right]


def percent_agreement(a: Sequence[str], b: Sequence[str]) -> float | None:
    if not a:
        return None
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's kappa = (po - pe) / (1 - pe); None if a rater used one class only, or no items."""
    n = len(a)
    if n == 0 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca.keys() & cb.keys()) / (n * n)
    return (po - pe) / (1 - pe)


def collapse(verdict: str) -> str:
    return "supported" if verdict == "supported" else "other"


class KappaResult(BaseModel):
    kappa: float | None
    ci_low: float | None = None
    ci_high: float | None = None
    status: str = "ok"  # ok | undefined
    note: str = ""
    resamples_used: int = 0  # bootstrap resamples where kappa was defined


class Agreement(BaseModel):
    rater_a: str
    rater_b: str
    n_reports: int
    n_items: int
    percent_agreement: float | None
    kappa_4class: KappaResult
    kappa_binary: KappaResult
    confusion: dict[str, dict[str, int]]  # confusion[a_verdict][b_verdict]
    mean_faithfulness_a: float | None
    mean_faithfulness_b: float | None


def _undefined_note(a: Sequence[str], b: Sequence[str], name_a: str, name_b: str) -> str:
    if not a:
        return "no items graded by both raters"
    single = [n for n, v in ((name_a, a), (name_b, b)) if len(set(v)) < 2]
    return f"{' and '.join(single)} used a single verdict for every item"


def bootstrap_kappa(
    pairs: Sequence[Pair],
    *,
    collapsed: bool,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    names: tuple[str, str] = ("rater A", "rater B"),
) -> KappaResult:
    """Kappa on all pairs, with a 95 % interval from resampling reports with replacement."""
    f = collapse if collapsed else (lambda v: v)
    a = [f(p.a) for p in pairs]
    b = [f(p.b) for p in pairs]
    point = cohen_kappa(a, b)
    if point is None:
        return KappaResult(kappa=None, status="undefined", note=_undefined_note(a, b, *names))
    by_case: dict[str, list[Pair]] = {}
    for p in pairs:
        by_case.setdefault(p.case_id, []).append(p)
    cases = sorted(by_case)
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(resamples):
        sample = [p for c in rng.choices(cases, k=len(cases)) for p in by_case[c]]
        k = cohen_kappa([f(p.a) for p in sample], [f(p.b) for p in sample])
        if k is not None:
            stats.append(k)
    if len(cases) < 2 or len(stats) < 20:
        return KappaResult(
            kappa=point,
            note="too few reports for an interval",
            resamples_used=len(stats),
        )
    stats.sort()
    lo = stats[int(0.025 * (len(stats) - 1))]
    hi = stats[int(0.975 * (len(stats) - 1) + 0.9999)]
    return KappaResult(kappa=point, ci_low=lo, ci_high=hi, resamples_used=len(stats))


def confusion_matrix(pairs: Sequence[Pair]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {a: dict.fromkeys(VERDICTS, 0) for a in VERDICTS}
    for p in pairs:
        matrix[p.a][p.b] += 1
    return matrix


def _mean_faithfulness(verdicts: Sequence[str]) -> float | None:
    scored = [SCORE[v] for v in verdicts if v in SCORE]
    return sum(scored) / len(scored) if scored else None


def compare_raters(
    name_a: str,
    grades_a: Sequence[ReportGrade],
    name_b: str,
    grades_b: Sequence[ReportGrade],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> Agreement:
    pairs = pair_items(grades_a, grades_b)
    a = [p.a for p in pairs]
    b = [p.b for p in pairs]
    names = (name_a, name_b)
    return Agreement(
        rater_a=name_a,
        rater_b=name_b,
        n_reports=len({p.case_id for p in pairs}),
        n_items=len(pairs),
        percent_agreement=percent_agreement(a, b),
        kappa_4class=bootstrap_kappa(pairs, collapsed=False, resamples=resamples, names=names),
        kappa_binary=bootstrap_kappa(pairs, collapsed=True, resamples=resamples, names=names),
        confusion=confusion_matrix(pairs),
        mean_faithfulness_a=_mean_faithfulness(a),
        mean_faithfulness_b=_mean_faithfulness(b),
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.0f}%"


def _kappa_line(label: str, k: KappaResult) -> str:
    if k.kappa is None:
        return f"  {label}: undefined ({k.note})"
    ci = f" (95% CI {k.ci_low:.2f} to {k.ci_high:.2f})" if k.ci_low is not None else ""
    note = f" [{k.note}]" if k.note else ""
    return f"  {label}: {k.kappa:.2f}{ci}{note}"


def format_agreement(ag: Agreement) -> str:
    lines = [
        f"{ag.rater_a} vs {ag.rater_b}: {ag.n_items} items in {ag.n_reports} reports, "
        f"agreement {_pct(ag.percent_agreement)}",
        _kappa_line("kappa, four verdicts", ag.kappa_4class),
        _kappa_line("kappa, supported vs other", ag.kappa_binary),
        f"  mean faithfulness on these items: {ag.rater_a} "
        f"{_fmt(ag.mean_faithfulness_a)}, {ag.rater_b} {_fmt(ag.mean_faithfulness_b)}",
        f"  confusion (rows {ag.rater_a}, columns {ag.rater_b}):",
    ]
    short = {
        "supported": "supp",
        "partially_supported": "part",
        "unsupported": "unsu",
        "not_verifiable": "n/v",
    }
    lines.append("    " + " " * 6 + "".join(f"{short[v]:>6}" for v in VERDICTS))
    for row in VERDICTS:
        counts = "".join(f"{ag.confusion[row][col]:>6}" for col in VERDICTS)
        lines.append(f"    {short[row]:<6}{counts}")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"
