"""Faithfulness grader: does the evidence a report cites support each of its claims?

One report is turned into *items*: the stated root cause (index -1) and each finding. An item is a
claim, how the report presented it (observed or inferred) and the references it cites. Every
reference is expanded into the text a reader would need to check the claim (`evidence_text`), the
items are packed into as few requests as fit the provider's size limit (`plan_batches`), and a
judge model returns one verdict per item.

The judge sees only the claim and the cited text. It is never given the planted truth, and the
rubric tells it not to judge whether a claim is true in the world.

Evidence text of a reference:
- Call (`T3`): the tool name and arguments, then the call's output. A call that repeated an earlier
  one is shown with the earlier call's output.
- Row (`ALM-000472`, `CHG-2026-0044`, `RB-FIBER-CUT#03`, `S-TUN-012`, ...): the one-line summary
  from the evidence registry, then the line of the call output that lists the row (with its
  indented continuation lines) and the call it came from.
- A reference the registry does not know is shown as missing.

Size control is deterministic. Each reference is cut to a cap on a line boundary, with a visible
"shortened" marker. Items are packed in report order. A batch of one item that is still too large
has its caps halved (down to a floor) and then its largest references omitted, each with a marker.
Items are never dropped: the judge is told what was shortened and may answer `not_verifiable`.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from incident_agent.agent.report import Finding, Report
from incident_agent.agent.state import CallRecord, RunResult
from incident_agent.evals.types import CaseArtifact, FindingGrade, FindingVerdict, ReportGrade
from incident_agent.llm.runner import Runner, estimate_tokens
from incident_agent.llm.types import AllModelsFailed

ROOT_INDEX = -1
PROMPT_BUDGET_TOKENS = 5000  # the provider rejects a request above 8,000 (prompt + completion)
# The runner's estimate (3.5 characters per token) undercounts this text, which is full of IDs and
# numbers: measured on the grader model, real prompt tokens were 1.1 to 1.4 times the estimate.
TOKEN_UNDERCOUNT = 1.4
CALL_CAP = 2000  # characters of one call's output
ROW_CAP = 700  # characters of one row's text
CALL_FLOOR = 300
ROW_FLOOR = 160
CLAIM_CAP = 1500
LINE_CONTEXT = 3  # continuation lines kept after the line that lists a row
OMITTED = "[text omitted to fit the request]"

VERDICTS: tuple[FindingVerdict, ...] = (
    "supported",
    "partially_supported",
    "unsupported",
    "not_verifiable",
)

# The rubric. The grading page shows exactly these words to the person grading.
VERDICT_DEFINITIONS: dict[str, str] = {
    "supported": (
        "Everything the claim states (which node or ID, which number, which time, which cause) "
        "is shown by the cited evidence or follows from it. An inferred claim is supported when "
        "the cited observations make it a reasonable inference, even if no single line says it."
    ),
    "partially_supported": (
        "Part of the claim is shown by the cited evidence and part is not: a number, time, node, "
        "scope or cause goes beyond what the evidence shows, or the evidence fits the claim but "
        "the claim says more than it can show. Say which part is not backed."
    ),
    "unsupported": (
        "The cited evidence contradicts the claim, is about something else, or nothing relevant "
        "is cited. A reference to a node only (for example S-TUN-012) shows that the node exists "
        "and how it connects; it does not support a claim about alarms, changes, measurements "
        "or causes."
    ),
    "not_verifiable": (
        "The evidence needed to judge is not available: a cited reference is missing, or its "
        "text was shortened or omitted and the missing part could decide the claim. If all the "
        "evidence is there and does not back the claim, that is unsupported, not this."
    ),
}
RULES: tuple[str, ...] = (
    "Judge only against the text of the references the claim cites. A fact that appears only "
    "under another reference does not count.",
    "Use no outside knowledge. Do not judge whether the claim is true in the real world, only "
    "whether the cited evidence backs it.",
    "Check numbers, IDs and times literally. If the claim changes one (another node, another "
    "time, another count), it is not fully supported.",
    "A cited tool call (T1, T2, ...) counts only through the output printed for it. If that "
    "output does not contain the fact, the call does not support the claim.",
    "A claim that something was absent (no changes, no maintenance, no alarms) is supported by "
    "a cited call whose output reports none for the same nodes and time window.",
    "A claim marked observed must be visible in the evidence. A claim marked inferred needs "
    "cited observations that make it a reasonable inference. The stated root cause is a "
    "conclusion and is judged like an inferred claim.",
)

SYSTEM_PROMPT = (
    "You check whether the claims of an incident report are backed by the evidence the report "
    "cites for them. Each claim has a number, a basis (observed, inferred or root cause) and the "
    "references it cites. The text of every reference is printed under Evidence.\n\n"
    "Verdicts:\n"
    + "\n".join(f"- {name}: {text}" for name, text in VERDICT_DEFINITIONS.items())
    + "\n\nRules:\n"
    + "\n".join(f"{n}. {text}" for n, text in enumerate(RULES, 1))
    + "\n\nGive one entry per claim, using the claim's number: first a short reason (one "
    "sentence, at most 30 words) saying what the evidence does or does not show, then the "
    "verdict."
)


class ItemVerdict(BaseModel):
    item: int = Field(description="The claim's number")
    reason: str = Field(description="One short sentence: what the cited evidence shows or lacks")
    verdict: FindingVerdict


class VerdictBatch(BaseModel):
    verdicts: list[ItemVerdict]


# --- items and evidence ---------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    index: int  # position in report.findings; ROOT_INDEX for the stated root cause
    claim: str
    basis: Literal["observed", "inferred", "root cause"]
    refs: tuple[str, ...]

    @property
    def number(self) -> int:
        """The number the judge uses: 0 for the root cause, then 1..N for the findings."""
        return self.index + 1


@dataclass(frozen=True)
class EvidenceText:
    ref: str
    text: str
    shortened: bool = False  # cut by the grader's size control (not by the tool itself)
    found: bool = True  # False if the reference is not in the report's evidence


def root_cause_refs(report: Report) -> list[str]:
    """References backing the stated root cause: those of the matching confirmed hypothesis.

    Falls back to a hypothesis of the same category, then to every reference the findings cite.
    """

    def same_node(node: str | None) -> bool:
        return node == report.root_cause_node_id

    ranked = [
        [
            h
            for h in report.hypotheses
            if h.category == report.root_cause_category
            and h.verdict == "confirmed"
            and same_node(h.node_id)
        ],
        [
            h
            for h in report.hypotheses
            if h.category == report.root_cause_category and h.verdict == "confirmed"
        ],
        [h for h in report.hypotheses if h.category == report.root_cause_category],
    ]
    for matches in ranked:
        if matches:
            return list(dict.fromkeys(matches[0].refs))
    return list(dict.fromkeys(r for f in report.findings for r in f.refs))


def root_cause_claim(report: Report) -> str:
    where = f" at {report.root_cause_node_id}" if report.root_cause_node_id else ""
    return (
        f"{report.root_cause_summary} (Stated conclusion: {report.classification}, "
        f"{report.root_cause_category}{where}.)"
    )


def build_items(report: Report) -> list[Item]:
    items = [
        Item(ROOT_INDEX, root_cause_claim(report), "root cause", tuple(root_cause_refs(report)))
    ]
    for i, finding in enumerate(report.findings):
        items.append(_finding_item(i, finding))
    return items


def _finding_item(index: int, finding: Finding) -> Item:
    return Item(index, finding.claim, finding.basis, tuple(dict.fromkeys(finding.refs)))


def cut(text: str, cap: int) -> tuple[str, bool]:
    """Cut `text` to about `cap` characters on a line boundary; say so if anything was cut."""
    if len(text) <= cap:
        return text, False
    head = text[:cap]
    newline = head.rfind("\n")
    if newline >= cap // 2:
        head = head[:newline]
    head = head.rstrip()
    return f"{head}\n[... shortened: {len(head)} of {len(text)} characters shown]", True


def _fmt_args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in args.items() if v is not None)


def _call_header(call: CallRecord) -> str:
    return f"{call.ref} {call.tool}({_fmt_args(call.args)})"


def _call_output(call: CallRecord, by_ref: dict[str, CallRecord]) -> str:
    source = call
    if call.duplicate_of and call.duplicate_of in by_ref:
        source = by_ref[call.duplicate_of]
    parts = []
    if call.duplicate_of:
        parts.append(f"(repeat of {call.duplicate_of}; same output)")
    if source.error:
        parts.append(f"error: {source.error}")
    parts.append(source.body.strip() or source.headline)
    if source.truncated:
        parts.append("(the tool itself cut its output to fit)")
    return "\n".join(parts)


def _listing_line(ref: str, call: CallRecord) -> str | None:
    """The line of a call's output that mentions `ref`, with a few indented continuation lines."""
    pattern = re.compile(rf"(?<![\w#-]){re.escape(ref)}(?![\w#-])")
    lines = call.body.splitlines()
    for n, line in enumerate(lines):
        if pattern.search(line):
            block = [line.strip()]
            for follow in lines[n + 1 : n + 1 + LINE_CONTEXT]:
                if follow[:1].isspace() and follow.strip():
                    block.append(follow.strip())
                else:
                    break
            return "\n".join(block)
    return None


def evidence_text(ref: str, result: RunResult, *, cap: int | None = None) -> EvidenceText:
    """The text the judge (and the person grading) reads for one cited reference."""
    by_ref = {c.ref: c for c in result.calls}
    if ref in by_ref:
        text = f"{_call_header(by_ref[ref])}\n{_call_output(by_ref[ref], by_ref)}"
        text, shortened = cut(text, cap or CALL_CAP)
        return EvidenceText(ref, text, shortened)
    known = result.evidence.get(ref)
    if known is None:
        return EvidenceText(ref, "[this reference is not in the report's evidence]", found=False)
    lines = [f"{ref} ({known.kind}): {known.summary}"]
    sources = [c for c in result.calls if not c.duplicate_of and ref in c.row_refs]
    listed = False
    for call in sources:
        if line := _listing_line(ref, call):
            lines.append(f"Listed by {call.ref} ({call.tool}):\n{line}")
            listed = True
            break
    if sources and not listed:
        lines.append(f"Returned by {sources[0].ref} ({sources[0].tool}).")
    text, shortened = cut("\n".join(lines), cap or ROW_CAP)
    return EvidenceText(ref, text, shortened)


# --- packing into requests ------------------------------------------------------------------


@dataclass
class Batch:
    """One request: some items and the text of every reference they cite (each shown once)."""

    items: list[Item]
    evidence: dict[str, EvidenceText] = field(default_factory=dict)

    def messages(self) -> list[tuple[str, str]]:
        return [("system", SYSTEM_PROMPT), ("human", render_request(self))]


def _claim_text(item: Item) -> str:
    text, _ = cut(item.claim, CLAIM_CAP)
    return text


def render_request(batch: Batch) -> str:
    lines = ["Evidence", ""]
    refs = list(dict.fromkeys(r for item in batch.items for r in item.refs))
    if not refs:
        lines.append("(no references are cited by these claims)")
    for ref in refs:
        lines += [f"### {ref}", batch.evidence[ref].text, ""]
    lines += ["Claims", ""]
    for item in batch.items:
        cites = ", ".join(item.refs) if item.refs else "(nothing)"
        lines += [f"[{item.number}] ({item.basis}) {_claim_text(item)}", f"cites: {cites}", ""]
    return "\n".join(lines).rstrip() + "\n"


def estimate(batch: Batch) -> int:
    """Prompt tokens of a request, estimated on the safe side (see `TOKEN_UNDERCOUNT`)."""
    from langchain_core.messages import convert_to_messages

    raw = estimate_tokens(convert_to_messages(batch.messages()), None, VerdictBatch)
    return int(raw * TOKEN_UNDERCOUNT)


def _evidence_for(
    items: Iterable[Item], result: RunResult, call_cap: int, row_cap: int
) -> dict[str, EvidenceText]:
    by_ref = {c.ref for c in result.calls}
    out: dict[str, EvidenceText] = {}
    for item in items:
        for ref in item.refs:
            if ref not in out:
                out[ref] = evidence_text(ref, result, cap=call_cap if ref in by_ref else row_cap)
    return out


def _shrink_single(item: Item, result: RunResult, budget: int) -> Batch:
    """A batch of one item that is too large: halve the caps, then omit the largest references."""
    call_cap, row_cap = CALL_CAP, ROW_CAP
    batch = Batch([item], _evidence_for([item], result, call_cap, row_cap))
    while estimate(batch) > budget and (call_cap > CALL_FLOOR or row_cap > ROW_FLOOR):
        call_cap, row_cap = max(CALL_FLOOR, call_cap // 2), max(ROW_FLOOR, row_cap // 2)
        batch = Batch([item], _evidence_for([item], result, call_cap, row_cap))
    while estimate(batch) > budget:
        candidates = [e for e in batch.evidence.values() if e.text != OMITTED and e.found]
        if not candidates:
            break
        largest = max(candidates, key=lambda e: (len(e.text), e.ref))
        batch.evidence[largest.ref] = EvidenceText(largest.ref, OMITTED, shortened=True)
    return batch


def plan_batches(
    items: Sequence[Item], result: RunResult, *, budget: int = PROMPT_BUDGET_TOKENS
) -> list[Batch]:
    """Pack items, in order, into batches whose estimated prompt fits `budget` tokens.

    Every item lands in exactly one batch. The result depends only on the inputs.
    """
    batches: list[Batch] = []
    current: list[Item] = []
    for item in items:
        trial = Batch([*current, item], _evidence_for([*current, item], result, CALL_CAP, ROW_CAP))
        if estimate(trial) <= budget:
            current.append(item)
            continue
        if current:
            batches.append(Batch(current, _evidence_for(current, result, CALL_CAP, ROW_CAP)))
            current = []
        alone = Batch([item], _evidence_for([item], result, CALL_CAP, ROW_CAP))
        if estimate(alone) <= budget:
            current = [item]
        else:
            batches.append(_shrink_single(item, result, budget))
    if current:
        batches.append(Batch(current, _evidence_for(current, result, CALL_CAP, ROW_CAP)))
    return batches


# --- grading --------------------------------------------------------------------------------


class Faithfulness(BaseModel):
    score: float | None  # mean of supported=1, partial=0.5, unsupported=0; None if nothing scored
    n_items: int
    counts: dict[str, int]
    n_scored: int  # items that count in the mean (everything but not_verifiable)
    n_not_verifiable: int


SCORE: dict[str, float] = {"supported": 1.0, "partially_supported": 0.5, "unsupported": 0.0}


def faithfulness(grades: Iterable[FindingGrade]) -> Faithfulness:
    counts: dict[str, int] = dict.fromkeys(VERDICTS, 0)
    for g in grades:
        counts[g.verdict] += 1
    scored = sum(counts[v] for v in SCORE)
    total = sum(SCORE[v] * counts[v] for v in SCORE)
    return Faithfulness(
        score=total / scored if scored else None,
        n_items=sum(counts.values()),
        counts=counts,
        n_scored=scored,
        n_not_verifiable=counts["not_verifiable"],
    )


class GradeUsage(BaseModel):
    calls: int = 0
    cached_calls: int = 0
    input_tokens: int = 0  # all calls, as the provider reported them (cached ones: the original)
    output_tokens: int = 0
    live_tokens: int = 0  # input + output of the calls that actually reached the provider


def _usage_dict(usage: GradeUsage) -> dict[str, Any]:
    return usage.model_dump()


def _ask(runner: Runner, batch: Batch, usage: GradeUsage) -> tuple[list[ItemVerdict], str]:
    result = runner.invoke(batch.messages(), schema=VerdictBatch, purpose="grade report")
    usage.calls += 1
    usage.input_tokens += result.usage.input_tokens
    usage.output_tokens += result.usage.output_tokens
    if result.usage.cached:
        usage.cached_calls += 1
    else:
        usage.live_tokens += result.usage.input_tokens + result.usage.output_tokens
    parsed = result.parsed
    verdicts = parsed.verdicts if isinstance(parsed, VerdictBatch) else []
    return verdicts, f"{result.usage.provider}:{result.usage.model}"


def grade_report(
    artifact: CaseArtifact,
    runner: Runner,
    *,
    budget: int = PROMPT_BUDGET_TOKENS,
    reasoning: bool = False,
) -> ReportGrade:
    """Grade one report. Raises what the runner raises (quota, cache miss in replay mode)."""
    result = artifact.result
    if result is None:
        raise ValueError(f"{artifact.case.case_id} has no result to grade")
    items = build_items(result.report)
    batches = plan_batches(items, result, budget=budget)
    usage = GradeUsage()
    by_number = {item.number: item for item in items}
    got: dict[int, ItemVerdict] = {}
    model = ""
    pending = batches
    for attempt in range(2):  # the second pass asks again only for items without a verdict
        for batch in pending:
            verdicts, model = _ask(runner, batch, usage)
            for v in verdicts:
                if v.item in by_number and v.item not in got:
                    got[v.item] = v
        missing = [i for i in items if i.number not in got]
        if not missing or attempt == 1:
            break
        pending = plan_batches(missing, result, budget=budget)
    grades: list[FindingGrade] = []
    no_verdict: list[int] = []
    for item in items:
        given = got.get(item.number)
        if given is None:
            no_verdict.append(item.index)
            grades.append(
                FindingGrade(
                    index=item.index,
                    verdict="not_verifiable",
                    reason="The grader returned no verdict for this claim.",
                )
            )
        else:
            grades.append(
                FindingGrade(index=item.index, verdict=given.verdict, reason=given.reason.strip())
            )
    shortened = sorted({e.ref for b in batches for e in b.evidence.values() if e.shortened})
    return ReportGrade(
        case_id=artifact.case.case_id,
        grader=model,
        findings=grades,
        extra={
            "reasoning": reasoning,
            "batches": len(batches),
            "shortened_refs": shortened,
            "no_verdict": no_verdict,
            "usage": _usage_dict(usage),
        },
    )


def is_daily_limit(exc: AllModelsFailed) -> bool:
    """True if the provider said its daily quota is used up."""
    text = " ".join(a.error or "" for a in exc.attempts)
    return bool(re.search(r"(?i)per day|\bTPD\b|\bRPD\b|daily", text))
