"""The neighbourhood of one node, for a small diagram."""

from sqlalchemy import Engine

from incident_agent.agent.tools.common import Node, NodeIndex
from incident_agent.api.errors import ApiError
from incident_agent.api.jsonsafe import to_jsonable
from incident_agent.api.schemas import Topology, TopoNode

MAX_LISTED = 12


def _node(node: Node) -> TopoNode:
    return TopoNode(
        id=node.node_id,
        type=node.node_type,
        name=node.name,
        region_id=node.region_id,
        parent_id=node.parent_id,
        attrs=to_jsonable(node.attrs),
    )


def node_neighbourhood(engine: Engine, node_id: str) -> Topology:
    with engine.connect() as conn:
        idx = NodeIndex.load(conn)

    raw, note = node_id.strip(), None
    if raw.upper() in idx.cells:
        site = idx.cells[raw.upper()]
        note, raw = f"{raw} is a cell of {site}; showing {site}.", site
    key = raw if raw in idx.nodes else raw.upper()
    if key in idx.regions:
        raise ApiError(404, "not_a_node", f"{key} is a region, not a node.")
    if key not in idx.nodes:
        raise ApiError(404, "unknown_node", f"Unknown node_id {node_id!r}.{idx.suggest(node_id)}")

    node = idx.nodes[key]
    ancestors = idx.ancestors(key)
    children = idx.children.get(key, [])
    siblings = idx.siblings(key)
    sites_below = [d for d in idx.descendants(key) if idx.nodes[d].node_type == "site"]
    shared = (
        []
        if node.node_type.startswith("core_")
        else sorted(n for n, v in idx.nodes.items() if v.node_type in ("core_dns", "core_amf"))
    )
    return Topology(
        node=_node(node),
        chain=[_node(idx.nodes[n]) for n in [key, *ancestors]],
        shared_core=[_node(idx.nodes[n]) for n in shared],
        siblings=[_node(idx.nodes[n]) for n in siblings[:MAX_LISTED]],
        n_siblings=len(siblings),
        children=[_node(idx.nodes[n]) for n in children[:MAX_LISTED]],
        n_children=len(children),
        n_sites_below=len(sites_below),
        note=note,
    )
