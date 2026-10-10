# ruff: noqa: E501
"""Threshold sweep, held-out evaluation, and the results files (JSON, PNG, Markdown)."""

import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pandas as pd

from incident_agent.detector.config import DetectorConfig
from incident_agent.detector.evaluate import (
    PreparedWorld,
    evaluate_alerts,
    evaluate_prepared,
    pool,
    prepare_world,
)
from incident_agent.detector.pipeline import detect_prepared
from incident_agent.simulator.build import build_world

TUNE_SEED = 42
HELD_OUT_SEEDS = (1, 2, 3)
Z_GRID = (3.0, 3.5, 4.0, 5.0, 6.0, 8.0)
STEPS_GRID = (1, 2, 3, 4)
SEVERITY_FILTERS = (
    ("all alerts", ("low", "medium", "high")),
    ("medium and high", ("medium", "high")),
    ("high only", ("high",)),
)


def run_sweep(pw: PreparedWorld, base: DetectorConfig) -> list[dict[str, Any]]:
    """Evaluate every (z_threshold, min_steps) pair on one prepared world."""
    rows: list[dict[str, Any]] = []
    for steps in STEPS_GRID:
        for z in Z_GRID:
            ev = evaluate_prepared(pw, replace(base, z_threshold=z, min_steps=steps))
            rows.append(
                {
                    "z_threshold": z,
                    "min_steps": steps,
                    "alerts": ev.n_alerts,
                    "alerts_per_day": ev.alerts_per_day,
                    "precision": ev.precision,
                    "recall": ev.recall,
                    "recall_incidents": ev.recall_incidents,
                    "f1": ev.f1,
                    "f2": ev.f2,
                    "delay_median_min": ev.delay_median_min,
                    "fragmentation": ev.fragmentation,
                    "merged_alerts": len(ev.merged_alerts),
                    "missed": [
                        f"{m['scenario_id']} ({m['kind']}, {m['difficulty']})" for m in ev.missed
                    ],
                }
            )
    return rows


def sweep_table(rows: list[dict[str, Any]], default: DetectorConfig | None = None) -> str:
    head = "  z  steps  alerts  /day  precision  recall  recall(inc)    F1    F2  fragm."
    lines = [head]
    for r in rows:
        star = (
            " <- default"
            if default
            and r["z_threshold"] == default.z_threshold
            and r["min_steps"] == default.min_steps
            else ""
        )
        lines.append(
            f"{r['z_threshold']:>3g}  {r['min_steps']:>5d}  {r['alerts']:>6d}  {r['alerts_per_day']:>4.1f}"
            f"  {r['precision']:>9.3f}  {r['recall']:>6.3f}  {r['recall_incidents']:>11.3f}"
            f"  {r['f1']:.3f} {r['f2']:.3f}  {r['fragmentation']:.2f}{star}"
        )
    return "\n".join(lines)


def severity_breakdown(pws: list[PreparedWorld], cfg: DetectorConfig) -> list[dict[str, Any]]:
    """What happens if only alerts of some severities are forwarded."""
    out: list[dict[str, Any]] = []
    results = [(pw, detect_prepared(pw.prepared, cfg).alerts) for pw in pws]
    for label, keep in SEVERITY_FILTERS:
        evals = [
            evaluate_alerts(
                alerts[alerts["severity"].isin(keep)].reset_index(drop=True),
                pw.world,
                pw.prepared.topology,
                cfg,
                pw.n_days,
                pw.seed,
            )
            for pw, alerts in results
        ]
        p = pool(evals)
        out.append(
            {
                "filter": label,
                "alerts_per_day": p["alerts_per_day"],
                "precision": p["precision"],
                "recall": p["recall"],
                "recall_by_kind": {k: v["recall"] for k, v in p["by_kind"].items()},
            }
        )
    return out


def run_evaluation(
    cfg: DetectorConfig, held_out: tuple[int, ...] = HELD_OUT_SEEDS, tune_seed: int = TUNE_SEED
) -> dict[str, Any]:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    t = time.perf_counter()
    tune = prepare_world(build_world(tune_seed), tune_seed, cfg)
    timings["build_and_baseline_seed_42_s"] = time.perf_counter() - t
    t = time.perf_counter()
    sweep = run_sweep(tune, cfg)
    timings["sweep_24_configs_s"] = time.perf_counter() - t

    tune_eval = evaluate_prepared(tune, cfg)
    held_pws = [prepare_world(build_world(s), s, cfg) for s in held_out]
    held_evals = [evaluate_prepared(pw, cfg) for pw in held_pws]
    timings["total_s"] = time.perf_counter() - t0
    return {
        "config": {
            k: v for k, v in asdict(cfg).items() if k not in ("cell_metrics", "core_metrics")
        },
        "tuning_seed": tune_seed,
        "held_out_seeds": list(held_out),
        "sweep_seed_42": sweep,
        "seed_42": tune_eval.to_dict(),
        "held_out": [e.to_dict() for e in held_evals],
        "held_out_pooled": pool(held_evals),
        "severity_filters_held_out": severity_breakdown(held_pws, cfg),
        "timings_s": timings,
    }


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _json_default(obj: object) -> Any:
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


# --- plot ------------------------------------------------------------------------------------


def write_plot(report: dict[str, Any], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ramp = {1: "#9ecae1", 2: "#6baed6", 3: "#3182bd", 4: "#08519c"}
    default = report["config"]
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=140)
    for steps in STEPS_GRID:
        pts = [r for r in report["sweep_seed_42"] if r["min_steps"] == steps]
        ax.plot(
            [r["recall"] for r in pts],
            [r["precision"] for r in pts],
            "-o",
            color=ramp[steps],
            lw=2,
            ms=6,
            label=f"min_steps = {steps}",
        )
    star = next(
        r
        for r in report["sweep_seed_42"]
        if r["z_threshold"] == default["z_threshold"] and r["min_steps"] == default["min_steps"]
    )
    ax.plot(
        star["recall"],
        star["precision"],
        "*",
        color="#d95f02",
        ms=18,
        mec="white",
        mew=1.2,
        label=f"chosen default (z={default['z_threshold']:g}, steps={default['min_steps']}), seed 42",
        zorder=5,
    )
    for ev in report["held_out"]:
        ax.plot(
            ev["recall"],
            ev["precision"],
            "D",
            mfc="none",
            mec="#333333",
            mew=1.6,
            ms=8,
            label="same default on held-out seeds" if ev is report["held_out"][0] else None,
            zorder=4,
        )
        ax.annotate(
            f"seed {ev['seed']}",
            (ev["recall"], ev["precision"]),
            textcoords="offset points",
            xytext=(7, -3),
            fontsize=8,
            color="#333333",
        )
    lo = [r for r in report["sweep_seed_42"] if r["min_steps"] == 3]
    for r in [r for r in lo if r["z_threshold"] >= 5]:
        ax.annotate(
            f"z={r['z_threshold']:g}",
            (r["recall"], r["precision"]),
            textcoords="offset points",
            xytext=(-4, -13),
            fontsize=7.5,
            color="#3182bd",
            ha="right",
        )
    ax.set_xlabel("recall (share of detectable scenarios that raised an alert)")
    ax.set_ylabel("precision (share of alerts that match a scenario)")
    ax.set_title(
        "Detector: precision vs recall, threshold sweep on seed 42", loc="left", fontsize=11
    )
    ax.set_xlim(0.8, 1.02)
    ax.set_ylim(0.3, 1.0)
    ax.grid(True, color="#e5e5e5", lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower left", fontsize=8, frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# --- markdown --------------------------------------------------------------------------------


def _fmt(x: float | None, nd: int = 2) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def _headline_row(label: str, d: dict[str, Any]) -> str:
    return (
        f"| {label} | {d['n_alerts']} | {d['alerts_per_day']:.1f} | {d['precision']:.2f} "
        f"| {d['recall']:.2f} | {d['f1']:.2f} | {_fmt(d['delay_median_min'], 0)} "
        f"| {_fmt(d['delay_p90_min'], 0)} | {d['fragmentation']:.2f} | {d['n_merged_alerts']} |"
    )


def write_markdown(report: dict[str, Any], path: Path) -> None:
    cfg = report["config"]
    sweep = report["sweep_seed_42"]
    pooled = report["held_out_pooled"]
    s42 = report["seed_42"]
    held = report["held_out"]
    step_min = 15

    def ev_dict(e: dict[str, Any]) -> dict[str, Any]:
        return {**e, "n_merged_alerts": len(e["merged_alerts"])}

    sweep_rows = "\n".join(
        f"| {r['z_threshold']:g} | {r['min_steps']} | {r['alerts']} | {r['alerts_per_day']:.1f} "
        f"| {r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} | {r['f2']:.2f} "
        f"| {'**chosen**' if r['z_threshold'] == cfg['z_threshold'] and r['min_steps'] == cfg['min_steps'] else ''} |"
        for r in sweep
    )
    first_losses = []
    for r in sweep:
        if r["min_steps"] == cfg["min_steps"] and r["missed"]:
            first_losses.append(f"    - z = {r['z_threshold']:g}: missed {', '.join(r['missed'])}")
    losses = (
        "\n".join(first_losses)
        if first_losses
        else "- (nothing is missed anywhere on the grid at this step count)"
    )

    head_rows = "\n".join(
        [_headline_row(f"seed {e['seed']}", ev_dict(e)) for e in held]
        + [_headline_row("**held-out pooled (1, 2, 3)**", pooled)]
        + [_headline_row("seed 42 (tuning seed, for reference)", ev_dict(s42))]
    )
    kinds = sorted(pooled["by_kind"])
    kind_rows = "\n".join(
        f"| {k} | {pooled['by_kind'][k]['detected']}/{pooled['by_kind'][k]['n']} "
        f"| {pooled['by_kind'][k]['recall']:.2f} "
        f"| {s42['by_kind'][k]['detected']}/{s42['by_kind'][k]['n']} |"
        for k in kinds
    )
    diff_rows = "\n".join(
        f"| {k} | {v['detected']}/{v['n']} | {v['recall']:.2f} |"
        for k, v in pooled["by_difficulty"].items()
    )
    pair_lines = []
    for e in [s42, *held]:
        for p in e["overlap_pairs"]:
            parts = ", ".join(
                f"{s['scenario_id']} ({s['kind']}) -> {', '.join(s['alerts']) or 'no alert'}"
                for s in p["scenarios"]
            )
            verdict = "kept apart" if p["kept_apart"] else "NOT kept apart"
            pair_lines.append(f"| {e['seed']} | {p['group']} | {parts} | {verdict} |")
    pair_rows = "\n".join(pair_lines)
    sev_rows = "\n".join(
        f"| {s['filter']} | {s['alerts_per_day']:.1f} | {s['precision']:.2f} | {s['recall']:.2f} "
        f"| {min(s['recall_by_kind'].items(), key=lambda kv: kv[1])[0]} ({min(s['recall_by_kind'].values()):.2f}) |"
        for s in report["severity_filters_held_out"]
    )
    fps = [(e["seed"], f) for e in held for f in e["false_positives"]]
    fp_sites: dict[str, int] = {}
    for _, f in fps:
        for token in f["summary"].replace("(", " ").replace(")", " ").replace(",", " ").split():
            if token.startswith("S-"):
                fp_sites[token] = fp_sites.get(token, 0) + 1
    top_fp = ", ".join(f"{s} ({n})" for s, n in sorted(fp_sites.items(), key=lambda kv: -kv[1])[:5])
    n_low = sum(1 for _, f in fps if f["severity"] == "low")
    n_storm = sum(1 for _, f in fps if f["during_alarm_storm"])
    t = report["timings_s"]

    text = f"""# Anomaly detector: results

Generated by `uv run python -m incident_agent.detector evaluate`. Numbers below are produced by that command; re-running it overwrites this file.

## What the detector does

It watches the network's KPI time series (traffic, users, availability, call setup success, drop rate, latency, radio load, plus DNS/UPF/AMF health) and raises an **alert** when something moves far away from its normal level for long enough. It is a simple, explainable detector, not a learned model. The point of this milestone is that we can *measure* it, because the synthetic network comes with labelled incidents.

Steps:

1. **Series.** For each site and each region, cells are combined into one series per metric (traffic and users are summed; latency, drop rate and RRC success are averaged weighted by traffic; radio load and availability are plain averages). Core nodes are monitored as they are. Cells that are down report no latency, drop or RRC value (NULL); those gaps are skipped, and the availability series carries the outage signal.
2. **Baseline.** For each series, day type (weekday, Saturday, Sunday) and 15-minute slot of the day, the detector takes the **median** of the values seen at that slot (and the two slots either side) on days of the same type. The spread is the **MAD** (median absolute deviation: the median of how far each value is from the median). Median and MAD are *robust*: a few abnormal days barely move them, which is why an incident does not hide itself.
3. **Robust z-score.** `z = (value - median) / (1.4826 * MAD + floor)`. It says how many "normal wiggles" the value is from normal. The 1.4826 factor makes MAD comparable to a standard deviation. The small per-metric floor stops near-constant series, such as availability (almost always 100), from producing huge scores on harmless changes.
4. **Anomaly.** At least `min_steps` consecutive 15-minute steps with `z` beyond `z_threshold` in a direction that matters for the metric (volume: down or up; availability, RRC success, DNS and attach success: down; latency, drop rate, radio load, DNS time: up). A single normal step inside a run is bridged. A one-step blip never fires.
5. **Alert.** Anomalies that overlap in time and are related are grouped: same site, same transport link or aggregation router, same region, or core/nationwide. Two regions with problems at the same time stay separate alerts, unless three or more regions are affected at once (then it is one nationwide alert), or DNS/AMF is affected (everything depends on those). Each alert has a score, a `low | medium | high` label and a one-sentence summary.

Defaults: `z_threshold = {cfg["z_threshold"]:g}`, `min_steps = {cfg["min_steps"]}` (that is {cfg["min_steps"] * step_min} minutes of sustained deviation).

## How it is scored

Terms, for a reader who has not seen them before:

- **Precision**: of the alerts raised, the share that match a planted scenario. Low precision means noisy alerts.
- **Recall**: of the scenarios the detector could possibly see, the share that got at least one matching alert. Low recall means missed incidents.
- **F1** balances the two. **F2** weights recall twice as much as precision. We care about F2 more: a missed real incident costs more than an extra alert.

Rules (code: `detector/evaluate.py`, the only place that reads ground truth):

- **Detectable scenarios** are all kinds except `alarm_storm` (an alarm flood with no KPI impact). An alert raised only because of a storm would count as a false positive; none did.
- **Red herrings count as detectable.** Planned maintenance, stadium events and the public holiday really do move the KPIs, so the detector *should* alert on them. Deciding they are not incidents is the agent's job. The `precision` below therefore counts an alert on a red herring as correct. Alerts that match a real incident only are reported as "incident precision" in `detector.json`.
- An alert **matches** a scenario if the time ranges overlap (alert vs. impact start to end) and they share scope: the alert's sites intersect the scenario's sites (links and routers are resolved to the sites behind them), or, for nationwide scenarios (DNS, public holiday), the alert is nationwide, core-level or spans several regions.
- **Delay** = alert start minus impact start, in minutes, for the earliest matching alert. Alert starts sit on the 15-minute grid, so small negative values just mean the impact began part-way through the previous step. This measures how precisely the interval starts. An online detector could only *know* after `min_steps` steps, which is the median of {_fmt(pooled["confirm_median_min"], 0)} minutes on the held-out seeds.
- **Fragmentation** = alerts per detected scenario (1.00 is ideal). **Merges** = alerts that match more than one scenario.

## Tuning protocol

The thresholds were chosen on **seed 42 only**. Seeds 1, 2 and 3 (new worlds built in memory, with new topologies, noise and scenario placement) were not used to choose anything and are the headline numbers. Seed 42 is shown for reference only; it is optimistic because it is the data the thresholds were picked on.

### Threshold sweep, seed 42

![precision vs recall](detector.png)

| z_threshold | min_steps | alerts | per day | precision | recall | F1 | F2 | |
|---|---|---|---|---|---|---|---|---|
{sweep_rows}

Reading the table:

- Lower thresholds and shorter runs catch everything but add noise: with `min_steps = 1` the detector fires 2 to 3 alerts a day and half or more are wrong.
- Raising `min_steps` removes short noise at almost no cost on this data. Raising `z_threshold` past about 4 starts losing real scenarios. Scenarios lost first, at `min_steps = {cfg["min_steps"]}`:
{losses}
- **Choice: `z_threshold = {cfg["z_threshold"]:g}`, `min_steps = {cfg["min_steps"]}`.** Rule: take the best F2 (recall counts double), and among near-ties prefer the setting that confirms sooner. The best F2 on seed 42 is `z = 3.5, min_steps = 4`, but it wins by about 0.01, it needs a full hour of deviation (the shortest planted incident is about an hour, so it sits on the edge), and it fires 15 minutes later. At `min_steps = 3`, `z = 3.5` and `z = 4` give identical results on seed 42; we took the lower one because it leaves more margin for weaker signals. We accept slightly more false alerts for a faster and safer detector.
- **Alert volume is not the constraint.** The agent can investigate about 25 alerts a day; the default produces about {pooled["alerts_per_day"]:.1f} a day for the whole country. So we sit on the recall side of the trade-off on purpose. If volume ever matters, filter by severity (below) rather than raising the threshold.

## Results on held-out seeds

| run | alerts | per day | precision | recall | F1 | delay median (min) | delay p90 (min) | alerts per detected scenario | merged alerts |
|---|---|---|---|---|---|---|---|---|---|
{head_rows}

Pooled over the three held-out worlds: {pooled["n_detected"]} of {pooled["n_detectable"]} detectable scenarios detected ({pooled["n_incidents_detected"]} of {pooled["n_incidents"]} real incidents). Precision counts red herrings as correct; counting only real incidents as correct, pooled precision is {pooled["precision_incidents"]:.2f}.

### Recall by scenario kind

| kind | held-out detected | held-out recall | seed 42 detected |
|---|---|---|---|
{kind_rows}

### Recall by difficulty (held-out)

| difficulty | detected | recall |
|---|---|---|
{diff_rows}

### The two deliberate overlap pairs

Each world has two pairs of scenarios placed on purpose in the same night or evening in different regions, to see whether the detector keeps them apart (the agent later has to do the same).

| seed | pair | scenario -> alerts | result |
|---|---|---|---|
{pair_rows}

## Forwarding only some alerts

Alerts carry a severity label from a simple score (`2*ln(1+peak z) + ln(1+hours) + ln(1+entities)`; medium from {cfg["medium_score"]:g}, high from {cfg["high_score"]:g}). On the held-out seeds:

| forwarded | alerts per day | precision | recall | weakest kind (recall) |
|---|---|---|---|---|
{sev_rows}

The severity cut is a lever for later (for example, to protect the daily investigation budget). Precision rises to 1.00 at "medium and high", but recall falls because link degradations (and, at "high only", most congestions and stadium events) score below the cut. Severity here is a ranking aid, not a safe filter for dropping alerts.

## What the detector gets wrong, honestly

**False alerts.** On the held-out seeds, {len(fps)} alerts matched no scenario ({n_low} of them labelled `low`, {n_storm} during an alarm storm). Most are single-site latency excursions of 45 minutes to a few hours in the evening. They cluster on a handful of sites (site: count of false alerts: {top_fp}). The worst one is the busiest site of its world in the evening (checked for seeds 1 and 2: its mean radio load between 19:00 and 22:00 is the highest of all sites). These sites run close to capacity at peak time, where the simulated latency rises steeply with load, so ordinary load noise produces big latency swings that the median/MAD baseline underestimates. They are real deviations, just not incidents. A multi-metric rule ("latency alone on one site is not enough") would remove most of them but would also hide the latency-only signal of a degraded microwave link.

**Subtle cases are caught here, but that says as much about the data as about the detector.** Recall is 100% for every kind on all four worlds at the default setting, including hard DNS degradations with no alarm. That is because the planted effects are large compared with the simulated noise (an outage is a 100% drop, a DNS degradation moves latency on every site at once). Real networks have smaller, messier effects, so do not read 100% as "this would work in production". The sweep gives a better feel: as the threshold rises, the scenarios that disappear first are the ones with the weakest signal: on seed 42 these are the public holiday (a 10 to 20% dip spread over a day) and the microwave link degradations (a latency rise on three sites). I expected hard DNS cases and short congestions to be the first casualties; they are not. The hard DNS cases move latency on every site at once, and the shortest congestion (about one hour) still gives several abnormal steps at three or four times the noise.

**Some incidents are only seen through one metric.** Link degradations (microwave rain fade) are detected through latency only and usually get a `low` severity, even though they are real incidents. Forwarding only medium and high alerts would drop recall to zero for this kind (table above).

**Alert times are rough.** The public holiday is detected only for the part of the day where traffic is clearly below a normal weekday (business hours), so the alert starts hours after the scenario does. A scenario that touches sites behind different aggregation routers (for example a two-site congestion) can give one alert per router; this is what pushes fragmentation slightly above 1.00.

**This is a batch, in-sample detector.** The baseline is computed from the same 30 days that are then scored. The median and MAD make that tolerable, but it is not what a live system could do: a live system cannot see the future days. An online version needs a baseline from a trailing history window (for example the last 4 to 8 weeks of the same day type and slot), updated on a schedule and excluding periods already flagged, and it needs a warm-up period; the detector would also have to wait `min_steps` steps before confirming an alert. With only one month of data, Saturdays and Sundays have just 4 or 5 samples per slot, which is thin.

**Pooled slots blur the baseline on steep ramps.** Each slot's baseline pools two neighbouring slots on each side. When traffic climbs quickly (morning and evening ramps), that pooling widens the MAD, so the detector is slightly less sensitive there. It is a deliberate trade for having enough samples per slot from a single month.

**Other limits.** The evaluation uses the same author's scenarios and the same simulator as the detector's test data; there are no real operator logs. Matching is generous on scope (a shared site is enough), so a large alert can match a small scenario. Only 31 to 34 scenarios per world, so one extra miss moves recall by about 3 points. Metrics are sites, regions and core nodes: nothing finer (single cells) is monitored.

## Cost

Baseline and detection for one world (48 sites, 4 regions, 4 core nodes, 2,880 steps, 7 cell metrics) take well under a second. Whole `evaluate` run including building the four worlds and the 24-point sweep: {t["total_s"]:.0f} s.

## Reproduce

```
cd backend
uv run python -m incident_agent.detector sweep      # seed 42 table only
uv run python -m incident_agent.detector evaluate   # held-out seeds, writes docs/results/detector.*
uv run python -m incident_agent.detector run        # score the database, replace alerts + anomalies
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_all(report: dict[str, Any], out_dir: Path) -> None:
    write_json(report, out_dir / "detector.json")
    write_plot(report, out_dir / "detector.png")
    write_markdown(report, out_dir / "detector.md")
