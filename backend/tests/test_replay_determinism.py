"""What keeps the recorded prompts byte-identical on every machine, and what the cassettes hold.

The response cache keys on the exact text of each prompt, so anything platform-dependent in a
prompt turns into a replay failure on another operating system. These tests pin the parts of that
which can be checked without a database.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from incident_agent.agent import prompts
from incident_agent.agent.report import Report
from incident_agent.agent.tools.common import num, pct
from incident_agent.agent.tools.registry import tool_schemas
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


# --- what the model is sent does not depend on the process ------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def serialised_parts() -> dict[str, str]:
    """Digests of the fixed text and schemas that go into every recorded request, in the order
    they are sent (nothing is sorted here: the order is part of the bytes)."""
    return {
        "tool_schemas": _digest(json.dumps(tool_schemas())),
        "report_schema": _digest(json.dumps(Report.model_json_schema())),
        "intake_prompt": _digest(prompts.INTAKE_SYSTEM),
        "investigate_prompt": _digest(prompts.investigate_system()),
        "conclude_prompt": _digest(prompts.CONCLUDE_SYSTEM),
    }


# Changing a tool definition, the report schema or a prompt on purpose changes a digest and makes
# the replay test miss every recording. Update the digest here and re-record the cassettes:
# `uv run pytest -m db tests/test_replay.py` with REPLAY_RECORD=1 (see evals/cassettes/README.md).
PINNED_DIGESTS = {
    "tool_schemas": "52660f1f063193f8917d3ac3db3e328cd8386dc30833d82d3aa9ea17b0da9bb6",
    "report_schema": "12ec2c08410a291f92cf4870d331a9ddb807dbd4d8224fca6bb0b1a15203f81d",
    "intake_prompt": "d2f9e748bf6d3ac2fbecbf89eadd452577bcd798212445becdbc6e087e4cb1ea",
    "investigate_prompt": "25727ac41bafdf63109cce00e97a6af97e8fde9e9cc32bdf3f7a27818d982116",
    "conclude_prompt": "bedaf65b84806d7a57803459e92a907394cafc8683d2b27301e21d1268ae594e",
}


def test_the_serialised_request_parts_are_the_recorded_ones() -> None:
    changed = sorted(k for k, v in serialised_parts().items() if PINNED_DIGESTS[k] != v)
    assert not changed, (
        f"{changed} no longer match the pinned digests. If the change is on purpose, update "
        "PINNED_DIGESTS and re-record evals/cassettes (REPLAY_RECORD=1, see "
        "evals/cassettes/README.md). If it is not, something in tool definitions, the report "
        "schema or the prompts now depends on the machine or the process."
    )


@pytest.mark.parametrize("seed", ["0", "12345"])
def test_the_serialised_request_parts_do_not_depend_on_the_hash_seed(seed: str) -> None:
    code = (
        "import json;"
        "from tests.test_replay_determinism import serialised_parts;"
        "print(json.dumps(serialised_parts()))"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    run = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert json.loads(run.stdout) == serialised_parts()
