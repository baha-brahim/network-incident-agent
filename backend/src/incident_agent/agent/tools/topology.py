"""get_topology: where a node sits in the dependency tree and what depends on it."""

from typing import Any, Literal

from pydantic import Field

from incident_agent.agent.tools.common import (
    Node,
    NodeIndex,
    error_result,
    join_ids,
)
from incident_agent.agent.tools.schema import ToolArgs
from incident_agent.agent.types import EvidenceRef, ToolContext, ToolResult

MAX_LISTED = 10


class GetTopologyArgs(ToolArgs):
    node_id: str = Field(description="A site, link, aggregation router or core node id.")
    include: Literal["ancestors", "descendants", "siblings", "all"] = Field(
        default="all", description="Which relatives to list."
    )


def _kind(node: Node) -> str:
    if node.node_type == "transport_link":
        return f"{node.attrs.get('medium', '?')} link"
    return node.node_type.replace("_", " ")


def _facts(node: Node) -> str:
    a = node.attrs
    parts: list[str] = [_kind(node)]
    if node.region_id:
        parts.append(node.region_id)
    if node.node_type == "site":
        for key in ("locality", "area_type"):
            if a.get(key):
                parts.append(str(a[key]))
        if a.get("near_venue"):
            parts.append("near a venue")
    elif node.node_type == "transport_link":
        if a.get("length_km"):
            parts.append(f"{a['length_km']} km")
        if a.get("capacity_gbps"):
            parts.append(f"{a['capacity_gbps']} Gbps")
    elif a.get("note"):
        parts.append(str(a["note"]).rstrip("."))
    elif a.get("serves_regions"):
        parts.append("serves " + "/".join(a["serves_regions"]))
    return ", ".join(parts)


def get_topology(ctx: ToolContext, args: GetTopologyArgs) -> ToolResult:
    with ctx.engine.connect() as conn:
        idx = NodeIndex.load(conn)

    raw = args.node_id.strip()
    notes: list[str] = []
    if raw.upper() in idx.cells:
        site = idx.cells[raw.upper()]
        notes.append(f"{raw} is a cell of {site}; showing {site}.")
        raw = site
    node_id = raw if raw in idx.nodes else raw.upper()
    if node_id in idx.regions:
        return _region(args, idx, node_id)
    if node_id not in idx.nodes:
        return error_result(
            "get_topology", args, f"Unknown node_id {args.node_id!r}.{idx.suggest(args.node_id)}"
        )
    node = idx.nodes[node_id]
    want = args.include
    refs: list[EvidenceRef] = []
    data: dict[str, Any] = {"node_id": node_id, "node_type": node.node_type}
    lines: list[str] = []

    ancestors = idx.ancestors(node_id)
    chain = [node_id, *ancestors]
    if want in ("ancestors", "all"):
        parts = [f"{n} ({_kind(idx.nodes[n])})" for n in chain]
        lines.append("Depends on (child -> parent -> core): " + " -> ".join(parts))
        data["ancestors"] = ancestors
        shared = sorted(
            n.node_id for n in idx.nodes.values() if n.node_type in ("core_dns", "core_amf")
        )
        if shared and not node.node_type.startswith("core_"):
            lines.append(
                "Also depends on shared core services (not in the parent chain): "
                f"{', '.join(shared)}."
            )
    lines.append(f"{node_id}: {_facts(node)}.")

    if node.node_type == "site":
        site_cells = sorted(c for c, s in idx.cells.items() if s == node_id)
        if site_cells:
            lines.append(f"Cells: {join_ids(site_cells)}.")
            data["cells"] = site_cells

    descendants = idx.descendants(node_id)
    sites_below = [d for d in descendants if idx.nodes[d].node_type == "site"]
    if want in ("descendants", "all") and descendants:
        direct = idx.children.get(node_id, [])
        kinds = {idx.nodes[c].node_type for c in direct}
        label = "Sites below" if kinds == {"site"} else "Children"
        lines.append(f"{label}: {join_ids(direct, MAX_LISTED)}.")
        if kinds != {"site"}:
            lines.append(f"{len(sites_below)} sites in total depend on {node_id}.")
        else:
            lines.append(f"A failure of {node_id} takes down all {len(direct)} of them together.")
        data["children"] = direct
        data["sites_below"] = len(sites_below)
    elif want in ("descendants", "all") and node.node_type != "site":
        lines.append("No nodes below in the dependency tree.")

    siblings = idx.siblings(node_id)
    if want in ("siblings", "all") and node.parent_id:
        if siblings:
            lines.append(f"Siblings under {node.parent_id}: {join_ids(siblings, MAX_LISTED)}.")
        else:
            lines.append(f"No siblings: {node_id} is the only child of {node.parent_id}.")
        data["siblings"] = siblings

    if node.node_type.startswith("core_") and not node.parent_id and not descendants:
        lines.append("Core node outside the site tree: its health affects traffic across regions.")

    # Evidence: the node itself, its chain, and the relatives that were listed.
    refs.append(
        EvidenceRef(
            ref=node_id,
            kind="node",
            summary=f"{_facts(node)}; chain: {' -> '.join(chain)}"
            + (f"; {len(sites_below)} sites below" if sites_below else ""),
        )
    )
    if want in ("ancestors", "all"):
        refs += [EvidenceRef(ref=a, kind="node", summary=_facts(idx.nodes[a])) for a in ancestors]
    if want in ("siblings", "all"):
        refs += [
            EvidenceRef(ref=s, kind="node", summary=f"{_facts(idx.nodes[s])}; sibling of {node_id}")
            for s in siblings[:MAX_LISTED]
        ]
    if want in ("descendants", "all"):
        refs += [
            EvidenceRef(ref=d, kind="node", summary=f"{_facts(idx.nodes[d])}; under {node_id}")
            for d in idx.children.get(node_id, [])[:MAX_LISTED]
        ]

    body = "\n".join([*notes, *lines])
    return ToolResult(
        tool="get_topology",
        args=args.model_dump(),
        headline=lines[0][:200] if lines else node_id,
        body=body,
        refs=refs,
        data=data,
        truncated=False,
    )


def _region(args: GetTopologyArgs, idx: NodeIndex, region_id: str) -> ToolResult:
    members = sorted(idx.in_region(region_id))
    aggs = [m for m in members if idx.nodes[m].node_type == "agg_router"]
    links = [m for m in members if idx.nodes[m].node_type == "transport_link"]
    sites = [m for m in members if idx.nodes[m].node_type == "site"]
    body = (
        f"{region_id} is a region ({idx.regions[region_id]}), not a node. "
        f"Aggregation routers: {join_ids(aggs)}. {len(links)} links, {len(sites)} sites. "
        "Call get_topology on one of these nodes."
    )
    return ToolResult(
        tool="get_topology",
        args=args.model_dump(),
        headline=f"{region_id}: region with {len(sites)} sites",
        body=body,
        data={"region_id": region_id, "aggs": aggs},
    )
