"""Turn raw KPI tables into the monitored series: sites, regions and core nodes.

Everything here is pure: DataFrames in, numpy arrays out.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from incident_agent.detector.config import DetectorConfig, MetricSpec
from incident_agent.simulator.world import World

_QUALITY = ("rrc_success_pct", "drop_rate_pct", "latency_ms")  # volume-weighted means
_MEAN = ("prb_util_pct", "availability_pct")  # plain means over cells
_SUM = ("dl_volume_mb", "active_users")


@dataclass(frozen=True)
class DetectorInput:
    """The four tables the detector needs. Read from Postgres or taken from a World."""

    nodes: pd.DataFrame
    cells: pd.DataFrame
    cell_kpis: pd.DataFrame
    core_kpis: pd.DataFrame

    @classmethod
    def from_world(cls, world: World) -> "DetectorInput":
        return cls(world.nodes, world.cells, world.cell_kpis, world.core_kpis)


@dataclass(frozen=True)
class Topology:
    """Lookups derived from the `nodes` table."""

    node_type: dict[str, str]
    region_of: dict[str, str | None]
    parent: dict[str, str | None]
    agg_of_site: dict[str, str]
    link_of_site: dict[str, str]
    upf_regions: dict[str, tuple[str, ...]]  # core UPF -> regions it serves

    @classmethod
    def from_nodes(cls, nodes: pd.DataFrame) -> "Topology":
        node_type = dict(zip(nodes["node_id"], nodes["node_type"], strict=True))
        region_of = {
            n: (r if isinstance(r, str) else None)
            for n, r in zip(nodes["node_id"], nodes["region_id"], strict=True)
        }
        parent = {
            n: (p if isinstance(p, str) else None)
            for n, p in zip(nodes["node_id"], nodes["parent_id"], strict=True)
        }
        agg_of_site: dict[str, str] = {}
        link_of_site: dict[str, str] = {}
        for node, kind in node_type.items():
            if kind != "site":
                continue
            link = parent[node]
            agg = parent.get(link) if link else None
            link_of_site[node] = link or node
            agg_of_site[node] = agg or link or node
        upf: dict[str, set[str]] = {}
        for node, kind in node_type.items():
            up = parent[node]
            region = region_of[node]
            if kind == "agg_router" and up is not None and region is not None:
                upf.setdefault(up, set()).add(region)
        return cls(
            node_type,
            region_of,
            parent,
            agg_of_site,
            link_of_site,
            {u: tuple(sorted(r)) for u, r in upf.items()},
        )

    def sites_under(self, node_id: str) -> list[str]:
        """Sites that depend on `node_id` (itself, if it is a site). DNS/AMF: every site."""
        kind = self.node_type.get(node_id)
        if kind == "site":
            return [node_id]
        if kind == "transport_link":
            return sorted(s for s, link in self.link_of_site.items() if link == node_id)
        if kind == "agg_router":
            return sorted(s for s, agg in self.agg_of_site.items() if agg == node_id)
        if kind == "core_upf":
            regions = set(self.upf_regions.get(node_id, ()))
            return sorted(s for s in self.agg_of_site if self.region_of.get(s) in regions)
        if kind in ("core_dns", "core_amf"):
            return sorted(self.agg_of_site)
        return []


@dataclass(frozen=True)
class SeriesSet:
    """N monitored series over T time steps."""

    ts: pd.DatetimeIndex
    entity_type: np.ndarray  # object (N,): site | region | core_node
    entity_id: np.ndarray
    region_id: np.ndarray  # object, None for core nodes
    metric: np.ndarray
    spec: tuple[MetricSpec, ...]  # per series
    values: np.ndarray  # (N, T), NaN where unknown

    def __len__(self) -> int:
        return len(self.entity_id)


def _grid(ts: pd.Series) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """The sorted unique timestamps and each row's index into them."""
    index = pd.DatetimeIndex(np.sort(ts.unique()))
    codes = index.get_indexer(pd.DatetimeIndex(ts))
    return index, codes


def _cell_matrices(inp: DetectorInput) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray]]:
    """cell_kpis as one (cells, steps) array per metric, rows in `cells` order."""
    kpis = inp.cell_kpis
    index, t_code = _grid(kpis["ts"])
    cell_ids = pd.Index(inp.cells["cell_id"])
    c_code = cell_ids.get_indexer(pd.Index(kpis["cell_id"]))
    keep = c_code >= 0
    out: dict[str, np.ndarray] = {}
    for name in (*_SUM, *_QUALITY, *_MEAN):
        arr = np.full((len(cell_ids), len(index)), np.nan)
        arr[c_code[keep], t_code[keep]] = kpis[name].to_numpy(dtype=float)[keep]
        out[name] = arr
    return index, out


def _aggregate(group: np.ndarray, mats: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Aggregate cells into groups. `group` is a 0/1 matrix of shape (groups, cells)."""
    vol = np.nan_to_num(mats["dl_volume_mb"], nan=0.0)
    out: dict[str, np.ndarray] = {}
    for name in _SUM:
        out[name] = group @ np.nan_to_num(mats[name], nan=0.0)
    for name in _QUALITY:
        x = mats[name]
        ok = ~np.isnan(x)
        weight = np.where(ok, vol, 0.0)
        den = group @ weight
        num = group @ (np.where(ok, x, 0.0) * weight)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[name] = np.where(den > 0, num / den, np.nan)
    n_cells = np.maximum(group.sum(axis=1, keepdims=True), 1.0)
    for name in _MEAN:
        out[name] = (group @ np.nan_to_num(mats[name], nan=0.0)) / n_cells
    return out


def _membership(codes: np.ndarray, n_groups: int) -> np.ndarray:
    m = np.zeros((n_groups, len(codes)))
    valid = codes >= 0
    m[codes[valid], np.flatnonzero(valid)] = 1.0
    return m


def build_series(inp: DetectorInput, cfg: DetectorConfig) -> SeriesSet:
    """Site, region and core-node series for every monitored metric."""
    topo = Topology.from_nodes(inp.nodes)
    index, mats = _cell_matrices(inp)

    site_ids = sorted(topo.agg_of_site)
    site_of_cell = pd.Index(site_ids).get_indexer(pd.Index(inp.cells["site_id"]))
    region_ids = sorted({r for r in (topo.region_of[s] for s in site_ids) if r})
    region_of_cell = np.array(
        [
            region_ids.index(r) if (r := topo.region_of.get(s)) in region_ids else -1
            for s in inp.cells["site_id"]
        ]
    )
    levels = [
        ("site", site_ids, _aggregate(_membership(site_of_cell, len(site_ids)), mats)),
        ("region", region_ids, _aggregate(_membership(region_of_cell, len(region_ids)), mats)),
    ]

    e_type: list[str] = []
    e_id: list[str] = []
    e_region: list[str | None] = []
    e_metric: list[str] = []
    e_spec: list[MetricSpec] = []
    blocks: list[np.ndarray] = []
    for level, ids, agg in levels:
        for spec in cfg.cell_metrics:
            for ent in ids:
                e_type.append(level)
                e_id.append(ent)
                e_region.append(ent if level == "region" else topo.region_of.get(ent))
                e_metric.append(spec.name)
                e_spec.append(spec)
            blocks.append(agg[spec.name])

    core = inp.core_kpis
    if len(core):
        core_specs = {m.name: m for m in cfg.core_metrics}
        for (node, metric), part in core.groupby(["node_id", "metric"], sort=True):
            spec_c = core_specs.get(str(metric))
            if spec_c is None:
                continue
            row = np.full(len(index), np.nan)
            row[index.get_indexer(pd.DatetimeIndex(part["ts"]))] = part["value"].to_numpy(float)
            e_type.append("core_node")
            e_id.append(str(node))
            e_region.append(None)
            e_metric.append(str(metric))
            e_spec.append(spec_c)
            blocks.append(row[None, :])

    return SeriesSet(
        ts=index,
        entity_type=np.array(e_type, dtype=object),
        entity_id=np.array(e_id, dtype=object),
        region_id=np.array(e_region, dtype=object),
        metric=np.array(e_metric, dtype=object),
        spec=tuple(e_spec),
        values=np.vstack(blocks),
    )
