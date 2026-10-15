"""Facts about the network the prompts need (regions, id formats) and the checks use (node ids)."""

import json
import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, text


def _attrs(value: Any) -> dict[str, Any]:
    """Node attributes arrive as a dict or as a JSON string, depending on the driver."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def id_pattern(node_id: str, region_ids: set[str]) -> str:
    """'S-TUN-012' -> 'S-<REGION>-nnn'; 'LNK-TUN-02-C' -> 'LNK-<REGION>-nn-<letter>'."""
    parts = []
    for position, part in enumerate(node_id.split("-")):
        if part in region_ids:
            parts.append("<REGION>")
        elif part.isdigit():
            parts.append("n" * len(part))
        elif position > 0 and len(part) == 1 and part.isalpha():
            parts.append("<letter>")
        else:
            parts.append(part)
    return "-".join(parts)


@dataclass
class Reference:
    regions: dict[str, str] = field(default_factory=dict)  # region_id -> name
    node_ids: set[str] = field(default_factory=set)
    cell_ids: set[str] = field(default_factory=set)
    id_formats: list[str] = field(default_factory=list)  # one pattern per kind of regional node
    core_nodes: list[str] = field(default_factory=list)
    parent_of: dict[str, str] = field(default_factory=dict)  # node or cell -> its parent
    node_type: dict[str, str] = field(default_factory=dict)  # node -> site, transport_link, ...
    region_of: dict[str, str | None] = field(default_factory=dict)  # node -> region (None: core)
    venue_sites: set[str] = field(default_factory=set)  # sites near an event venue

    @classmethod
    def load(cls, engine: Engine) -> "Reference":
        with engine.connect() as conn:
            regions = {r.region_id: r.name for r in conn.execute(text("SELECT * FROM regions"))}
            nodes = conn.execute(
                text(
                    "SELECT node_id, node_type, region_id, parent_id, attrs "
                    "FROM nodes ORDER BY node_id"
                )
            ).all()
            cell_rows = conn.execute(
                text("SELECT cell_id, site_id FROM cells ORDER BY cell_id LIMIT 5000")
            ).all()
        cells = [r.cell_id for r in cell_rows]
        formats: dict[str, str] = {}
        core: list[str] = []
        for n in nodes:
            if n.region_id is None:
                core.append(n.node_id)
            else:
                formats.setdefault(n.node_type, id_pattern(n.node_id, set(regions)))
        if cells:
            formats["cell"] = id_pattern(cells[0], set(regions))
        return cls(
            regions=regions,
            node_ids={n.node_id for n in nodes},
            cell_ids=set(cells),
            id_formats=[f"{kind} {pattern}" for kind, pattern in formats.items()],
            core_nodes=core,
            parent_of={
                **{n.node_id: n.parent_id for n in nodes if n.parent_id},
                **{r.cell_id: r.site_id for r in cell_rows if r.site_id},
            },
            node_type={n.node_id: n.node_type for n in nodes},
            region_of={n.node_id: n.region_id for n in nodes},
            venue_sites={
                n.node_id
                for n in nodes
                if n.node_type == "site" and _attrs(n.attrs).get("near_venue")
            },
        )

    def known(self, node_id: str) -> bool:
        return node_id in self.node_ids or node_id in self.cell_ids or node_id in self.regions

    def ancestors(self, node_id: str) -> list[str]:
        """Parent first, core last; empty when the topology is not loaded."""
        out: list[str] = []
        current = self.parent_of.get(node_id)
        while current and current not in out:
            out.append(current)
            current = self.parent_of.get(current)
        return out

    def descendants(self, node_id: str) -> list[str]:
        """Everything below `node_id`, nearest first; empty when the topology is not loaded."""
        children: dict[str, list[str]] = {}
        for child, parent in self.parent_of.items():
            children.setdefault(parent, []).append(child)
        out: list[str] = []
        queue = deque(sorted(children.get(node_id, [])))
        while queue:
            current = queue.popleft()
            if current in out:
                continue
            out.append(current)
            queue.extend(sorted(children.get(current, [])))
        return out

    def lowest_common_ancestor(self, node_ids: Sequence[str]) -> str | None:
        """The nearest node that is an ancestor of every given node; None if there is none."""
        unique = list(dict.fromkeys(node_ids))
        if len(unique) < 2:
            return None
        chains = [self.ancestors(n) for n in unique]
        shared = set(chains[0]).intersection(*chains[1:])
        return next((a for a in chains[0] if a in shared), None)

    def canonical(self, raw: str) -> str | None:
        """The id as stored (case-insensitive, trimmed), or None if it does not exist."""
        key = re.sub(r"[\s`'\"\[\]]", "", raw).upper()
        return key if self.known(key) else None
