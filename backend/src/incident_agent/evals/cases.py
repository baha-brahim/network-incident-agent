"""Cases of an evaluation: one per (scenario, question), read from the planted labels.

This module and `prepare` are the only evaluation code that reads `gt.scenarios`, and they use
the owner connection. The agent never does.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Engine, text

from incident_agent.agent.tools.timeutil import as_utc, parse_time
from incident_agent.evals.scoring import Topology
from incident_agent.evals.types import EvalCase, Split, Truth

DEV_SEED = 42  # the world the prompts were developed on
# Case ids start with the world: s<seed> for the default profile, h<seed> for the hard one.
PROFILE_PREFIX = {"default": "s", "hard": "h"}
QuestionMode = Literal["first", "all"]

# Where the time an evidence row comes into view is stored: (id column, time column).
# Maintenance is always on the calendar, so it has none.
_VISIBLE_FROM: dict[str, tuple[str, str]] = {
    "alarms": ("alarm_id", "raised_at"),
    "changes": ("change_id", "executed_at"),
    "external_events": ("event_id", "start_at"),
}
_DIFFICULTY_ORDER = ("easy", "medium", "hard")


@dataclass(frozen=True)
class PlannedCase:
    case: EvalCase
    truth: Truth

    @property
    def case_id(self) -> str:
        return self.case.case_id


def split_of(seed: int, profile: str = "default") -> Split:
    """A hard world is never a development world, whatever its seed."""
    return "dev" if seed == DEV_SEED and profile == "default" else "test"


def make_case_id(seed: int, scenario_id: str, question_index: int, profile: str = "default") -> str:
    return f"{PROFILE_PREFIX[profile]}{seed}-{scenario_id}-q{question_index}"


def _visible_from(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows with a `visible_from` UTC timestamp (null when always visible)."""
    out: list[dict[str, Any]] = []
    by_table: dict[str, dict[str, str]] = {}
    for table, (id_col, time_col) in _VISIBLE_FROM.items():
        ids = sorted({str(r["id"]) for r in rows if r["table"] == table})
        if ids:
            found = conn.execute(
                text(
                    f"SELECT {id_col} AS id, {time_col} AS seen_at FROM {table} "
                    f"WHERE {id_col} = ANY(:ids)"
                ),
                {"ids": ids},
            )
            by_table[table] = {str(r.id): as_utc(r.seen_at).isoformat() for r in found}
    for row in rows:
        when = by_table.get(str(row["table"]), {}).get(str(row["id"]))
        out.append({**row, "visible_from": when})
    return out


def _truth(row: Any, conn: Any) -> Truth:
    return Truth(
        kind=row["kind"],
        is_incident=row["is_incident"],
        root_cause_category=row["root_cause_category"],
        root_cause_node_id=row["root_cause_node_id"],
        start_at=as_utc(row["start_at"]),
        impact_start_at=as_utc(row["impact_start_at"]),
        end_at=as_utc(row["end_at"]),
        affected_node_ids=list(row["affected_node_ids"]),
        affected_region_ids=list(row["affected_region_ids"]),
        severity=row["severity"],
        difficulty=row["difficulty"],
        evidence=_visible_from(conn, list(row["evidence"])),
        expected_tools=list(row["expected_tools"]),
        confounders=_visible_from(conn, list(row["confounders"])),
        notes=row["notes"] or "",
    )


def load_planned_cases(
    engine: Engine, seed: int, questions: QuestionMode = "first", profile: str = "default"
) -> list[PlannedCase]:
    """Every case of the world in scenario order. Evidence rows carry `visible_from`."""
    with engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT * FROM gt.scenarios ORDER BY scenario_id")).mappings().all()
        )
        planned: list[PlannedCase] = []
        for row in rows:
            truth = _truth(row, conn)
            qs = list(row["questions"])
            for index, q in enumerate(qs[:1] if questions == "first" else qs):
                case = EvalCase(
                    case_id=make_case_id(seed, row["scenario_id"], index, profile),
                    seed=seed,
                    split=split_of(seed, profile),
                    scenario_id=row["scenario_id"],
                    question_index=index,
                    question=str(q["text"]),
                    asked_at=parse_time(str(q["asked_at"])),
                )
                planned.append(PlannedCase(case, truth))
    return planned


def load_topology(engine: Engine) -> Topology:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT node_id, parent_id FROM nodes"))
        return Topology(parents={r.node_id: r.parent_id for r in rows})


# --- ordering and selection -------------------------------------------------------------------


def interleave[T](groups: Sequence[Sequence[T]]) -> list[T]:
    """Round robin: the first of each group, then the second of each, and so on."""
    out: list[T] = []
    for i in range(max((len(g) for g in groups), default=0)):
        out.extend(g[i] for g in groups if i < len(g))
    return out


def stratified(cases: Iterable[PlannedCase]) -> list[PlannedCase]:
    """Round robin over kinds, and inside a kind over difficulties, so that any prefix of the
    list covers as many kinds (and difficulties) as it can."""
    by_kind: dict[str, list[PlannedCase]] = {}
    for c in sorted(cases, key=lambda c: c.case_id):
        by_kind.setdefault(c.truth.kind, []).append(c)
    per_kind: list[list[PlannedCase]] = []
    for kind in sorted(by_kind):
        by_diff = {
            d: [c for c in by_kind[kind] if c.truth.difficulty == d] for d in _DIFFICULTY_ORDER
        }
        per_kind.append(interleave([g for g in by_diff.values() if g]))
    return interleave(per_kind)


def select_cases(cases: Sequence[PlannedCase], only: Sequence[str] | None) -> list[PlannedCase]:
    """Keep the cases named by scenario id (SCN-021) or case id (s42-SCN-021-q0), in order."""
    if not only:
        return list(cases)
    wanted = {o.strip() for o in only if o.strip()}
    chosen = [c for c in cases if c.case_id in wanted or c.case.scenario_id in wanted]
    known = {c.case_id for c in chosen} | {c.case.scenario_id for c in chosen}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(f"not in this world: {', '.join(unknown)}")
    return chosen


def parse_only(value: str | None) -> list[str] | None:
    return [p.strip() for p in value.split(",") if p.strip()] if value else None
