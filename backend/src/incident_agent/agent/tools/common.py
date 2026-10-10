"""Helpers shared by the tools: the body budget, node scoping, number formatting, errors."""

import difflib
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection, text

from incident_agent.agent.types import EvidenceRef, ToolResult

BODY_CHARS = 2000  # ~500 tokens at 4 characters per token
_SAFETY = 40  # room for rounding
MAX_ROWS_CONSIDERED = 300  # rows beyond this are summarised without being laid out


def estimate_tokens(body: str) -> int:
    return (len(body) + 3) // 4


def error_result(tool: str, args: BaseModel | dict[str, Any], message: str) -> ToolResult:
    """A ToolResult carrying a helpful error instead of raising."""
    dumped = args.model_dump() if isinstance(args, BaseModel) else args
    message = message[:600]
    return ToolResult(
        tool=tool,
        args=dumped,
        headline=f"{tool} error: {message[:140]}",
        body=message,
        error=message,
    )


def trim(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: max(limit - 3, 1)].rstrip() + "..."


def num(value: float | None) -> str:
    """Compact number: enough digits to compare values, few enough to save tokens."""
    if value is None or value != value:
        return "-"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def pct(value: float) -> str:
    return f"{value:+.0f}%"


def join_ids(ids: list[str], limit: int = 6) -> str:
    shown = ", ".join(ids[:limit])
    return shown if len(ids) <= limit else f"{shown} +{len(ids) - limit} more"


# --- body assembly ---------------------------------------------------------------------------


@dataclass
class Item:
    """One row of a tool's answer: its text, a chronological sort key, and its evidence."""

    line: str
    sort: Any
    ref: EvidenceRef | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Assembled:
    body: str
    shown: list[Item]
    omitted: list[Item]

    @property
    def truncated(self) -> bool:
        return bool(self.omitted)

    @property
    def refs(self) -> list[EvidenceRef]:
        return [i.ref for i in self.shown if i.ref is not None]


def hard_cap(body: str, limit: int = BODY_CHARS) -> str:
    return body if len(body) <= limit else body[: limit - 4].rstrip() + " ..."


def assemble(
    head: list[str],
    items: list[Item],
    *,
    omitted_line: Callable[[list[Item]], str] | None = None,
    tail: list[str] | None = None,
    budget: int = BODY_CHARS - _SAFETY,
) -> Assembled:
    """Fit as many items as the budget allows.

    `items` come in priority order (most important first). The chosen ones are shown in
    chronological order (by `sort`); one line summarises what was left out.
    """
    fixed = sum(len(line) + 1 for line in [*head, *(tail or [])])
    count = len(items)
    while count > 0:
        left = items[count:]
        extra = len(omitted_line(left)) + 1 if left and omitted_line else 0
        total = fixed + sum(len(i.line) + 1 for i in items[:count]) + extra
        if total <= budget:
            break
        count -= 1
    shown = sorted(items[:count], key=lambda i: i.sort)
    left = items[count:]
    lines = [*head, *(i.line for i in shown)]
    if left and omitted_line:
        lines.append(omitted_line(left))
    lines += tail or []
    return Assembled(hard_cap("\n".join(lines)), shown, left)


def count_by(items: list[Item], key: str, limit: int = 6) -> str:
    """'TEMP_HIGH x8, VSWR_HIGH x3' from the `key` field of each item's data."""
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.data.get(key, "?"))
        counts[value] = counts.get(value, 0) + int(item.data.get("count", 1))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{k} x{v}" for k, v in ranked[:limit])


# --- topology --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    node_id: str
    node_type: str
    name: str
    region_id: str | None
    parent_id: str | None
    attrs: dict[str, Any]


def _attrs(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class NodeIndex:
    """The whole (small) topology in memory: parents, children, regions, cells."""

    def __init__(self, nodes: list[Node], regions: dict[str, str], cells: dict[str, str]) -> None:
        self.nodes = {n.node_id: n for n in nodes}
        self.regions = regions  # region_id -> name
        self.cells = cells  # cell_id -> site_id
        self.children: dict[str, list[str]] = {}
        for n in nodes:
            if n.parent_id:
                self.children.setdefault(n.parent_id, []).append(n.node_id)
        for kids in self.children.values():
            kids.sort()

    @classmethod
    def load(cls, conn: Connection) -> "NodeIndex":
        node_rows = conn.execute(
            text("SELECT node_id, node_type, name, region_id, parent_id, attrs FROM nodes")
        )
        nodes = [
            Node(r.node_id, r.node_type, r.name, r.region_id, r.parent_id, _attrs(r.attrs))
            for r in node_rows
        ]
        region_rows = conn.execute(text("SELECT region_id, name FROM regions"))
        cell_rows = conn.execute(text("SELECT cell_id, site_id FROM cells"))
        return cls(
            nodes,
            {r.region_id: r.name for r in region_rows},
            {r.cell_id: r.site_id for r in cell_rows},
        )

    def ancestors(self, node_id: str) -> list[str]:
        """Parent first, core node last."""
        out: list[str] = []
        current = self.nodes[node_id].parent_id
        while current and current in self.nodes and current not in out:
            out.append(current)
            current = self.nodes[current].parent_id
        return out

    def descendants(self, node_id: str) -> list[str]:
        out: list[str] = []
        queue = deque(self.children.get(node_id, []))
        while queue:
            current = queue.popleft()
            out.append(current)
            queue.extend(self.children.get(current, []))
        return out

    def siblings(self, node_id: str) -> list[str]:
        parent = self.nodes[node_id].parent_id
        if not parent:
            return []
        return [c for c in self.children.get(parent, []) if c != node_id]

    def in_region(self, region_id: str) -> set[str]:
        return {n.node_id for n in self.nodes.values() if n.region_id == region_id}

    def core_nodes(self) -> set[str]:
        return {n.node_id for n in self.nodes.values() if n.region_id is None}

    def suggest(self, bad: str) -> str:
        pool = [*self.nodes, *self.cells, *self.regions]
        close = difflib.get_close_matches(bad.strip().upper(), pool, n=3, cutoff=0.6)
        return f" Did you mean {', '.join(close)}?" if close else ""


@dataclass
class Scope:
    """The nodes a query covers, and how each one relates to what was asked about."""

    ids: set[str] | None  # None = no restriction
    relation: dict[str, str] = field(default_factory=dict)  # node -> "ancestor of X" / "below X"
    direct: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def label(self, node_id: str) -> str:
        return self.relation.get(node_id, "")


def resolve_scope(
    idx: NodeIndex,
    node_ids: list[str] | None,
    region_id: str | None,
    *,
    descendants: bool = False,
    ancestors: bool = False,
    include_core: bool = True,
) -> Scope:
    """Turn `node_ids` / `region_id` arguments into the set of node ids to filter on."""
    scope = Scope(ids=None)
    if region_id is not None:
        region_id = region_id.strip().upper()
        if region_id not in idx.regions:
            scope.error = (
                f"Unknown region_id {region_id!r}. Regions: {', '.join(sorted(idx.regions))}."
            )
            return scope
    if node_ids:
        unknown: list[str] = []
        for raw in node_ids:
            node_id = raw.strip()
            if node_id.upper() in idx.cells:  # a cell id stands for its site
                node_id = idx.cells[node_id.upper()]
                scope.notes.append(f"{raw} is a cell; using its site {node_id}.")
            if node_id not in idx.nodes:
                node_id = node_id.upper()
            if node_id not in idx.nodes:
                unknown.append(raw + idx.suggest(raw).rstrip("."))
                continue
            if node_id not in scope.direct:
                scope.direct.append(node_id)
        if unknown:
            scope.notes.append(f"Unknown node ids ignored: {'; '.join(unknown)}.")
        if not scope.direct:
            scope.error = "None of the node_ids exist. " + " ".join(scope.notes)
            return scope
        ids = set(scope.direct)
        for node_id in scope.direct:
            if descendants:
                for d in idx.descendants(node_id):
                    if d not in ids:
                        ids.add(d)
                        scope.relation[d] = f"below {node_id}"
            if ancestors:
                for a in idx.ancestors(node_id):
                    if a not in ids:
                        ids.add(a)
                        scope.relation[a] = f"ancestor of {node_id}"
        if region_id is not None:
            allowed = idx.in_region(region_id) | idx.core_nodes()
            outside = [n for n in scope.direct if n not in allowed]
            if outside:
                scope.notes.append(f"{join_ids(outside)} is not in region {region_id}.")
            ids &= allowed
        scope.ids = ids
    elif region_id is not None:
        ids = idx.in_region(region_id)
        if include_core:
            ids |= idx.core_nodes()
        scope.ids = ids
        scope.notes.append(
            f"Scope: region {region_id}" + (" plus core nodes." if include_core else ".")
        )
    return scope
