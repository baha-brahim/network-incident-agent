"""Score a whole run and describe it: the data behind `score`, `summary.json` and the report."""

from dataclasses import dataclass
from typing import Any

from incident_agent.evals.aggregate import (
    Aggregate,
    Rate,
    aggregate,
    class_of_case,
    difficulty_of_case,
    group_by,
    has_traps,
    kind_of_case,
    trap_of_case,
)
from incident_agent.evals.rundir import RunDir, RunMeta
from incident_agent.evals.scoring import CaseScore, dump_score, faithfulness, score_case
from incident_agent.evals.types import CaseArtifact, ReportGrade


@dataclass
class ScoredRun:
    meta: RunMeta
    scores: list[CaseScore]
    artifacts: dict[str, CaseArtifact]
    grades: dict[str, ReportGrade]

    @property
    def overall(self) -> Aggregate:
        return aggregate(self.scores)

    @property
    def n_present(self) -> int:
        return len(self.scores)

    @property
    def partial(self) -> bool:
        scored = sum(1 for s in self.scores if s.status == "scored")
        return scored < self.meta.cases_total

    def faithfulness_scores(self) -> dict[str, float]:
        """Faithfulness of each graded, scored case; cases with nothing gradable are left out."""
        out: dict[str, float] = {}
        for case_id, grade in self.grades.items():
            value = faithfulness(grade)
            if value is not None and case_id in self.artifacts:
                out[case_id] = value
        return out


def load_scored_run(run: RunDir) -> ScoredRun:
    meta = run.read_meta()
    if meta is None:
        raise FileNotFoundError(f"no run named {run.name!r} at {run.path}")
    topology = run.read_topology()
    artifacts = {a.case.case_id: a for a in run.load_artifacts()}
    # Cases come sorted by id.
    scores = [score_case(a, topology) for a in artifacts.values()]
    return ScoredRun(meta, scores, artifacts, run.load_grades())


def _rate(r: Rate) -> str:
    if r.value is None:
        return "n/a"
    return f"{r.k}/{r.n} = {r.value:.0%} [{r.lo:.0%}, {r.hi:.0%}]"


def summary_lines(scored: ScoredRun) -> list[str]:
    agg = scored.overall
    m = scored.meta
    lines = [
        f"run {m.name}: seed {m.seed} ({world_label(m)}), variant {m.variant}, "
        f"model {m.agent_model}",
        f"cases scored {agg.n_cases} of {m.cases_total}"
        + (f"; {agg.n_errors} infrastructure errors (not scored)" if agg.n_errors else "")
        + ("  [PARTIAL RUN]" if scored.partial else ""),
        "",
        f"  verdict correct        {_rate(agg.verdict_correct)}",
        f"  category correct       {_rate(agg.category_correct)}",
        f"  category in top 3      {_rate(agg.category_in_top3)}",
        f"  node exact             {_rate(agg.node_exact)}",
        f"  node exact/acceptable  {_rate(agg.node_acceptable_or_exact)}",
        f"  rca strict             {_rate(agg.rca_strict)}",
        f"  rca lenient            {_rate(agg.rca_lenient)}",
        f"  abstained              {_rate(agg.abstention)}",
        f"  confident and wrong    {_rate(agg.confident_wrong)}",
        f"  tokens per case        p50 {_num(agg.total_tokens.p50)}  "
        f"p95 {_num(agg.total_tokens.p95)}",
        f"  node matches           {agg.node_counts}",
    ]
    lines += checks_lines(scored.scores)
    if has_traps(scored.scores):
        lines.append("  by trap (rca lenient):")
        for trap, agg_t in group_by(scored.scores, trap_of_case).items():
            lines.append(f"    {trap:<34} {_rate(agg_t.rca_lenient)}")
    return lines


def checks_effect(scores: list[CaseScore]) -> dict[str, int] | None:
    """What the look-alike checks changed, counted on the same investigations: every case scored
    as its report stood before the checks, against how it scored after. None if none fired."""
    done = [s for s in scores if s.status == "scored"]
    fired = [s for s in done if s.before_checks is not None]
    if not fired:
        return None

    def before(s: CaseScore, field: str) -> bool:
        return bool(getattr(s.before_checks if s.before_checks is not None else s, field))

    return {
        "n": len(done),
        "fired": len(fired),
        "gained": sum(1 for s in fired if s.rca_lenient and not before(s, "rca_lenient")),
        "lost": sum(1 for s in fired if before(s, "rca_lenient") and not s.rca_lenient),
        "rca_lenient_before": sum(1 for s in done if before(s, "rca_lenient")),
        "rca_lenient_after": sum(1 for s in done if s.rca_lenient),
        "abstained_before": sum(1 for s in done if before(s, "abstained")),
        "abstained_after": sum(1 for s in done if s.abstained),
        "confident_wrong_before": sum(1 for s in done if before(s, "confident_wrong")),
        "confident_wrong_after": sum(1 for s in done if s.confident_wrong),
    }


def checks_lines(scores: list[CaseScore]) -> list[str]:
    e = checks_effect(scores)
    if e is None:
        return []
    return [
        f"  look-alike checks      fired on {e['fired']} of {e['n']} cases: "
        f"{e['gained']} became right, {e['lost']} became wrong",
        f"    before -> after      rca lenient {e['rca_lenient_before']} -> "
        f"{e['rca_lenient_after']}, abstained {e['abstained_before']} -> "
        f"{e['abstained_after']}, confident and wrong {e['confident_wrong_before']} -> "
        f"{e['confident_wrong_after']}",
    ]


def world_label(meta: RunMeta) -> str:
    """'test', 'dev' or 'hard, test': the split, and the profile when it is not default."""
    return meta.split if meta.profile == "default" else f"{meta.profile}, {meta.split}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def case_line(s: CaseScore) -> str:
    if s.status == "error":
        return f"{s.case_id:<20} {s.kind:<20} {s.difficulty:<7} ERROR {s.error}"
    flag = "ok   " if s.rca_lenient else "WRONG"
    return (
        f"{s.case_id:<20} {s.kind:<20} {s.difficulty:<7} {flag} "
        f"verdict={'y' if s.verdict_correct else 'N'} cat={'y' if s.category_correct else 'N'} "
        f"node={s.node_match:<10} conf={s.confidence:<6} "
        f"evid={_frac(s.evidence_found)}/{_frac(s.evidence_cited)} tokens={s.total_tokens}"
        + ("" if s.clean else "  [other model answered a step]")
    )


def _frac(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def summary_json(scored: ScoredRun) -> dict[str, Any]:
    """What `score` writes to `summary.json`."""
    by_trap = (
        {
            "by_trap": {
                k: v.model_dump(mode="json")
                for k, v in group_by(scored.scores, trap_of_case).items()
            }
        }
        if has_traps(scored.scores)
        else {}
    )
    return {
        "run": scored.meta.model_dump(mode="json", exclude={"invocations"}),
        "partial": scored.partial,
        "overall": scored.overall.model_dump(mode="json"),
        "by_kind": {
            k: v.model_dump(mode="json") for k, v in group_by(scored.scores, kind_of_case).items()
        },
        "by_difficulty": {
            k: v.model_dump(mode="json")
            for k, v in group_by(scored.scores, difficulty_of_case).items()
        },
        "by_class": {
            k: v.model_dump(mode="json") for k, v in group_by(scored.scores, class_of_case).items()
        },
        **({"checks": effect} if (effect := checks_effect(scored.scores)) else {}),
        **by_trap,
        "cases": [dump_score(s) for s in scored.scores],
    }
