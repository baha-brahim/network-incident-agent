"""Recover the core of a report from an answer that is not valid JSON (cut off, or malformed).

The model writes the fields in schema order, so the verdict (classification, category, node,
summary) comes before the long lists that run out of room. The recovered report is marked partial
and its confidence is forced to low.
"""

import json
import re
from typing import get_args

from incident_agent.agent.report import (
    CLASSIFICATION_OF,
    PARTIAL_PREFIX,
    Category,
    Finding,
    Report,
)

_STRING = r'"((?:[^"\\]|\\.)*)"'
NOTE = (
    f"{PARTIAL_PREFIX} the model's answer could not be parsed; only the fields before the break "
    "were recovered, confidence is forced to low."
)


def _value(raw: str, key: str) -> str | None:
    """The text of a `"key": "text"` pair; None when the key is missing, null or cut off."""
    match = re.search(rf'"{key}"\s*:\s*{_STRING}', raw)
    if match is None:
        return None
    try:
        return str(json.loads(f'"{match.group(1)}"'))
    except json.JSONDecodeError:
        return match.group(1)


def _id_list(raw: str, key: str) -> list[str]:
    match = re.search(rf'"{key}"\s*:\s*\[([^\]]*)\]', raw)
    if match is None:
        return []
    try:
        items = json.loads(f"[{match.group(1)}]")
    except json.JSONDecodeError:
        return []
    return [i for i in items if isinstance(i, str)]


def salvage_report(raw: str, findings: list[Finding]) -> Report | None:
    """A low-confidence report built from what can be read in `raw`, or None if the category
    (and with it the classification) is not recoverable."""
    category = _value(raw, "root_cause_category")
    if category not in get_args(Category):
        classification = _value(raw, "classification")
        category = {
            "planned_maintenance": "planned_maintenance",
            "expected_event": "expected_event",
            "no_impact": "no_impact",
            "inconclusive": "unknown",
        }.get(classification or "")
    if category is None:
        return None
    return Report(
        title=_value(raw, "title") or "Partial report",
        classification=CLASSIFICATION_OF[category],
        root_cause_category=category,
        root_cause_node_id=_value(raw, "root_cause_node_id"),
        root_cause_summary=_value(raw, "root_cause_summary") or "The summary was not recovered.",
        confidence="low",
        confidence_reason="Partial report: the model's answer was cut off or malformed.",
        impact_summary=_value(raw, "impact_summary") or "Not recovered from the partial answer.",
        impact_start=_value(raw, "impact_start"),
        impact_end=_value(raw, "impact_end"),
        root_cause_time=_value(raw, "root_cause_time"),
        affected_node_ids=_id_list(raw, "affected_node_ids"),
        timeline=[],
        findings=findings,
        hypotheses=[],
        dismissed_signals=[],
        recommended_actions=["Re-run the investigation to get the full report."],
    )
