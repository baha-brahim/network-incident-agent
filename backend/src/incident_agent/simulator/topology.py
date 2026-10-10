"""Topology: core -> aggregation -> transport links -> sites -> cells."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from incident_agent.simulator.config import RegionSpec, SimConfig
from incident_agent.simulator.frames import rows_to_frame

DNS_ID = "CORE-DNS-01"
AMF_ID = "CORE-AMF-01"
AREA_TYPES = ("urban", "suburban", "rural")


@dataclass(frozen=True)
class SiteInfo:
    site_id: str
    region_id: str
    link_id: str
    agg_id: str
    upf_id: str
    area_type: str
    near_venue: bool
    lat: float
    lon: float


@dataclass(frozen=True)
class Topology:
    nodes: pd.DataFrame
    cells: pd.DataFrame
    regions: pd.DataFrame
    sites: dict[str, SiteInfo]
    link_sites: dict[str, list[str]]
    agg_links: dict[str, list[str]]
    link_medium: dict[str, str]
    link_region: dict[str, str]
    agg_region: dict[str, str]
    region_sites: dict[str, list[str]]
    site_cell_rows: dict[str, list[int]]
    upf_regions: dict[str, list[str]]

    @property
    def cell_ids(self) -> list[str]:
        return self.cells["cell_id"].tolist()

    def cell_rows(self, site_ids: list[str]) -> list[int]:
        return [r for s in site_ids for r in self.site_cell_rows[s]]


def _node(
    node_id: str,
    node_type: str,
    name: str,
    region_id: str | None,
    parent_id: str | None,
    attrs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "name": name,
        "region_id": region_id,
        "parent_id": parent_id,
        "attrs": attrs,
    }


def _area_types(rng: np.random.Generator, spec: RegionSpec) -> list[str]:
    n_urban = round(spec.urban_frac * spec.n_sites)
    n_sub = round(spec.suburban_frac * spec.n_sites)
    n_rural = max(0, spec.n_sites - n_urban - n_sub)
    types = ["urban"] * n_urban + ["suburban"] * n_sub + ["rural"] * n_rural
    types = types[: spec.n_sites]
    return [str(t) for t in rng.permutation(np.array(types))]


def build_topology(rng: np.random.Generator, cfg: SimConfig) -> Topology:
    nodes: list[dict[str, Any]] = []
    upf_regions: dict[str, list[str]] = {}
    for spec in cfg.regions:
        upf_regions.setdefault(spec.upf_id, []).append(spec.region_id)
    shared_note = "Shared dependency of every cell in every region (single instance)."
    nodes.append(
        _node(
            "CORE-DNS-01",
            "core_dns",
            "Core DNS 01",
            None,
            None,
            {"serves": "all_regions", "shared_dependency": True, "note": shared_note},
        )
    )
    nodes.append(
        _node(
            "CORE-AMF-01",
            "core_amf",
            "Core AMF/MME 01",
            None,
            None,
            {"serves": "all_regions", "shared_dependency": True, "note": shared_note},
        )
    )
    for upf_id in sorted(upf_regions):
        nodes.append(
            _node(
                upf_id,
                "core_upf",
                f"Core UPF {upf_id[-2:]}",
                None,
                None,
                {"serves_regions": upf_regions[upf_id]},
            )
        )

    sites: dict[str, SiteInfo] = {}
    link_sites: dict[str, list[str]] = {}
    agg_links: dict[str, list[str]] = {}
    link_medium: dict[str, str] = {}
    link_region: dict[str, str] = {}
    agg_region: dict[str, str] = {}
    region_sites: dict[str, list[str]] = {}
    site_nodes: list[dict[str, Any]] = []
    link_nodes: list[dict[str, Any]] = []

    for spec in cfg.regions:
        rid = spec.region_id
        agg_ids = [f"AGG-{rid}-{i:02d}" for i in (1, 2)]
        for agg_id in agg_ids:
            agg_region[agg_id] = rid
            agg_links[agg_id] = []
            nodes.append(
                _node(
                    agg_id,
                    "agg_router",
                    f"Aggregation Router {rid}-{agg_id[-2:]}",
                    rid,
                    spec.upf_id,
                    {"role": "aggregation"},
                )
            )

        area = _area_types(rng, spec)
        venue_idx = (
            list(range(cfg.near_venue_sites)) if rid == cfg.venue_region else []
        )  # these sites sit next to the venue
        for i in venue_idx:
            area[i] = "urban" if i < cfg.near_venue_sites - 1 else "suburban"
        scale = {"urban": 0.03, "suburban": 0.07, "rural": 0.15}
        coords: list[tuple[float, float]] = []
        for i in range(spec.n_sites):
            if i in venue_idx:
                coords.append(
                    (
                        cfg.venue_lat + float(rng.normal(0, 0.008)),
                        cfg.venue_lon + float(rng.normal(0, 0.008)),
                    )
                )
            else:
                s = scale[area[i]]
                coords.append(
                    (
                        spec.lat + float(np.clip(rng.normal(0, s), -0.3, 0.3)),
                        spec.lon + float(np.clip(rng.normal(0, s * 1.2), -0.3, 0.3)),
                    )
                )
        names = list(spec.localities)
        order = sorted(range(spec.n_sites), key=lambda k: (coords[k][0], coords[k][1]))
        groups = np.array_split(np.array(order), spec.n_links)
        n_first = -(-spec.n_links // 2)
        letters = {agg_ids[0]: iter("ABC"), agg_ids[1]: iter("ABC")}
        for g_idx, group in enumerate(groups):
            agg_id = agg_ids[0] if g_idx < n_first else agg_ids[1]
            link_id = f"LNK-{rid}-{agg_id[-2:]}-{next(letters[agg_id])}"
            agg_links[agg_id].append(link_id)
            link_region[link_id] = rid
            link_sites[link_id] = []
            for k in group.tolist():
                site_id = f"S-{rid}-{k + 1:03d}"
                info = SiteInfo(
                    site_id,
                    rid,
                    link_id,
                    agg_id,
                    spec.upf_id,
                    area[k],
                    k in venue_idx,
                    round(coords[k][0], 5),
                    round(coords[k][1], 5),
                )
                sites[site_id] = info
                link_sites[link_id].append(site_id)
                region_sites.setdefault(rid, []).append(site_id)
                locality = names[k] if k < len(names) else f"Site {k + 1}"
                site_nodes.append(
                    _node(
                        site_id,
                        "site",
                        f"{site_id} {locality}",
                        rid,
                        link_id,
                        {
                            "lat": info.lat,
                            "lon": info.lon,
                            "area_type": info.area_type,
                            "near_venue": info.near_venue,
                            "locality": locality,
                        },
                    )
                )
            link_nodes.append(
                _node(link_id, "transport_link", f"Link {link_id[4:]}", rid, agg_id, {})
            )
        region_sites[rid].sort()

    link_ids = [n["node_id"] for n in link_nodes]
    mw = set(rng.choice(len(link_ids), size=cfg.microwave_links, replace=False).tolist())
    for i, ln in enumerate(link_nodes):
        medium = "microwave" if i in mw else "fiber"
        link_medium[ln["node_id"]] = medium
        if medium == "microwave":
            ln["attrs"] = {
                "medium": medium,
                "capacity_gbps": 1.0,
                "band_ghz": int(rng.choice([18, 23])),
                "length_km": round(float(rng.uniform(4, 18)), 1),
            }
        else:
            ln["attrs"] = {
                "medium": medium,
                "capacity_gbps": 10.0,
                "length_km": round(float(rng.uniform(2, 30)), 1),
            }
    nodes.extend(link_nodes)
    site_nodes.sort(key=lambda n: n["node_id"])
    nodes.extend(site_nodes)

    cell_rows: list[dict[str, Any]] = []
    site_cell_rows: dict[str, list[int]] = {}
    for site_id in sorted(sites):
        info = sites[site_id]
        site_cell_rows[site_id] = []
        for sector in range(1, cfg.cells_per_site + 1):
            if info.near_venue:
                is_5g = sector <= 2
            elif info.area_type == "urban":
                is_5g = bool(rng.random() < (0.8 if sector == 1 else 0.4 if sector == 2 else 0.0))
            elif info.area_type == "suburban":
                is_5g = bool(sector == 1 and rng.random() < 0.15)
            else:
                is_5g = False
            tech = "5G" if is_5g else "4G"
            base_cap = cfg.capacity_mbps_5g if is_5g else cfg.capacity_mbps_4g
            cap = base_cap * float(rng.uniform(0.85, 1.15))
            if info.near_venue:
                cap *= cfg.venue_capacity_boost
            site_cell_rows[site_id].append(len(cell_rows))
            cell_rows.append(
                {
                    "cell_id": f"C-{site_id[2:]}-{sector}",
                    "site_id": site_id,
                    "technology": tech,
                    "sector": sector,
                    "capacity_mbps": round(cap, 1),
                }
            )

    regions = rows_to_frame(
        "regions", [{"region_id": r.region_id, "name": r.name} for r in cfg.regions]
    )
    return Topology(
        nodes=rows_to_frame("nodes", nodes),
        cells=rows_to_frame("cells", cell_rows),
        regions=regions,
        sites=dict(sorted(sites.items())),
        link_sites=link_sites,
        agg_links=agg_links,
        link_medium=link_medium,
        link_region=link_region,
        agg_region=agg_region,
        region_sites=region_sites,
        site_cell_rows=site_cell_rows,
        upf_regions=upf_regions,
    )
