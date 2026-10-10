"""Command line: `python -m incident_agent.evals <command>`.

Each command group lives in its own module and registers itself here:
`cli_harness` (prepare, run, score, report) and `cli_grading` (grade, human-pack, agreement).
"""

import argparse
import sys

from incident_agent.evals import cli_grading, cli_harness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m incident_agent.evals")
    sub = parser.add_subparsers(dest="command", required=True)
    cli_harness.add_commands(sub)
    cli_grading.add_commands(sub)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
