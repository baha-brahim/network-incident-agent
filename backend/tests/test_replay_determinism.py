"""What keeps the recorded prompts byte-identical on every machine, and what the cassettes hold.

The response cache keys on the exact text of each prompt, so anything platform-dependent in a
prompt turns into a replay failure on another operating system. These tests pin the parts of that
which can be checked without a database.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from incident_agent.agent.tools.common import num, pct
from incident_agent.config import REPO_ROOT

CASSETTES = REPO_ROOT / "evals" / "cassettes"


def test_numbers_never_print_a_negative_zero() -> None:
    assert num(-0.0) == "0"
    assert num(-1e-12) == "0"
    assert num(-0.004) == "0"
    assert num(-0.006) == "-0.01"
    assert pct(-1e-12) == "+0%"
    assert pct(-0.4) == "+0%"
    assert pct(-0.6) == "-1%"
    assert pct(12.0) == "+12%"


@pytest.mark.parametrize(
    ("exact", "noisy"),
    [
        (12.25, 12.250000000000002),  # a tie at one decimal
        (12.25, 12.249999999999998),
        (0.125, 0.12500000000000003),  # a tie at two decimals
        (150.5, 150.50000000000003),  # a tie at zero decimals
        (99.4, 99.39999999999999),
    ],
)
def test_last_bit_noise_does_not_change_a_number(exact: float, noisy: float) -> None:
    assert num(noisy) == num(exact)
    assert pct(noisy) == pct(exact)


@pytest.mark.parametrize("zone", ["Pacific/Auckland", "America/Los_Angeles"])
def test_local_time_does_not_depend_on_the_machine_time_zone(zone: str) -> None:
    code = (
        "from datetime import UTC, datetime;"
        "from incident_agent.agent.tools.timeutil import fmt, to_local;"
        "t = datetime(2026, 9, 3, 6, 0, tzinfo=UTC);"
        "print(fmt(t), to_local(t).strftime('%A'))"
    )
    env = {"PATH": "", "TZ": zone, "LC_ALL": "fr_FR.UTF-8", "SYSTEMROOT": "C:\\Windows"}
    run = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert run.stdout.strip() == "2026-09-03 07:00 Thursday"


def _cassette_files() -> list[Path]:
    return sorted(CASSETTES.glob("*/*.json"))


def test_cassettes_are_present_and_readable() -> None:
    files = _cassette_files()
    assert files, "no recordings under evals/cassettes; see evals/cassettes/README.md"
    for file in files:
        entry = json.loads(file.read_text(encoding="utf-8"))
        assert file.stem == entry["key"][:24]
        assert {"key", "request", "response", "usage"} <= set(entry)
        assert [a["status"] for a in entry["usage"]["attempts"]] == ["ok"]


def test_cassettes_use_unix_line_endings_and_hold_no_credentials() -> None:
    secret = re.compile(
        r"AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z]{20,}|Bearer\s+\S{12,}"
        r"|api[_-]?key|x-goog|authorization",
        re.IGNORECASE,
    )
    for file in _cassette_files():
        raw = file.read_bytes()
        assert b"\r" not in raw, f"{file.name} has Windows line endings"
        assert not secret.search(raw.decode("utf-8")), f"{file.name} looks like it holds a secret"
