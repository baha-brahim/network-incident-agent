"""The results report: `docs/results/evaluation.md`, `.json` and charts, from any set of runs."""

# ruff: noqa: E501  (the report prose is written as long lines of text)

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incident_agent.evals import charts
from incident_agent.evals.aggregate import (
    Aggregate,
    Dist,
    MeanStat,
    Rate,
    aggregate,
    class_of_case,
    difficulty_of_case,
    group_by,
    kind_of_case,
)
from incident_agent.evals.pricing import LIST_PRICES
from incident_agent.evals.rundir import RunDir, dumps, write_text
from incident_agent.evals.scoring import PEER_KINDS, CaseScore
from incident_agent.evals.stats import bootstrap_mean_ci, mean
from incident_agent.evals.summary import ScoredRun, load_scored_run

BASENAME = "evaluation"
DEV_NOTE = "dev world: the prompts were developed on it, so these numbers are optimistic"
LARGE_TIME_ERROR_MIN = 45.0


# --- formatting -------------------------------------------------------------------------------


def pct_rate(r: Rate) -> str:
    if r.value is None or r.lo is None or r.hi is None:
        return "n/a"
    return f"{r.k}/{r.n} ({r.value:.0%}) [{r.lo:.0%} to {r.hi:.0%}]"


def short_rate(r: Rate) -> str:
    return "-" if r.value is None else f"{r.k}/{r.n} ({r.value:.0%})"


def mean_ci(m: MeanStat, digits: int = 2, scale: float = 1.0) -> str:
    if m.mean is None or m.lo is None or m.hi is None:
        return "n/a"
    return f"{m.mean * scale:.{digits}f} [{m.lo * scale:.{digits}f} to {m.hi * scale:.{digits}f}] (n={m.n})"


def dist_cell(d: Dist, digits: int = 0) -> str:
    if d.p50 is None or d.p95 is None:
        return "n/a"
    return f"{d.p50:,.{digits}f} / {d.p95:,.{digits}f}"


def money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def minutes(m: MeanStat) -> str:
    if m.median is None or m.mean is None:
        return "n/a"
    return f"median {m.median:.0f}, mean {m.mean:.0f} (n={m.n})"


def esc(text: str) -> str:
    return " ".join(text.replace("|", "/").split())


def run_label(run: ScoredRun) -> str:
    return run.meta.name


# --- ordering ---------------------------------------------------------------------------------


def order_runs(runs: Sequence[ScoredRun]) -> list[ScoredRun]:
    """Test runs first, then dev; default variant first; then by name."""
    return sorted(
        runs,
        key=lambda r: (r.meta.split != "test", r.meta.variant != "default", r.meta.name),
    )


def baselines(runs: Sequence[ScoredRun]) -> list[ScoredRun]:
    base = [r for r in runs if r.meta.variant == "default"]
    return base or list(runs)


# --- ablations --------------------------------------------------------------------------------


@dataclass
class Ablation:
    variant: ScoredRun
    base: ScoredRun
    common: list[str]  # case ids scored in both


def find_ablations(runs: Sequence[ScoredRun]) -> list[Ablation]:
    out: list[Ablation] = []
    for run in runs:
        if run.meta.variant == "default":
            continue
        candidates = [
            r for r in runs if r.meta.variant == "default" and r.meta.seed == run.meta.seed
        ]
        best: Ablation | None = None
        for base in candidates:
            ok = {s.case_id for s in base.scores if s.status == "scored"}
            common = sorted(ok & {s.case_id for s in run.scores if s.status == "scored"})
            if best is None or len(common) > len(best.common):
                best = Ablation(run, base, common)
        if best is not None and best.common:
            out.append(best)
    return out


def paired(ab: Ablation) -> dict[str, Any]:
    by_id_v = {s.case_id: s for s in ab.variant.scores}
    by_id_b = {s.case_id: s for s in ab.base.scores}
    b = [by_id_b[c] for c in ab.common]
    v = [by_id_v[c] for c in ab.common]
    gained = [
        c for c, x, y in zip(ab.common, b, v, strict=True) if y.rca_lenient and not x.rca_lenient
    ]
    lost = [
        c for c, x, y in zip(ab.common, b, v, strict=True) if x.rca_lenient and not y.rca_lenient
    ]
    return {
        "variant": ab.variant.meta.name,
        "variant_kind": ab.variant.meta.variant,
        "base": ab.base.meta.name,
        "n": len(ab.common),
        "base_aggregate": aggregate(b),
        "variant_aggregate": aggregate(v),
        "gained": gained,
        "lost": lost,
    }


# --- examples of failure ---------------------------------------------------------------------


def failure_examples(
    runs: Sequence[ScoredRun], limit: int = 3
) -> list[tuple[ScoredRun, CaseScore]]:
    """Wrong cases, worst first: confident and wrong, then wrong verdict, then the rest."""
    found: list[tuple[int, str, ScoredRun, CaseScore]] = []
    for run in runs:
        for s in run.scores:
            if s.status != "scored" or s.rca_lenient:
                continue
            rank = 0 if s.confident_wrong else 1 if not s.verdict_correct else 2
            found.append((rank, f"{run.meta.name}/{s.case_id}", run, s))
    found.sort(key=lambda t: (t[0], t[1]))
    return [(run, s) for _, _, run, s in found[:limit]]


def imperfections(run: ScoredRun) -> list[str]:
    """Things worth knowing about in cases that were counted as correct."""
    out: list[str] = []
    for s in run.scores:
        if s.status != "scored" or not s.rca_lenient:
            continue
        notes: list[str] = []
        if s.node_match == "acceptable":
            notes.append(f"named {s.report_node}, a peer of the labelled node {s.truth_node}")
        if s.impact_start_error_min is not None and s.impact_start_error_min > LARGE_TIME_ERROR_MIN:
            notes.append(f"impact start off by {s.impact_start_error_min:.0f} min")
        if s.confounder_outcome == "seen_ignored":
            notes.append("saw the confounder but neither dismissed nor blamed it")
        if s.repaired:
            notes.append(f"needed a repair call ({s.citation_issues} verification problem(s))")
        if not s.clean:
            notes.append("a step was answered by another model than the configured one")
        if notes:
            out.append(f"- `{s.case_id}` ({s.kind}, {s.difficulty}): {'; '.join(notes)}.")
    return out


# --- markdown ---------------------------------------------------------------------------------

METRICS: list[tuple[str, str]] = [
    (
        "verdict correct",
        "The report's classification equals the planted one: `incident`, or for the red herrings `planned_maintenance`, `expected_event`, `no_impact`. `inconclusive` is never correct.",
    ),
    ("category correct", "`root_cause_category` equals the planted category."),
    (
        "category in top 3",
        "The planted category is the stated root cause or among the first three ranked hypotheses.",
    ),
    (
        "node exact / acceptable / related / wrong",
        "How the stated root-cause node compares with the label. `exact`: the same node. `acceptable`: a peer the label could equally have named (rules below). `related`: an ancestor or descendant of the labelled node. `wrong`: anything else, including no node.",
    ),
    ("root cause, strict", "Verdict, category and node all correct, with node `exact`."),
    (
        "root cause, lenient",
        "The same, with node `exact` or `acceptable`. This is the headline accuracy.",
    ),
    (
        "abstained",
        "The report is `inconclusive`. Counted as wrong for accuracy, and shown separately.",
    ),
    (
        "high confidence and wrong",
        "The report says `high` confidence and the lenient root cause is not right. The worst failure.",
    ),
    (
        "impact start / cause time error",
        "Absolute difference in minutes between the reported time and the planted one. Empty when the report gives no time.",
    ),
    (
        "evidence found / cited",
        "Of the planted evidence rows (alarms, changes, events, maintenance windows) that existed at the time of the question, the share that appeared in a tool result / that the report cites by id.",
    ),
    (
        "confounder outcome",
        "For cases with a planted harmless look-alike (a change or alarm just before the incident): `dismissed` (listed under dismissed signals), `blamed` (cited by the confirmed hypothesis or named in the root-cause summary), `seen_ignored` (shown by a tool, never addressed), `not_seen`.",
    ),
    (
        "tool precision / recall",
        "Distinct tools the model chose to call (the code-driven first lookups are excluded) against the tools expected for the scenario.",
    ),
    (
        "citation issues / repaired",
        "Problems the verification step found in the first draft (unknown references, bad times, wrong node ids), and whether a repair call was needed.",
    ),
    (
        "faithfulness",
        "Share of the report's claims that the cited evidence supports, judged by a grader model (see below).",
    ),
]


def node_rules() -> list[str]:
    peers = ", ".join(f"`{k}`" for k in sorted(PEER_KINDS))
    return [
        f"- Peers (`acceptable`) exist only for {peers}: a cause that hits several equal nodes "
        "(the sites of a pushed group, two congested sites, the sites around a venue), where the "
        "label names one of them. Any other affected node counts. A configuration push to a "
        "router is labelled with the router, so its sites are not peers.",
        "- Every other kind has a single labelled node (the link of a fibre cut or microwave "
        "degradation, the site of a power outage or alarm storm, the DNS node, the node a "
        "maintenance window concerns): only that node is `exact`.",
        "- The public holiday has no node. A report with no node is `exact`; naming a node is `wrong`.",
        "- `related` means the named node is an ancestor or descendant of the label in the "
        "dependency tree (site, link, router, core). It is not counted as correct.",
    ]


def _headline_table(base: Sequence[ScoredRun]) -> list[str]:
    head = ["| metric |"] + [f" {run_label(r)} ({r.meta.split}) |" for r in base]
    rows = [
        "".join(head),
        "|---|" + "---|" * len(base),
    ]
    aggs = [r.overall for r in base]

    def row(label: str, fn: Any) -> None:
        rows.append(f"| {label} | " + " | ".join(fn(a) for a in aggs) + " |")

    row("cases scored", lambda a: f"{a.n_cases}")
    row("verdict correct", lambda a: pct_rate(a.verdict_correct))
    row("category correct", lambda a: pct_rate(a.category_correct))
    row("category in top 3", lambda a: pct_rate(a.category_in_top3))
    row("node exact", lambda a: pct_rate(a.node_exact))
    row("**root cause, strict**", lambda a: pct_rate(a.rca_strict))
    row("**root cause, lenient**", lambda a: pct_rate(a.rca_lenient))
    row("abstained", lambda a: pct_rate(a.abstention))
    row("high confidence and wrong", lambda a: pct_rate(a.confident_wrong))
    return rows


def _group_table(groups: dict[str, Aggregate]) -> list[str]:
    rows = [
        "| group | cases | verdict | category | root cause, strict | root cause, lenient | abstained |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, a in groups.items():
        rows.append(
            f"| {key} | {a.n_cases} | {short_rate(a.verdict_correct)} | "
            f"{short_rate(a.category_correct)} | {short_rate(a.rca_strict)} | "
            f"{short_rate(a.rca_lenient)} | {short_rate(a.abstention)} |"
        )
    return rows


def _case_table(run: ScoredRun) -> list[str]:
    rows = [
        "| case | kind | difficulty | planted | reported | node | confidence | right | evidence found / cited | tokens |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in run.scores:
        if s.status == "error":
            rows.append(
                f"| {s.case_id} | {s.kind} | {s.difficulty} | {s.truth_category} @ {s.truth_node or '-'} "
                f"| ERROR | | | | | {esc(s.error or '')[:80]} |"
            )
            continue
        ev = (
            "-"
            if s.evidence_found is None or s.evidence_cited is None
            else f"{s.evidence_found:.2f} / {s.evidence_cited:.2f}"
        )
        flag = "yes" if s.rca_lenient else "NO"
        rows.append(
            f"| {s.case_id} | {s.kind} | {s.difficulty} | {s.truth_category} @ {s.truth_node or '-'} "
            f"| {s.report_classification}/{s.report_category} @ {s.report_node or '-'} "
            f"| {s.node_match} | {s.confidence} | {flag} | {ev} | {s.total_tokens:,} |"
        )
    return rows


def _failure_block(run: ScoredRun, s: CaseScore) -> list[str]:
    art = run.artifacts[s.case_id]
    assert art.result is not None
    report = art.result.report
    truth = art.truth
    summary = esc(report.root_cause_summary)
    if len(summary) > 360:
        summary = summary[:357] + "..."
    return [
        f"**{s.case_id}** ({run.meta.name}; {s.kind}, {s.difficulty})",
        "",
        f"- Question: {esc(art.case.question)}",
        f"- Planted: {s.truth_classification} / {s.truth_category} at {s.truth_node or 'no node'}.",
        f"- Reported: {s.report_classification} / {s.report_category} at {s.report_node or 'no node'}, "
        f"confidence {s.confidence}; node match `{s.node_match}`.",
        f"- The report says: {summary}",
        f"- Planted notes: {esc(truth.notes)}",
        "",
    ]


def render_markdown(
    runs: Sequence[ScoredRun],
    ablations: Sequence[dict[str, Any]],
    chart_files: dict[str, str],
) -> str:
    base = baselines(runs)
    L: list[str] = []
    add = L.append
    add("# Evaluation of the investigation agent")
    add("")
    add(
        "This page measures whether the agent finds the *right* cause of a network incident. The "
        "synthetic network contains planted incidents and red herrings with known labels, so "
        "everything below that can be scored in code is scored in code, from those labels. A "
        "grader model is used only for one thing code cannot judge: whether each claim in a "
        "report is supported by the evidence it cites."
    )
    add("")
    add(
        "Two worlds are used. **Seed 42 is the dev world**: the prompts were written while looking "
        "at it, so its numbers are optimistic. **Seed 7 is the test world**: never looked at and "
        "never tuned on. Headline numbers come from the test world."
    )
    add("")

    partial = [r for r in runs if r.partial]
    if partial:
        add("> **Partial results.** " + " ".join(_partial_sentence(r) for r in partial))
        add("")
    if not any(r.meta.split == "test" for r in runs):
        add(
            "> **No test-world run is included yet.** Every number here comes from the dev world "
            "and is optimistic."
        )
        add("")

    add("## Runs")
    add("")
    add(
        "| run | world | variant | model | cases scored | infrastructure errors | other model answered a step |"
    )
    add("|---|---|---|---|---|---|---|")
    for r in runs:
        a = r.overall
        unclean = a.n_cases - a.clean.k
        add(
            f"| {r.meta.name} | seed {r.meta.seed} ({r.meta.split}) | {r.meta.variant} | "
            f"`{r.meta.agent_model}` | {a.n_cases} of {r.meta.cases_total} | {a.n_errors} | {unclean} |"
        )
    add("")
    add(
        "A case is one scenario with its first question. An *infrastructure error* (quota, outage, "
        "crash) is not a wrong answer: it is left out of every figure and retried on a later run. "
        "A run uses the primary model only, with no fallback chain; where the saved response of a "
        "step shows a different model answered, the case is flagged above."
    )
    add("")

    add("## Headline")
    add("")
    for r in base:
        if r.meta.split == "dev":
            add(f"- `{r.meta.name}`: {DEV_NOTE}.")
    add("")
    L.extend(_headline_table(base))
    add("")
    add(
        "Each cell is successes/cases (share) and a 95% Wilson interval. With few cases the "
        "intervals are wide: 11 of 11 correct is compatible with a true rate as low as 74%."
    )
    add("")

    add("## What the metrics mean")
    add("")
    add("| metric | definition |")
    add("|---|---|")
    for name, text in METRICS:
        add(f"| {name} | {text} |")
    add("")
    add("### Which node counts as the right one")
    add("")
    L.extend(node_rules())
    add("")

    for r in base:
        add(f"## Breakdown: {r.meta.name} ({r.meta.split})")
        add("")
        if r.meta.split == "dev":
            add(f"({DEV_NOTE}.)")
            add("")
        for title, key in (
            ("By scenario kind", kind_of_case),
            ("By difficulty", difficulty_of_case),
            ("Real incidents and red herrings", class_of_case),
        ):
            add(f"**{title}**")
            add("")
            L.extend(_group_table(group_by(r.scores, key)))
            add("")
    if "accuracy_by_kind" in chart_files:
        add(f"![Root-cause accuracy by scenario kind]({chart_files['accuracy_by_kind']})")
        add("")

    add("## Confidence and calibration")
    add("")
    add(
        "A report states `low`, `medium` or `high` confidence. If the stated confidence means "
        "anything, accuracy should rise with it. Code also lowers some confidences after the fact "
        "(for example `high` needs two kinds of evidence and the look-alike checks), so the level "
        "is partly mechanical."
    )
    add("")
    add("| run | " + " | ".join(["low", "medium", "high"]) + " | high confidence and wrong |")
    add("|---|---|---|---|---|")
    for r in base:
        cal = {c.confidence: c.accuracy for c in r.overall.calibration}
        add(
            f"| {r.meta.name} | "
            + " | ".join(short_rate(cal[lv]) for lv in ("low", "medium", "high"))
            + f" | {pct_rate(r.overall.high_confidence_wrong)} |"
        )
    add("")
    add("Cells: cases with the root cause found / reports at that confidence.")
    add("")
    if "calibration" in chart_files:
        add(f"![Accuracy at each confidence level]({chart_files['calibration']})")
        add("")

    add("## Evidence, timing and tools")
    add("")
    add(
        "| run | evidence found | evidence cited | impact start error (min) | cause time error (min) | tool precision | tool recall |"
    )
    add("|---|---|---|---|---|---|---|")
    for r in base:
        a = r.overall
        add(
            f"| {r.meta.name} | {mean_ci(a.evidence_found)} | {mean_ci(a.evidence_cited)} | "
            f"{minutes(a.impact_start_error_min)} | {minutes(a.cause_time_error_min)} | "
            f"{mean_ci(a.tool_precision)} | {mean_ci(a.tool_recall)} |"
        )
    add("")
    add(
        "Evidence shares are low for scenarios whose planted evidence is dozens of alarms (an alarm "
        "storm): the agent sees a summary and a few rows by design. Means carry a bootstrap 95% interval."
    )
    add("")
    add(
        "| run | confounder outcomes | repaired reports | citation problems per report | node matches |"
    )
    add("|---|---|---|---|---|")
    for r in base:
        a = r.overall
        conf = (
            ", ".join(f"{k} {v}" for k, v in a.confounder_counts.items()) or "no confounder cases"
        )
        nodes = ", ".join(f"{k} {v}" for k, v in a.node_counts.items()) or "-"
        add(
            f"| {r.meta.name} | {conf} | {short_rate(a.repaired)} | "
            f"{mean_ci(a.citation_issues)} | {nodes} |"
        )
    add("")

    add("## Faithfulness")
    add("")
    graded = [(r, r.faithfulness_scores()) for r in base]
    if any(f for _, f in graded):
        add("| run | graded reports | mean faithfulness |")
        add("|---|---|---|")
        for r, f in graded:
            if f:
                vals = list(f.values())
                lo, hi = bootstrap_mean_ci(vals)
                add(
                    f"| {r.meta.name} | {len(vals)} of {r.overall.n_cases} | {mean(vals):.2f} [{lo:.2f} to {hi:.2f}] |"
                )
            else:
                add(f"| {r.meta.name} | 0 of {r.overall.n_cases} | not yet measured |")
        add("")
        add(
            "Faithfulness is the mean over a report's claims of supported = 1, partially supported "
            "= 0.5, unsupported = 0; claims the grader could not verify are left out. It checks "
            "that a claim follows from the evidence it cites, not that the claim is true in the world."
        )
    else:
        add("Not yet measured: no grader output exists for these runs.")
    add("")

    add("## Cost and speed")
    add("")
    add(
        "| run | model calls (p50 / p95) | tool calls (p50 / p95) | tokens (p50 / p95) | model + tool seconds (p50 / p95) | list-price cost per case (p50 / p95) |"
    )
    add("|---|---|---|---|---|---|")
    for r in base:
        a = r.overall
        cost = (
            "not established"
            if a.cost_usd is None
            else (f"{money(a.cost_usd.p50)} / {money(a.cost_usd.p95)}")
        )
        add(
            f"| {r.meta.name} | {dist_cell(a.model_calls)} | {dist_cell(a.tool_calls)} | "
            f"{dist_cell(a.total_tokens)} | {dist_cell(a.wall_seconds, 1)} | {cost} |"
        )
    add("")
    add(
        "Seconds add the original latency of each model call and the tool time; they leave out the "
        "pause the runner inserts between calls to respect free-tier rate limits, and they do not "
        "depend on whether a response came from the cache."
    )
    add("")
    priced = sorted({r.meta.agent_model for r in base if r.meta.agent_model in LIST_PRICES})
    if priced:
        for model in priced:
            p = LIST_PRICES[model]
            add(
                f"Cost uses the list price of `{model}`: ${p.usd_per_m_input:.2f} per million input "
                f"tokens and ${p.usd_per_m_output:.2f} per million output tokens (including "
                f"thinking), standard paid tier, text input; read from {p.source} on {p.read_on}. "
                "The runs themselves used the free tier and cost nothing."
            )
        total = [(r.meta.name, r.overall.cost_total_usd) for r in base]
        add("")
        add("Total at list price: " + ", ".join(f"{n} {money(c)}" for n, c in total) + ".")
    for r in base:
        if r.meta.agent_model not in LIST_PRICES:
            add(
                f"No list price is established for `{r.meta.agent_model}` (`{r.meta.name}`), so no cost is shown for it."
            )
    add("")
    if "tokens" in chart_files:
        add(f"![Tokens per investigation]({chart_files['tokens']})")
        add("")

    if ablations:
        add("## Ablations")
        add("")
        add(
            "Each variant is compared with the default agent on the cases that were scored in both "
            "runs, so the two columns describe the same cases."
        )
        add("")
        add(
            "| variant | against | common cases | root cause, lenient: default | root cause, lenient: variant | gained | lost | tool calls p50: default / variant | tokens p50: default / variant |"
        )
        add("|---|---|---|---|---|---|---|---|---|")
        for ab in ablations:
            b, v = ab["base_aggregate"], ab["variant_aggregate"]
            add(
                f"| {ab['variant']} ({ab['variant_kind']}) | {ab['base']} | {ab['n']} | "
                f"{pct_rate(b.rca_lenient)} | {pct_rate(v.rca_lenient)} | {len(ab['gained'])} | "
                f"{len(ab['lost'])} | {dist_cell(b.tool_calls, 1)} -> {dist_cell(v.tool_calls, 1)} | "
                f"{dist_cell(b.total_tokens)} -> {dist_cell(v.total_tokens)} |"
            )
        add("")
        for ab in ablations:
            if ab["gained"] or ab["lost"]:
                add(
                    f"- `{ab['variant']}`: gained {', '.join(ab['gained']) or 'none'}; "
                    f"lost {', '.join(ab['lost']) or 'none'}."
                )
        add(
            "\nA difference of one or two cases between runs is within the noise of a single run "
            "per case; nothing here was repeated to measure that noise."
        )
        add("")

    add("## Every case")
    add("")
    for r in runs:
        add(f"### {r.meta.name}")
        add("")
        L.extend(_case_table(r))
        add("")

    add("## What the agent gets wrong")
    add("")
    examples = failure_examples(order_runs(base))
    if examples:
        for run, s in examples:
            L.extend(_failure_block(run, s))
    else:
        add("No scored case was wrong in the runs included here.")
        add("")
    notes = [(r, imperfections(r)) for r in base]
    if any(n for _, n in notes):
        add("Cases counted as correct that still had something to note:")
        add("")
        for r, n in notes:
            if n:
                add(f"{r.meta.name}:")
                add("")
                L.extend(n)
                add("")

    add("## Limitations")
    add("")
    add(
        "- **The dev world is optimistic.** The prompts and checks were adjusted while looking at seed 42. Only the test world says how the agent does on something new."
    )
    add(
        "- **Small samples.** There are about 34 scenarios per world, so one case moves a rate by about 3 points and the intervals are wide. Breakdowns by kind or difficulty have only a handful of cases each."
    )
    add(
        "- **One run per case.** The model is run once per case; run-to-run variation is not measured."
    )
    add(
        "- **Synthetic data.** The network, the incidents and the runbooks come from the same simulator. Planted effects are large compared with the noise, and there are no real operator logs."
    )
    add(
        "- **Labels are conventions in places.** Where several equal nodes share a cause, the label names one; `acceptable` accepts the others, `strict` does not."
    )
    add(
        "- **Evidence shares are approximate.** Evidence is matched by row id in tool results and in cited references, and an agent can reach the right conclusion from other rows."
    )
    add(
        "- **Faithfulness is not truth.** The grader judges whether cited evidence supports a claim, not whether the claim is true."
    )
    add(
        "- **Cost is an estimate at list price** for runs that cost nothing, and is shown only where a list price was read from the provider."
    )
    add("")

    add("## Reproduce")
    add("")
    add("```")
    add("cd backend")
    add("uv run python -m incident_agent.evals prepare --seed 7")
    add("uv run python -m incident_agent.evals run --name baseline-test --seed 7")
    add("uv run python -m incident_agent.evals score --run baseline-test")
    add(
        "uv run python -m incident_agent.evals report --runs " + " ".join(r.meta.name for r in runs)
    )
    add("```")
    add("")
    return "\n".join(L)


def _partial_sentence(r: ScoredRun) -> str:
    a = r.overall
    return (
        f"`{r.meta.name}` covers {a.n_cases} of {r.meta.cases_total} cases"
        + (f" ({a.n_errors} more ended in an infrastructure error)" if a.n_errors else "")
        + "; the scenarios not yet run are not in any figure."
    )


# --- json and files ---------------------------------------------------------------------------


def build_json(runs: Sequence[ScoredRun], ablations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out_runs: list[dict[str, Any]] = []
    for r in runs:
        faith = r.faithfulness_scores()
        out_runs.append(
            {
                "run": r.meta.model_dump(
                    mode="json", exclude={"invocations", "created_at", "updated_at"}
                ),
                "partial": r.partial,
                "overall": r.overall.model_dump(mode="json"),
                "by_kind": {
                    k: v.model_dump(mode="json")
                    for k, v in group_by(r.scores, kind_of_case).items()
                },
                "by_difficulty": {
                    k: v.model_dump(mode="json")
                    for k, v in group_by(r.scores, difficulty_of_case).items()
                },
                "by_class": {
                    k: v.model_dump(mode="json")
                    for k, v in group_by(r.scores, class_of_case).items()
                },
                "faithfulness": {
                    "graded": len(faith),
                    "mean": mean(list(faith.values())) if faith else None,
                },
                "cases": [s.model_dump(mode="json") for s in r.scores],
            }
        )
    return {
        "runs": out_runs,
        "ablations": [
            {
                "variant": ab["variant"],
                "variant_kind": ab["variant_kind"],
                "base": ab["base"],
                "n": ab["n"],
                "base_rca_lenient": ab["base_aggregate"].rca_lenient.model_dump(mode="json"),
                "variant_rca_lenient": ab["variant_aggregate"].rca_lenient.model_dump(mode="json"),
                "gained": ab["gained"],
                "lost": ab["lost"],
            }
            for ab in ablations
        ],
        "list_prices": {
            k: {
                "usd_per_m_input": p.usd_per_m_input,
                "usd_per_m_output": p.usd_per_m_output,
                "source": p.source,
                "read_on": p.read_on,
            }
            for k, p in LIST_PRICES.items()
        },
    }


def write_charts(runs: Sequence[ScoredRun], out_dir: Path) -> dict[str, str]:
    base = [r for r in baselines(runs) if r.overall.n_cases]
    if not base:
        return {}
    files: dict[str, str] = {}
    by_run_kind = {r.meta.name: group_by(r.scores, kind_of_case) for r in base}
    name = f"{BASENAME}-accuracy-by-kind.png"
    charts.accuracy_by_kind(by_run_kind, out_dir / name)
    files["accuracy_by_kind"] = name
    name = f"{BASENAME}-calibration.png"
    charts.calibration({r.meta.name: r.overall for r in base}, out_dir / name)
    files["calibration"] = name
    name = f"{BASENAME}-tokens.png"
    charts.token_distribution(
        {
            r.meta.name: [float(s.total_tokens) for s in r.scores if s.status == "scored"]
            for r in base
        },
        out_dir / name,
    )
    files["tokens"] = name
    return files


def write_report(run_dirs: Sequence[RunDir], out_dir: Path) -> list[Path]:
    """Write evaluation.md, evaluation.json and the charts for the given runs."""
    runs = order_runs([load_scored_run(d) for d in run_dirs])
    if not runs:
        raise ValueError("no runs given")
    ablations = [paired(ab) for ab in find_ablations(runs)]
    chart_files = write_charts(runs, out_dir)
    md_path, json_path = out_dir / f"{BASENAME}.md", out_dir / f"{BASENAME}.json"
    write_text(md_path, render_markdown(runs, ablations, chart_files))
    write_text(json_path, dumps(build_json(runs, ablations)))
    return [md_path, json_path, *(out_dir / f for f in chart_files.values())]
