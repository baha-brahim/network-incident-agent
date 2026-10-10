"""Development aid: run the agent on a planted scenario and compare it with the planted truth.

This is the only agent code that reads `gt.scenarios`, and it uses the owner connection, not the
agent's read-only one. Before a run it reads only the question text and `asked_at`; the truth is
read after the run, to print next to the agent's verdict. The agent itself never sees it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text

from incident_agent.agent.report import CLASSIFICATION_OF
from incident_agent.agent.state import RunResult
from incident_agent.agent.tools.timeutil import fmt, parse_time


def list_scenarios(engine: Engine) -> list[dict[str, Any]]:
    """Id, kind and difficulty only; used to choose what to run."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT scenario_id, kind, difficulty, "
                "jsonb_array_length(questions) AS n_questions "
                "FROM gt.scenarios ORDER BY scenario_id"
            )
        ).mappings()
        return [dict(r) for r in rows]


def load_question(engine: Engine, scenario_id: str, index: int = 0) -> tuple[str, datetime]:
    """The question text and `asked_at` of a scenario: all the agent is allowed to know."""
    with engine.connect() as conn:
        questions = conn.execute(
            text("SELECT questions FROM gt.scenarios WHERE scenario_id = :id"),
            {"id": scenario_id},
        ).scalar_one_or_none()
    if questions is None:
        raise SystemExit(f"Unknown scenario {scenario_id}.")
    if not 0 <= index < len(questions):
        raise SystemExit(f"{scenario_id} has {len(questions)} questions (0..{len(questions) - 1}).")
    q = questions[index]
    return str(q["text"]), parse_time(str(q["asked_at"]))


@dataclass
class Truth:
    scenario_id: str
    kind: str
    difficulty: str
    is_incident: bool
    category: str
    node_id: str | None
    impact_start: datetime
    end: datetime
    affected: list[str]

    @property
    def classification(self) -> str:
        return CLASSIFICATION_OF.get(self.category, "incident")


def load_truth(engine: Engine, scenario_id: str) -> Truth:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT kind, difficulty, is_incident, root_cause_category, "
                    "root_cause_node_id, impact_start_at, end_at, affected_node_ids "
                    "FROM gt.scenarios WHERE scenario_id = :id"
                ),
                {"id": scenario_id},
            )
            .mappings()
            .one()
        )
    return Truth(
        scenario_id=scenario_id,
        kind=row["kind"],
        difficulty=row["difficulty"],
        is_incident=row["is_incident"],
        category=row["root_cause_category"],
        node_id=row["root_cause_node_id"],
        impact_start=row["impact_start_at"],
        end=row["end_at"],
        affected=list(row["affected_node_ids"]),
    )


@dataclass
class Comparison:
    classification_ok: bool
    category_ok: bool
    node_ok: bool
    onset_ok: bool | None  # None if the report names no impact start

    def lines(self, truth: Truth, result: RunResult) -> list[str]:
        r = result.report
        mark = {True: "yes", False: "NO", None: "n/a"}
        return [
            f"Truth:  {truth.kind} ({truth.difficulty}) -> "
            f"{truth.classification} / {truth.category} at {truth.node_id}; "
            f"impact {fmt(truth.impact_start)} to {fmt(truth.end)}",
            f"Agent:  {r.classification} / {r.root_cause_category} at {r.root_cause_node_id}; "
            f"confidence {r.confidence}; impact {r.impact_start} to {r.impact_end}",
            f"Match:  classification {mark[self.classification_ok]}, "
            f"category {mark[self.category_ok]}, node {mark[self.node_ok]}, "
            f"onset within 45 min {mark[self.onset_ok]}",
        ]


def compare(truth: Truth, result: RunResult) -> Comparison:
    r = result.report
    onset: bool | None = None
    if r.impact_start:
        try:
            onset = abs(parse_time(r.impact_start) - truth.impact_start) <= timedelta(minutes=45)
        except ValueError:
            onset = False
    return Comparison(
        classification_ok=r.classification == truth.classification,
        category_ok=r.root_cause_category == truth.category,
        node_ok=r.root_cause_node_id == truth.node_id,
        onset_ok=onset,
    )
