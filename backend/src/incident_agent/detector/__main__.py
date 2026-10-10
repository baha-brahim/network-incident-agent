"""CLI: python -m incident_agent.detector {run,evaluate,sweep}."""

import argparse
import time
from pathlib import Path

from incident_agent.config import REPO_ROOT
from incident_agent.detector.config import DetectorConfig

DEFAULT_OUT = REPO_ROOT / "docs" / "results"


def _cmd_run(args: argparse.Namespace) -> None:
    from incident_agent.detector.store import run_detector

    t0 = time.perf_counter()
    result, counts = run_detector()
    print(
        f"detected in {time.perf_counter() - t0:.1f}s: {counts['alerts']} alerts, "
        f"{counts['anomalies']} anomalies written"
    )
    if len(result.alerts):
        print(result.alerts["severity"].value_counts().to_string())


def _cmd_sweep(args: argparse.Namespace) -> None:
    from incident_agent.detector.evaluate import prepare_world
    from incident_agent.detector.report import TUNE_SEED, run_sweep, sweep_table
    from incident_agent.simulator.build import build_world

    cfg = DetectorConfig()
    t0 = time.perf_counter()
    pw = prepare_world(build_world(TUNE_SEED), TUNE_SEED, cfg)
    rows = run_sweep(pw, cfg)
    print(f"sweep on seed {TUNE_SEED} ({len(rows)} configs, {time.perf_counter() - t0:.1f}s)")
    print(sweep_table(rows, cfg))


def _cmd_evaluate(args: argparse.Namespace) -> None:
    from incident_agent.detector.report import run_evaluation, write_all

    cfg = DetectorConfig()
    report = run_evaluation(cfg, held_out=tuple(args.seeds))
    out = Path(args.out)
    write_all(report, out)
    p = report["held_out_pooled"]
    print(
        f"held-out seeds {report['held_out_seeds']} at z={cfg.z_threshold:g}, "
        f"min_steps={cfg.min_steps}:"
    )
    print(
        f"  precision {p['precision']:.3f}  recall {p['recall']:.3f}  F1 {p['f1']:.3f}  "
        f"alerts/day {p['alerts_per_day']:.1f}"
    )
    print(f"  total time {report['timings_s']['total_s']:.1f}s; wrote {out}/detector.(md|json|png)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.detector")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="read KPIs from Postgres, replace anomalies + alerts").set_defaults(
        func=_cmd_run
    )
    sub.add_parser("sweep", help="threshold sweep on seed 42").set_defaults(func=_cmd_sweep)
    e = sub.add_parser("evaluate", help="held-out evaluation; writes docs/results/detector.*")
    e.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    e.add_argument("--out", default=str(DEFAULT_OUT))
    e.set_defaults(func=_cmd_evaluate)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
