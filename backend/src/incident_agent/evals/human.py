"""Human grading: pick reports, build the grading page, read the exported grades.

The page shows, for each sampled report, its question, its stated conclusion and every item
(stated root cause and findings) with the exact evidence text the grader model reads, so a person
and the model judge the same material by the same rubric. Nothing in the page comes from a grader
verdict or from the planted truth: `build_pack` takes artifacts only to read the report and to pick
the sample, and the picking uses the truth only to balance correct and incorrect reports.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from incident_agent.agent.report import Report
from incident_agent.agent.state import RunResult
from incident_agent.evals.grader import (
    RULES,
    VERDICT_DEFINITIONS,
    EvidenceText,
    Item,
    build_items,
    plan_batches,
)
from incident_agent.evals.human_labels import GLOSSARY, describe_call, describe_row
from incident_agent.evals.human_template import PAGE
from incident_agent.evals.types import CaseArtifact, ReportGrade

PAGE_TITLE = "Report grading"
VERDICT_LABELS = {
    "supported": "Supported",
    "partially_supported": "Partially supported",
    "unsupported": "Unsupported",
    "not_verifiable": "Not verifiable",
}
# One-line paraphrases shown beside the grader's own wording (which is not changed).
VERDICT_PLAIN = {
    "supported": "The boxes show everything the sentence says.",
    "partially_supported": (
        "The boxes show some of it, but a number, time, node or cause goes further."
    ),
    "unsupported": (
        "The boxes contradict it, are about something else, or nothing relevant is cited."
    ),
    "not_verifiable": "Evidence is missing or cut short, so you cannot tell.",
}


def _rank(seed: int, case_id: str) -> str:
    return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()


def is_correct(artifact: CaseArtifact) -> bool:
    """Right classification and root-cause category. Used only to balance the sample."""
    assert artifact.result is not None
    report, truth = artifact.result.report, artifact.truth
    expected = "incident" if truth.is_incident else truth.root_cause_category
    return report.classification == expected and report.root_cause_category == (
        truth.root_cause_category
    )


def gradable(artifact: CaseArtifact) -> bool:
    return artifact.result is not None and artifact.error is None


def select_cases(artifacts: Sequence[CaseArtifact], n: int, seed: int = 0) -> list[CaseArtifact]:
    """Choose `n` reports: spread over kinds, with both correct and incorrect ones when present.

    Within a kind, incorrect and correct reports alternate (incorrect first, as they are rarer),
    each in a fixed pseudo-random order. Kinds are visited round-robin in name order. The chosen
    reports are returned in a fixed pseudo-random order that does not group by kind. The same
    inputs always give the same output.
    """
    by_kind: dict[str, list[CaseArtifact]] = {}
    for kind in sorted({a.truth.kind for a in artifacts if gradable(a)}):
        pool = sorted(
            (a for a in artifacts if gradable(a) and a.truth.kind == kind),
            key=lambda a: _rank(seed, a.case.case_id),
        )
        wrong = [a for a in pool if not is_correct(a)]
        right = [a for a in pool if is_correct(a)]
        mixed: list[CaseArtifact] = []
        while wrong or right:
            if wrong:
                mixed.append(wrong.pop(0))
            if right:
                mixed.append(right.pop(0))
        by_kind[kind] = mixed
    chosen: list[CaseArtifact] = []
    while len(chosen) < n and any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind] and len(chosen) < n:
                chosen.append(by_kind[kind].pop(0))
    return sorted(chosen, key=lambda a: _rank(seed, "order:" + a.case.case_id))


def _chips(report: Report) -> list[str]:
    where = f" at {report.root_cause_node_id}" if report.root_cause_node_id else ""
    return [
        f"classification: {report.classification}",
        f"root cause: {report.root_cause_category}{where}",
        f"confidence: {report.confidence}",
    ]


def _evidence_view(e: EvidenceText, result: RunResult) -> dict[str, Any]:
    """One evidence box: the grader's text plus a plain-English header built from the call."""
    view: dict[str, Any] = {
        "ref": e.ref,
        "text": e.text,
        "shortened": e.shortened,
        "found": e.found,
    }
    call = next((c for c in result.calls if c.ref == e.ref), None)
    if call is not None:
        view |= {
            "type": "call",
            "tool": call.tool,
            "args": call.args,
            "label": describe_call(call.tool, call.args),
        }
    else:
        known = result.evidence.get(e.ref)
        kind = known.kind if known is not None and e.found else None
        view |= {"type": kind or "missing", "label": describe_row(e.ref, kind)}
    return view


def _item_view(item: Item, evidence: dict[str, EvidenceText], result: RunResult) -> dict[str, Any]:
    return {
        "index": item.index,
        "basis": item.basis,
        "claim": item.claim,
        "evidence": [_evidence_view(evidence[r], result) for r in item.refs],
    }


def report_view(artifact: CaseArtifact) -> dict[str, Any]:
    """One report as the page shows it: the evidence is the text the grader model is given."""
    result: RunResult = artifact.result  # type: ignore[assignment]
    items = build_items(result.report)
    evidence: dict[int, dict[str, EvidenceText]] = {}
    for batch in plan_batches(items, result):
        for item in batch.items:
            evidence[item.index] = batch.evidence
    return {
        "case_id": artifact.case.case_id,
        "question": artifact.case.question,
        "title": result.report.title,
        "chips": _chips(result.report),
        "summary": result.report.root_cause_summary,
        "items": [_item_view(item, evidence[item.index], result) for item in items],
    }


def build_pack(artifacts: Sequence[CaseArtifact], *, title: str = PAGE_TITLE) -> dict[str, Any]:
    """The data of the page, in the order the reports will be shown."""
    reports = [report_view(a) for a in artifacts]
    digest = hashlib.sha256(json.dumps(reports, sort_keys=True).encode()).hexdigest()[:12]
    return {
        "pack_id": digest,
        "title": title,
        "rubric": {
            "verdicts": [
                {
                    "key": key,
                    "label": VERDICT_LABELS[key],
                    "definition": text,
                    "plain": VERDICT_PLAIN[key],
                }
                for key, text in VERDICT_DEFINITIONS.items()
            ],
            "rules": list(RULES),
        },
        "glossary": [
            {"term": t, "group": g, "text": d, "match": list(m)} for t, g, d, m in GLOSSARY
        ],
        "reports": reports,
    }


def _safe_json(data: dict[str, Any]) -> str:
    """JSON that is safe inside a script element: no `<`, so no `</script>` or `<!--`."""
    return (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render_page(pack: dict[str, Any]) -> str:
    return PAGE.replace("__TITLE__", _escape(pack["title"])).replace("__DATA__", _safe_json(pack))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_pack(pack: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    """Write `grading.html` and `items.json` (the same data, for reference and tests)."""
    directory.mkdir(parents=True, exist_ok=True)
    page = directory / "grading.html"
    items = directory / "items.json"
    page.write_text(render_page(pack), encoding="utf-8", newline="\n")
    items.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return page, items


_GRADES = TypeAdapter(list[ReportGrade])


def read_human_grades(path: Path) -> list[ReportGrade]:
    return _GRADES.validate_json(path.read_text(encoding="utf-8"))
