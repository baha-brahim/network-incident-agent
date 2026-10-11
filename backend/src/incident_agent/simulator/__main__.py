"""CLI: python -m incident_agent.simulator {build,plots}."""

import argparse
import time
from pathlib import Path

from incident_agent.simulator.build import build_world
from incident_agent.simulator.config import PROFILES
from incident_agent.simulator.io import read_world, write_world


def _dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def _cmd_build(args: argparse.Namespace) -> None:
    t0 = time.perf_counter()
    world = build_world(seed=args.seed, profile=args.profile)
    t_build = time.perf_counter() - t0
    out = Path(args.out)
    write_world(world, out)
    t_total = time.perf_counter() - t0
    print(f"built in {t_build:.1f}s, written in {t_total - t_build:.1f}s -> {out}")
    for name, df in world.tables().items():
        print(f"  {name:16s} {len(df):>9,d} rows")
    print(f"on-disk size: {_dir_size_mb(out):.1f} MB")
    if args.load:
        from incident_agent.db.loader import load_world

        load_world(world)
        print("loaded into Postgres")


def _cmd_plots(args: argparse.Namespace) -> None:
    from incident_agent.simulator.plots import make_plots

    data = Path(args.data)
    out = Path(args.out) if args.out else data / "plots"
    make_plots(read_world(data), out)
    print(f"plots written to {out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="generate the synthetic world")
    b.add_argument("--seed", type=int, default=42)
    b.add_argument(
        "--profile",
        choices=PROFILES,
        default="default",
        help="scenario profile: the default world, or the hard one (scenarios built around traps)",
    )
    b.add_argument("--out", required=True, help="output directory")
    b.add_argument("--load", action="store_true", help="also load into Postgres")
    b.set_defaults(func=_cmd_build)
    p = sub.add_parser("plots", help="render sanity-check plots")
    p.add_argument("--data", required=True, help="directory written by `build`")
    p.add_argument("--out", default=None, help="default: <data>/plots")
    p.set_defaults(func=_cmd_plots)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
