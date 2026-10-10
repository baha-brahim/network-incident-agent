"""Facts about the network the prompts need (regions, id formats) and the checks use (node ids)."""

import re
from dataclasses import dataclass, field

from sqlalchemy import Engine, text


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

    @classmethod
    def load(cls, engine: Engine) -> "Reference":
        with engine.connect() as conn:
            regions = {r.region_id: r.name for r in conn.execute(text("SELECT * FROM regions"))}
            nodes = conn.execute(
                text("SELECT node_id, node_type, region_id FROM nodes ORDER BY node_id")
            ).all()
            cells = [r.cell_id for r in conn.execute(text("SELECT cell_id FROM cells LIMIT 5000"))]
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
        )

    def known(self, node_id: str) -> bool:
        return node_id in self.node_ids or node_id in self.cell_ids or node_id in self.regions

    def canonical(self, raw: str) -> str | None:
        """The id as stored (case-insensitive, trimmed), or None if it does not exist."""
        key = re.sub(r"[\s`'\"\[\]]", "", raw).upper()
        return key if self.known(key) else None
