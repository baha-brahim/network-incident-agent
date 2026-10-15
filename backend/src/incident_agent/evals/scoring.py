"""Per-case scoring: pure functions from a saved case to typed scores. No database, no model.

The only outside knowledge needed is the parent of every node (`Topology`), to decide whether a
named node is the planted one, a peer the label could equally have named, or a neighbour.
"""

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_agent.agent.report import CLASSIFICATION_OF, Report, all_refs
from incident_agent.agent.state import CallRecord, RunResult
from incident_agent.agent.tools.timeutil import TimeParseError, as_utc, parse_time
from incident_agent.evals.pricing import estimate_cost
from incident_agent.evals.types import CaseArtifact, ReportGrade, Truth

NodeMatch = Literal["exact", "acceptable", "related", "wrong"]
ConfounderOutcome = Literal["dismissed", "blamed", "seen_ignored", "not_seen"]

# Kinds whose cause hits several equal nodes, so the label names one of them arbitrarily
# (the first site of a pushed group, the first of two congested sites, the first venue site).
PEER_KINDS = frozenset({"config_push", "congestion", "stadium_event"})

# From best to worst, to pick the outcome of a case with several confounders.
CONFOUNDER_ORDER: tuple[ConfounderOutcome, ...] = (
    "blamed",
    "seen_ignored",
    "not_seen",
    "dismissed",
)

CONFIDENCE_LEVELS = ("low", "medium", "high")

_TRAP_RE = re.compile(r"^trap=([a-z0-9_]+);")


def trap_of(notes: str | None) -> str | None:
    """The trap name a hard-profile scenario puts at the start of its notes, if any."""
    found = _TRAP_RE.match(notes or "")
    return found.group(1) if found else None


class Topology(BaseModel):
    """Node -> parent (None for a root). Sites hang under links, links under routers."""

    parents: dict[str, str | None]

    def ancestors(self, node: str) -> list[str]:
        out: list[str] = []
        seen = {node}
        current = self.parents.get(node)
        while current is not None and current not in seen:
            out.append(current)
            seen.add(current)
            current = self.parents.get(current)
        return out

    def related(self, a: str, b: str) -> bool:
        """One is an ancestor of the other."""
        return a in self.ancestors(b) or b in self.ancestors(a)


# --- node matching -----------------------------------------------------------------------------


def acceptable_nodes(truth: Truth) -> set[str]:
    """Peers the label could equally have named, besides the labelled node itself.

    Only for kinds that hit several equal nodes, and only when the label is itself one of the
    affected nodes: a config push to a router names the router, whose sites are its
    descendants and so "related", not peers.
    """
    root = truth.root_cause_node_id
    if truth.kind in PEER_KINDS and root is not None and root in truth.affected_node_ids:
        return set(truth.affected_node_ids) - {root}
    return set()


def classify_node(reported: str | None, truth: Truth, topology: Topology) -> NodeMatch:
    """exact, acceptable (a peer), related (ancestor or descendant) or wrong.

    A label of None (a nationwide cause) is matched only by None.
    """
    label = truth.root_cause_node_id
    node = reported.strip() if reported else None
    if label is None or node is None:
        return "exact" if label is None and node is None else "wrong"
    if node == label:
        return "exact"
    if node in acceptable_nodes(truth):
        return "acceptable"
    if topology.related(node, label):
        return "related"
    return "wrong"


# --- evidence ---------------------------------------------------------------------------------


def visible_at(row: dict[str, Any], asked_at: datetime) -> bool:
    """Could the agent have seen this evidence row? `visible_from` is when it came into being
    (alarm raised, change executed, event started); absent for maintenance, which is always
    on the calendar."""
    start = row.get("visible_from")
    if start is None:
        return True
    return as_utc(datetime.fromisoformat(str(start))) <= as_utc(asked_at)


def _seen_in_tool_results(row_id: str, calls: list[CallRecord]) -> bool:
    return any(row_id in c.row_refs or row_id in c.body for c in calls if not c.duplicate_of)


def evidence_shares(
    truth: Truth, result: RunResult, asked_at: datetime
) -> tuple[int, float | None, float | None]:
    """(visible rows, share seen in tool results, share cited by the report)."""
    ids = [str(r["id"]) for r in truth.evidence if visible_at(r, asked_at)]
    if not ids:
        return 0, None, None
    cited = {ref.strip().upper() for ref in all_refs(result.report)}
    found = sum(1 for i in ids if _seen_in_tool_results(i, result.calls))
    cited_n = sum(1 for i in ids if i.upper() in cited)
    return len(ids), found / len(ids), cited_n / len(ids)


def confounder_outcomes(
    truth: Truth, result: RunResult, asked_at: datetime
) -> list[ConfounderOutcome]:
    """For each confounder the agent could have seen: how the report treated it.

    dismissed: listed under dismissed signals. blamed: cited by a confirmed hypothesis of the
    stated category, or named in the root-cause summary. seen_ignored: it was in a tool result
    but the report neither dismissed nor blamed it. not_seen: no tool result showed it.
    """
    report = result.report
    dismissed = {d.ref.strip().upper() for d in report.dismissed_signals}
    supporting = {
        r.strip().upper()
        for h in report.hypotheses
        if h.verdict == "confirmed" and h.category == report.root_cause_category
        for r in h.refs
    }
    summary = f"{report.title} {report.root_cause_summary}".upper()
    out: list[ConfounderOutcome] = []
    for row in truth.confounders:
        if not visible_at(row, asked_at):
            continue
        cid = str(row["id"]).upper()
        if cid in supporting or cid in summary:
            out.append("blamed")
        elif cid in dismissed:
            out.append("dismissed")
        elif _seen_in_tool_results(str(row["id"]), result.calls):
            out.append("seen_ignored")
        else:
            out.append("not_seen")
    return out


def worst_outcome(outcomes: Iterable[ConfounderOutcome]) -> ConfounderOutcome | None:
    found = set(outcomes)
    return next((o for o in CONFOUNDER_ORDER if o in found), None)


# --- small helpers ----------------------------------------------------------------------------


def truth_classification(truth: Truth) -> str:
    return "incident" if truth.is_incident else CLASSIFICATION_OF.get(truth.root_cause_category, "")


def time_error_min(value: str | None, truth_time: datetime) -> float | None:
    """Absolute error in minutes, or None when the report gave no (usable) time."""
    if not value:
        return None
    try:
        return abs((parse_time(value) - as_utc(truth_time)).total_seconds()) / 60
    except TimeParseError:
        return None


def category_in_top3(report: Report, category: str) -> bool:
    ranked = [h.category for h in report.hypotheses[:3]]
    return report.root_cause_category == category or category in ranked


def tool_overlap(result: RunResult, expected: list[str]) -> tuple[float | None, float | None]:
    """Precision and recall of the tools the model chose (orient's code-driven calls excluded)."""
    called = {c.tool for c in result.calls if c.node == "investigate" and not c.duplicate_of}
    want = set(expected)
    hit = len(called & want)
    return (hit / len(called) if called else None, hit / len(want) if want else None)


def verification_counts(result: RunResult) -> tuple[int, int, bool]:
    """(problems found in the first draft, problems left after repair, a repair call was made)."""
    repaired = [i for i in result.issues if i.startswith("[repaired] ")]
    unresolved = [i for i in result.issues if i.startswith("unresolved: ")]
    made_repair = bool(repaired) or any(s.node == "repair" for s in result.steps)
    first = len(repaired) if repaired else len(unresolved)
    return first, len(unresolved), made_repair


def reconstructed_wall_seconds(result: RunResult) -> float:
    """Model latency plus tool time. Stable across replays, and without the free-tier throttle."""
    llm = sum(s.latency_ms for s in result.steps if not s.error)
    tools = sum(c.wall_ms for c in result.calls)
    return round((llm + tools) / 1000, 2)


# --- the score of a case ----------------------------------------------------------------------


class BeforeChecks(BaseModel):
    """How the report scored before the look-alike checks of the verify step changed it."""

    classification: str
    category: str
    node: str | None
    confidence: str
    rca_lenient: bool
    abstained: bool
    confident_wrong: bool


class CaseScore(BaseModel):
    case_id: str
    scenario_id: str
    kind: str
    difficulty: str
    is_incident: bool
    trap: str | None = None  # hard profile: the trap planted in the scenario
    status: Literal["scored", "error"]
    error: str | None = None

    truth_classification: str = ""
    truth_category: str = ""
    truth_node: str | None = None
    report_classification: str | None = None
    report_category: str | None = None
    report_node: str | None = None
    confidence: str | None = None

    verdict_correct: bool = False
    abstained: bool = False
    category_correct: bool = False
    category_in_top3: bool = False
    node_match: NodeMatch | None = None
    rca_strict: bool = False
    rca_lenient: bool = False
    confident_wrong: bool = False
    before_checks: BeforeChecks | None = None  # set when a look-alike check fired

    cause_time_error_min: float | None = None
    impact_start_error_min: float | None = None
    n_evidence_visible: int = 0
    evidence_found: float | None = None
    evidence_cited: float | None = None
    confounder_outcome: ConfounderOutcome | None = None
    tool_precision: float | None = None
    tool_recall: float | None = None
    citation_issues: int = 0
    unresolved_issues: int = 0
    repaired: bool = False

    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    wall_seconds: float = 0.0
    cost_usd: float | None = None
    models_used: list[str] = Field(default_factory=list)
    clean: bool = True  # no step was answered by a model other than the configured one


def score_case(artifact: CaseArtifact, topology: Topology) -> CaseScore:
    truth, case = artifact.truth, artifact.case
    base = CaseScore(
        case_id=case.case_id,
        scenario_id=case.scenario_id,
        kind=truth.kind,
        difficulty=truth.difficulty,
        is_incident=truth.is_incident,
        trap=trap_of(truth.notes),
        status="scored",
        truth_classification=truth_classification(truth),
        truth_category=truth.root_cause_category,
        truth_node=truth.root_cause_node_id,
    )
    result = artifact.result
    if artifact.error is not None or result is None:
        return base.model_copy(
            update={"status": "error", "error": artifact.error or "the run produced no result"}
        )

    report = result.report
    verdict_ok = report.classification == base.truth_classification
    category_ok = report.root_cause_category == truth.root_cause_category
    match = classify_node(report.root_cause_node_id, truth, topology)
    strict = verdict_ok and category_ok and match == "exact"
    lenient = verdict_ok and category_ok and match in ("exact", "acceptable")
    n_visible, found, cited = evidence_shares(truth, result, case.asked_at)
    precision, recall = tool_overlap(result, truth.expected_tools)
    first, unresolved, repaired = verification_counts(result)
    before = result.report_before_checks
    usage = result.usage
    models = list(result.models_used)
    clean = not result.fell_back and all(m == artifact.agent_model for m in models)
    return base.model_copy(
        update={
            "report_classification": report.classification,
            "report_category": report.root_cause_category,
            "report_node": report.root_cause_node_id,
            "confidence": report.confidence,
            "verdict_correct": verdict_ok,
            "abstained": report.classification == "inconclusive",
            "category_correct": category_ok,
            "category_in_top3": category_in_top3(report, truth.root_cause_category),
            "node_match": match,
            "rca_strict": strict,
            "rca_lenient": lenient,
            "confident_wrong": report.confidence == "high" and not lenient,
            "before_checks": _before_checks(before, base, truth, topology) if before else None,
            "cause_time_error_min": time_error_min(report.root_cause_time, truth.start_at),
            "impact_start_error_min": time_error_min(report.impact_start, truth.impact_start_at),
            "n_evidence_visible": n_visible,
            "evidence_found": found,
            "evidence_cited": cited,
            "confounder_outcome": worst_outcome(confounder_outcomes(truth, result, case.asked_at)),
            "tool_precision": precision,
            "tool_recall": recall,
            "citation_issues": first,
            "unresolved_issues": unresolved,
            "repaired": repaired,
            "model_calls": usage.llm_calls,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "wall_seconds": reconstructed_wall_seconds(result),
            "cost_usd": estimate_cost(
                artifact.agent_model, usage.input_tokens, usage.output_tokens
            ),
            "models_used": models,
            "clean": clean,
        }
    )


def _before_checks(
    report: Report, base: CaseScore, truth: Truth, topology: Topology
) -> BeforeChecks:
    match = classify_node(report.root_cause_node_id, truth, topology)
    lenient = (
        report.classification == base.truth_classification
        and report.root_cause_category == truth.root_cause_category
        and match in ("exact", "acceptable")
    )
    return BeforeChecks(
        classification=report.classification,
        category=report.root_cause_category,
        node=report.root_cause_node_id,
        confidence=report.confidence,
        rca_lenient=lenient,
        abstained=report.classification == "inconclusive",
        confident_wrong=report.confidence == "high" and not lenient,
    )


def dump_score(score: CaseScore) -> dict[str, Any]:
    """JSON form of a score. `trap` and `before_checks` are left out when empty, so files of
    runs without them keep their layout."""
    out = score.model_dump(mode="json")
    for key in ("trap", "before_checks"):
        if out.get(key) is None:
            out.pop(key, None)
    return out


# --- faithfulness (from a grade file, when the grading part has produced one) -----------------

_FAITHFULNESS_WEIGHT = {"supported": 1.0, "partially_supported": 0.5, "unsupported": 0.0}


def faithfulness(grade: ReportGrade) -> float | None:
    """Mean over graded items of supported 1, partially supported 0.5, unsupported 0.

    `not_verifiable` items are left out; None when no item is left.
    """
    weights = [
        _FAITHFULNESS_WEIGHT[f.verdict] for f in grade.findings if f.verdict in _FAITHFULNESS_WEIGHT
    ]
    return sum(weights) / len(weights) if weights else None
