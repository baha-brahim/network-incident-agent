"""Normal network behaviour (vectorised over cells x steps) plus the scenario effect layer."""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.frames import coerce
from incident_agent.simulator.timeaxis import TimeAxis
from incident_agent.simulator.topology import AMF_ID, AREA_TYPES, DNS_ID, Topology

# Diurnal shape per area type: night floor and (centre hour, sigma, amplitude) Gaussians.
_DIURNAL: dict[str, tuple[float, list[tuple[float, float, float]]]] = {
    "urban": (0.10, [(9.0, 1.8, 0.55), (14.0, 2.6, 0.62), (21.5, 2.0, 0.85)]),
    "suburban": (0.10, [(9.0, 1.8, 0.30), (14.0, 2.6, 0.38), (21.5, 2.0, 1.0)]),
    "rural": (0.10, [(9.0, 1.8, 0.30), (14.0, 2.6, 0.35), (21.0, 2.2, 0.95)]),
}
# Weekly multiplier per area type, Monday..Sunday.
_WEEKLY: dict[str, list[float]] = {
    "urban": [1.0, 1.02, 1.02, 1.0, 0.97, 0.82, 0.74],
    "suburban": [0.97, 0.97, 0.98, 1.0, 1.03, 1.10, 1.12],
    "rural": [0.98, 0.98, 0.99, 1.0, 1.02, 1.05, 1.06],
}
_GRID = np.linspace(0, 24, 961)


def _diurnal(hours: np.ndarray, area: str) -> np.ndarray:
    floor, comps = _DIURNAL[area]

    def curve(h: np.ndarray) -> np.ndarray:
        out = np.full_like(h, floor, dtype=float)
        for mu, sigma, amp in comps:
            d = (h - mu + 12.0) % 24.0 - 12.0
            out = out + amp * np.exp(-0.5 * (d / sigma) ** 2)
        return out

    return curve(hours) / float(curve(_GRID).max())


def ar1(rng: np.random.Generator, rows: int, steps: int, rho: float, sigma: float) -> np.ndarray:
    """Stationary AR(1) series with marginal std `sigma`, shape (rows, steps)."""
    eps = rng.standard_normal((rows, steps)) * (sigma * np.sqrt(1.0 - rho**2))
    out = np.empty((rows, steps))
    out[:, 0] = rng.standard_normal(rows) * sigma
    for t in range(1, steps):
        out[:, t] = rho * out[:, t - 1] + eps[:, t]
    return out


@dataclass(frozen=True)
class Baseline:
    users: np.ndarray  # (C, T) active users without any scenario effect
    rate_mbps: np.ndarray  # (C,) DL Mbps per active user
    cap_mbps: np.ndarray  # (C,)
    ul_ratio: np.ndarray  # (C,)
    base_latency: np.ndarray  # (C,)
    base_drop: np.ndarray  # (C,)
    base_rrc: np.ndarray  # (C,)
    cell_area: list[str]
    cell_region: list[str]

    @property
    def demand_mbps(self) -> np.ndarray:
        demand: np.ndarray = self.users * self.rate_mbps[:, None]
        return demand


@dataclass
class Effects:
    """Per cell/step modifiers that scenarios accumulate; neutral by default."""

    users_mult: np.ndarray
    volume_mult: np.ndarray
    latency_mult: np.ndarray
    latency_add: np.ndarray
    drop_mult: np.ndarray
    drop_add: np.ndarray
    rrc_add: np.ndarray
    demand_floor: np.ndarray  # fraction of capacity demand is forced up to (congestion)
    down_frac: np.ndarray  # fraction of each step the cell is out of service
    dns_success_sub: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dns_res_mult: np.ndarray = field(default_factory=lambda: np.ones(0))

    @classmethod
    def neutral(cls, n_cells: int, n_steps: int) -> "Effects":
        shape = (n_cells, n_steps)
        return cls(
            users_mult=np.ones(shape),
            volume_mult=np.ones(shape),
            latency_mult=np.ones(shape),
            latency_add=np.zeros(shape),
            drop_mult=np.ones(shape),
            drop_add=np.zeros(shape),
            rrc_add=np.zeros(shape),
            demand_floor=np.zeros(shape),
            down_frac=np.zeros(shape),
            dns_success_sub=np.zeros(n_steps),
            dns_res_mult=np.ones(n_steps),
        )

    def add_down(self, rows: list[int], frac: np.ndarray) -> None:
        self.down_frac[rows] = 1.0 - (1.0 - self.down_frac[rows]) * (1.0 - frac)


def build_baseline(
    rng: np.random.Generator, cfg: SimConfig, axis: TimeAxis, topo: Topology
) -> Baseline:
    cells = topo.cells
    n_c, n_t = len(cells), axis.n_steps
    site_info = topo.sites
    area = [site_info[s].area_type for s in cells["site_id"]]
    region = [site_info[s].region_id for s in cells["site_id"]]
    tech = cells["technology"].tolist()

    peak = np.array([cfg.peak_users[f"{t}:{a}"] for t, a in zip(tech, area, strict=True)])
    peak = peak * np.exp(rng.normal(0.0, 0.2, n_c))
    # Venue cells carry extra capacity but not extra everyday traffic headroom problems.
    rate = np.array([cfg.per_user_mbps_5g if t == "5G" else cfg.per_user_mbps_4g for t in tech])
    rate = rate * np.exp(rng.normal(0.0, 0.05, n_c))

    # Site-level phase shift so sites do not peak at the same minute.
    site_shift = {s: float(rng.uniform(-0.5, 0.5)) for s in sorted(site_info)}
    shift = np.array([site_shift[s] for s in cells["site_id"]])

    shape = np.empty((n_c, n_t))
    weekly = np.empty((n_c, n_t))
    for a in AREA_TYPES:
        rows = np.array([i for i, x in enumerate(area) if x == a], dtype=int)
        if len(rows) == 0:
            continue
        hours = axis.local_hour[None, :] + shift[rows, None]
        shape[rows] = _diurnal(hours, a)
        weekly[rows] = np.array(_WEEKLY[a])[axis.local_dow][None, :]

    rho = cfg.noise_rho
    cell_noise = ar1(rng, n_c, n_t, rho, cfg.users_noise_sigma)
    region_ids = [r.region_id for r in cfg.regions]
    reg_noise = ar1(rng, len(region_ids), n_t, 0.97, cfg.regional_noise_sigma)
    reg_idx = np.array([region_ids.index(r) for r in region])
    users = peak[:, None] * shape * weekly * np.exp(cell_noise + reg_noise[reg_idx])

    is_5g = np.array([t == "5G" for t in tech])
    rural = np.array([a == "rural" for a in area])
    base_latency = np.where(is_5g, 18.0, 35.0) * rng.uniform(0.9, 1.1, n_c) + np.where(rural, 8, 0)
    return Baseline(
        users=users,
        rate_mbps=rate,
        cap_mbps=cells["capacity_mbps"].to_numpy(),
        ul_ratio=rng.uniform(0.12, 0.18, n_c),
        base_latency=base_latency,
        base_drop=rng.uniform(0.4, 0.8, n_c),
        base_rrc=rng.uniform(99.0, 99.7, n_c),
        cell_area=area,
        cell_region=region,
    )


def _excess(prb: np.ndarray, knee: float, span: float) -> np.ndarray:
    return np.clip((prb - knee) / span, 0.0, None)


def derive_cell_kpis(
    rng: np.random.Generator,
    cfg: SimConfig,
    axis: TimeAxis,
    base: Baseline,
    fx: Effects,
) -> dict[str, np.ndarray]:
    """Turn baseline drivers plus scenario effects into final (C, T) KPI arrays."""
    n_c, n_t = base.users.shape
    step_s = axis.step_min * 60.0
    cap = base.cap_mbps[:, None]

    # Micro-outages: rare, harmless blips of availability.
    micro = np.where(
        rng.random((n_c, n_t)) < cfg.micro_outage_prob,
        rng.choice([1 / 15, 2 / 15, 4 / 15], size=(n_c, n_t)),
        0.0,
    )
    down = 1.0 - (1.0 - fx.down_frac) * (1.0 - micro)
    up = 1.0 - down

    users = base.users * fx.users_mult
    vol_noise = ar1(rng, n_c, n_t, cfg.noise_rho, 0.05)
    demand = users * base.rate_mbps[:, None] * fx.volume_mult * np.exp(vol_noise)
    demand = np.maximum(demand, fx.demand_floor * cap)
    delivered = np.minimum(demand, cap)
    prb_raw = delivered / cap * 100.0

    dl_mb = delivered * up * step_s / 8.0
    ul_noise = np.exp(rng.normal(0.0, 0.03, (n_c, n_t)))
    ul_mb = dl_mb * base.ul_ratio[:, None] * ul_noise

    excess_lat = _excess(prb_raw, 80.0, 20.0)
    lat_noise = ar1(rng, n_c, n_t, cfg.noise_rho, 0.07)
    latency = base.base_latency[:, None] * np.exp(lat_noise)
    latency = latency + 8.0 * (prb_raw / 100.0) ** 2 + 90.0 * excess_lat**2
    latency = latency * fx.latency_mult + fx.latency_add

    excess = _excess(prb_raw, 85.0, 15.0)
    drop_noise = ar1(rng, n_c, n_t, 0.5, 0.2)
    drop = base.base_drop[:, None] * np.exp(drop_noise) + 3.5 * excess**2
    drop = np.clip(drop * fx.drop_mult + fx.drop_add, 0.0, 100.0)

    rrc_noise = ar1(rng, n_c, n_t, 0.5, 0.08)
    rrc = base.base_rrc[:, None] + rrc_noise - 2.5 * excess**2 + fx.rrc_add
    rrc = np.clip(rrc, 0.0, 100.0)

    fully_down = up < 0.001
    users_out = np.where(fully_down, 0.0, users * up)
    prb = np.where(fully_down, 0.0, prb_raw * up)
    # A dead cell reports no quality measurements: NaN (NULL in Postgres), not 0.
    latency = np.where(fully_down, np.nan, np.clip(latency, 1.0, None))
    drop = np.where(fully_down, np.nan, drop)
    rrc = np.where(fully_down, np.nan, rrc)
    return {
        "dl_volume_mb": np.round(dl_mb, 2),
        "ul_volume_mb": np.round(ul_mb, 2),
        "active_users": np.round(users_out, 1),
        "rrc_success_pct": np.round(rrc, 3),
        "drop_rate_pct": np.round(drop, 3),
        "latency_ms": np.round(latency, 2),
        "prb_util_pct": np.round(prb, 2),
        "availability_pct": np.round(up * 100.0, 2),
    }


def cell_kpi_frame(
    axis: TimeAxis, cell_ids: list[str], arrays: dict[str, np.ndarray]
) -> pd.DataFrame:
    n_c, n_t = len(cell_ids), axis.n_steps
    data: dict[str, Any] = {
        "ts": pd.DatetimeIndex(np.tile(axis.ts.values, n_c), tz="UTC"),
        "cell_id": np.repeat(np.array(cell_ids, dtype=object), n_t),
    }
    for name, arr in arrays.items():
        data[name] = arr.reshape(-1)
    return coerce("cell_kpis", pd.DataFrame(data))


def derive_core_kpis(
    rng: np.random.Generator,
    cfg: SimConfig,
    axis: TimeAxis,
    topo: Topology,
    base: Baseline,
    arrays: dict[str, np.ndarray],
    fx: Effects,
) -> pd.DataFrame:
    n_t = axis.n_steps
    step_s = axis.step_min * 60.0
    region_arr = np.array(base.cell_region)
    dl_gbps = arrays["dl_volume_mb"] * 8.0 / step_s / 1000.0
    users = arrays["active_users"]

    series: list[tuple[str, str, np.ndarray]] = []
    total_users = users.sum(axis=0)
    load = total_users / max(float(total_users.max()), 1.0)
    dns_noise = ar1(rng, 1, n_t, 0.6, 1.0)[0]
    success = 99.9 - np.abs(dns_noise) * 0.02 - fx.dns_success_sub
    res_base = 9.0 + 4.0 * load + rng.normal(0.0, 0.6, n_t)
    resolution = np.clip(res_base, 5.0, None) * fx.dns_res_mult
    series.append((DNS_ID, "query_success_pct", np.clip(np.round(success, 3), 0, 100)))
    series.append((DNS_ID, "resolution_ms", np.round(resolution, 2)))
    for upf_id in sorted(topo.upf_regions):
        mask = np.isin(region_arr, topo.upf_regions[upf_id])
        series.append((upf_id, "throughput_gbps", np.round(dl_gbps[mask].sum(axis=0), 4)))
        sess = users[mask].sum(axis=0) * 2.2 * np.exp(rng.normal(0.0, 0.02, n_t))
        series.append((upf_id, "session_count", np.round(sess, 0)))
    amf = 99.5 + ar1(rng, 1, n_t, 0.5, 0.06)[0]
    series.append((AMF_ID, "attach_success_pct", np.clip(np.round(amf, 3), 0, 100)))

    frames = [
        pd.DataFrame({"ts": axis.ts, "node_id": node, "metric": metric, "value": vals})
        for node, metric, vals in series
    ]
    return coerce("core_kpis", pd.concat(frames, ignore_index=True))
