"""Assemble a complete, deterministic World from a seed."""

from typing import Any

import numpy as np

from incident_agent.simulator.config import SimConfig
from incident_agent.simulator.drafts import Ctx, ScenarioDraft
from incident_agent.simulator.events import EventLog, FinalEvents, Handle
from incident_agent.simulator.frames import rows_to_frame
from incident_agent.simulator.kpis import (
    Effects,
    build_baseline,
    cell_kpi_frame,
    derive_cell_kpis,
    derive_core_kpis,
)
from incident_agent.simulator.noise import Blocklist, add_background_noise
from incident_agent.simulator.placement import place_scenarios
from incident_agent.simulator.questions import make_questions
from incident_agent.simulator.scenarios import SCENARIO_KINDS
from incident_agent.simulator.timeaxis import TimeAxis, local_to_utc
from incident_agent.simulator.topology import build_topology
from incident_agent.simulator.world import World

DATASET_VERSION = "m2-1"


def _ref(ev: FinalEvents, h: Handle) -> dict[str, str]:
    return {"table": h[0], "id": ev.ids[h]}


def _scenario_rows(
    drafts: list[ScenarioDraft],
    ev: FinalEvents,
    questions: list[list[dict[str, str]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n, (d, qs) in enumerate(zip(drafts, questions, strict=True), start=1):
        rows.append(
            {
                "scenario_id": f"SCN-{n:03d}",
                "kind": d.kind,
                "is_incident": d.is_incident,
                "root_cause_category": d.category,
                "root_cause_node_id": d.root_node,
                "start_at": d.start,
                "impact_start_at": d.impact_start,
                "end_at": d.end,
                "affected_node_ids": d.affected_nodes,
                "affected_region_ids": d.regions,
                "severity": d.severity,
                "difficulty": d.difficulty,
                "evidence": [_ref(ev, h) for h in d.evidence],
                "expected_tools": d.expected_tools,
                "questions": qs,
                "confounders": [{**_ref(ev, h), "why": why} for h, why in d.confounders],
                "notes": d.notes
                + (f" Overlaps in time with group '{d.group}'." if d.group else ""),
            }
        )
    return rows


def build_world(seed: int = 42, config: SimConfig | None = None) -> World:
    cfg = config or SimConfig()
    rng = np.random.default_rng(seed)
    axis = TimeAxis.from_config(cfg)
    topo = build_topology(rng, cfg)
    base = build_baseline(rng, cfg, axis, topo)
    fx = Effects.neutral(len(topo.cells), axis.n_steps)
    log = EventLog()
    ctx = Ctx(cfg, axis, topo, base, fx, log, rng)

    region_names = dict(zip(topo.regions["region_id"], topo.regions["name"], strict=True))
    drafts: list[ScenarioDraft] = []
    questions: list[list[dict[str, str]]] = []
    for placed in place_scenarios(ctx):
        draft = SCENARIO_KINDS[placed.spec.kind].apply(ctx, placed.params, placed.start)
        draft.group = placed.spec.overlap_group
        drafts.append(draft)
        questions.append(make_questions(rng, cfg, axis, draft, region_names))

    add_background_noise(ctx, Blocklist(drafts))

    arrays = derive_cell_kpis(rng, cfg, axis, base, fx)
    cell_kpis = cell_kpi_frame(axis, topo.cell_ids, arrays)
    core_kpis = derive_core_kpis(rng, cfg, axis, topo, base, arrays, fx)
    ev = log.finalize()

    meta = {
        "seed": str(seed),
        "window_start": axis.start.isoformat(),
        "window_end": axis.end.isoformat(),
        "now": local_to_utc(cfg.now_local, cfg.utc_offset_hours).isoformat(),
        "step_minutes": str(cfg.step_minutes),
        "timezone": cfg.timezone_name,
        "version": DATASET_VERSION,
    }
    world = World(
        regions=topo.regions,
        nodes=topo.nodes,
        cells=topo.cells,
        cell_kpis=cell_kpis,
        core_kpis=core_kpis,
        alarms=ev.alarms,
        changes=ev.changes,
        maintenance=ev.maintenance,
        external_events=ev.external_events,
        scenarios=rows_to_frame("scenarios", _scenario_rows(drafts, ev, questions)),
        dataset_meta=rows_to_frame(
            "dataset_meta", [{"key": k, "value": v} for k, v in meta.items()]
        ),
    )
    world.validate()
    _check_references(world)
    return world


def _check_references(world: World) -> None:
    """Fail loudly if ground truth points at rows that do not exist."""
    key = {
        "alarms": "alarm_id",
        "changes": "change_id",
        "maintenance": "mw_id",
        "external_events": "event_id",
    }
    known = {t: set(getattr(world, t)[c]) for t, c in key.items()}
    nodes = set(world.nodes["node_id"])
    for sc in world.scenarios.to_dict(orient="records"):
        sid = sc["scenario_id"]
        refs: list[dict[str, Any]] = [*sc["evidence"], *sc["confounders"]]
        for r in refs:
            if r["id"] not in known[r["table"]]:
                raise ValueError(f"{sid}: unknown {r['table']} id {r['id']}")
        root = sc["root_cause_node_id"]
        if isinstance(root, str) and root not in nodes:
            raise ValueError(f"{sid}: unknown root cause node {root}")
        missing = [n for n in sc["affected_node_ids"] if n not in nodes]
        if missing:
            raise ValueError(f"{sid}: unknown affected nodes {missing}")
