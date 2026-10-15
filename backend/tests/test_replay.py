"""Complete investigations replayed from recorded model responses: no API key, no network.

Three questions run through the real agent (intake, tools, case file, report, verification) on
the fixture world. The model's answers come from the recordings in `evals/cassettes/<case>/`;
everything else runs for real against Postgres. The test fails, with the command to re-record,
when a prompt or a tool result is no longer the one that was recorded.

Recording (live calls to the primary model, one cassette directory per case):

    REPLAY_RECORD=1 uv run pytest -m db tests/test_replay.py            # bash
    $env:REPLAY_RECORD='1'; uv run pytest -m db tests/test_replay.py    # PowerShell
"""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from incident_agent.agent import investigate
from incident_agent.agent.reference import Reference
from incident_agent.agent.report import all_refs
from incident_agent.agent.state import RunResult
from incident_agent.agent.types import ToolContext
from incident_agent.config import REPO_ROOT, Settings, get_settings
from incident_agent.db.loader import load_world
from incident_agent.detector.store import run_detector
from incident_agent.llm.cache import ResponseCache
from incident_agent.llm.runner import LLMRunner
from incident_agent.llm.types import CacheMiss, LLMError
from incident_agent.rag import HashEmbedder
from incident_agent.rag.ingest import ingest, vector_literal
from tests.fixtures_world import at, make_fixture_world

pytestmark = pytest.mark.db

CASSETTES = REPO_ROOT / "evals" / "cassettes"
EMB = HashEmbedder()

RECORD_BASH = "REPLAY_RECORD=1 uv run pytest -m db tests/test_replay.py"
RECORD_POWERSHELL = "$env:REPLAY_RECORD='1'; uv run pytest -m db tests/test_replay.py"

# `clean_env` removes the key from the environment before each test; keep what the shell had.
_SHELL_GEMINI_KEY = os.environ.get("GEMINI_API_KEY")


@dataclass(frozen=True)
class Case:
    """A question, and what the fixture world says the right answer is."""

    id: str
    question: str
    asked_at: datetime
    classification: str
    category: str
    root_node: str
    must_cite: tuple[str, ...] = ()
    # Set when the recorded run gets the category wrong. `category` stays the true one; the
    # strict xfail test below passes, and so fails the suite, once a re-recording gets it right.
    known_miss: str = ""


# The fixture window starts on Tuesday 2026-09-01 (Africa/Tunis). All three are asked on the
# morning of Thursday 2026-09-03, so the events they ask about have already ended.
CASES = [
    # A clear incident: LNK-TUN-01-A is cut on Wednesday evening, its two sites go dark.
    Case(
        id="fiber-cut",
        question=(
            "Sites S-TUN-001 and S-TUN-002 in Tunis lost all service for a few hours yesterday "
            "evening. What happened?"
        ),
        asked_at=at(2, 9),
        classification="incident",
        category="transport_failure",
        root_node="LNK-TUN-01-A",
        must_cite=("ALM-000001",),
    ),
    # A red herring: the site was down because of a planned battery swap.
    Case(
        id="planned-maintenance",
        question=(
            "Site S-SFX-001 in Sfax dropped off the air in the early hours of this morning. "
            "Is this an outage we need to escalate?"
        ),
        asked_at=at(2, 9),
        classification="planned_maintenance",
        category="planned_maintenance",
        root_node="S-SFX-001",
        must_cite=("MW-0001",),
    ),
    # The harder one: nationwide, no site is down, and a harmless software upgrade on the same
    # node an hour earlier looks like the culprit. The first report blames that change; the
    # timing check of the verify step refutes it and the corrected report names the DNS fault.
    Case(
        id="dns-degradation",
        question=(
            "Customers in Tunis and Sfax complained yesterday around lunchtime that web pages "
            "and apps would not load, even though their phones showed full signal. "
            "What was going on?"
        ),
        asked_at=at(2, 9),
        classification="incident",
        category="core_degradation",
        root_node="CORE-DNS-01",
        must_cite=("ALR-0001",),
    ),
]


# --- recording and replaying ------------------------------------------------------------------


def recording() -> bool:
    return os.environ.get("REPLAY_RECORD") == "1"


class _Stopped(BaseException):
    """Ends an investigation at the first model call that cannot be answered.

    Deliberately not an `Exception`: the agent turns those into a step with an error and carries
    on, which would hide the first problem behind a string of follow-ups.
    """

    def __init__(self, error: LLMError) -> None:
        super().__init__(str(error))
        self.error = error


class _Guard:
    """Wraps the runner: any failed call (a cache miss, or a provider error) stops the case."""

    def __init__(self, inner: LLMRunner) -> None:
        self.inner = inner

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        try:
            return self.inner.invoke(messages, **kwargs)
        except LLMError as exc:
            raise _Stopped(exc) from exc


class _UsedFiles(ResponseCache):
    """Remembers which cassette files an investigation read or wrote."""

    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.used: set[str] = set()

    def path(self, key: str) -> Path:
        path = super().path(key)
        self.used.add(path.name)
        return path


def _recorded_model_specs(directory: Path) -> set[str]:
    specs = set()
    for file in sorted(directory.glob("*.json")):
        usage = json.loads(file.read_text(encoding="utf-8"))["usage"]
        specs.add(f"{usage['provider']}:{usage['model']}")
    return specs


def build_runner(case: Case) -> tuple[_Guard, _UsedFiles]:
    """A runner on the primary model only, reading (and when recording, writing) the cassette."""
    directory = CASSETTES / case.id
    if recording():
        settings = Settings(llm_cache_mode="readwrite", llm_cache_dir=directory)
        primary = settings.agent_model
        other = _recorded_model_specs(directory) - {primary}
        if other:
            pytest.fail(
                f"{directory} holds responses from {sorted(other)}, not from {primary}. A "
                "cassette never mixes models: delete the directory and record it again."
            )
        runner = LLMRunner("agent", chain=[primary], settings=settings, cache_mode="readwrite")
    else:
        settings = Settings(_env_file=None, llm_cache_mode="replay", llm_cache_dir=directory)
        runner = LLMRunner(
            "agent",
            chain=[settings.agent_model],
            settings=settings,
            cache_mode="replay",
            min_interval_seconds=0.0,
        )
    tracker = _UsedFiles(directory)
    runner.cache = tracker
    return _Guard(runner), tracker


def stale_message(case: Case, error: LLMError) -> str:
    if isinstance(error, CacheMiss):
        return (
            f"Replay of case {case.id!r} found no recorded model response:\n  {error}\n\n"
            "The prompts or the tool output changed since evals/cassettes/"
            f"{case.id}/ was recorded. That is expected after editing a prompt, a tool, the "
            "fixture world or the runbooks. If only CI fails, a prompt differs between "
            "machines (formatting, ordering, time zone): fix that instead of re-recording.\n\n"
            "To re-record (live calls to the primary model, about 20 for all cases; needs "
            "GEMINI_API_KEY in .env), run from backend/ and commit evals/cassettes/:\n"
            f"  bash:       {RECORD_BASH}\n"
            f"  PowerShell: {RECORD_POWERSHELL}"
        )
    return (
        f"Recording case {case.id!r} stopped at a failed model call:\n  {error}\n\n"
        "Responses already recorded are kept. If this is a rate limit, wait a minute and run "
        f"the same command again; it continues where it stopped:\n  {RECORD_BASH}"
    )


def run_case(case: Case, engine: Engine) -> RunResult:
    """Run the investigation of `case` on the fixture world."""
    runner, tracker = build_runner(case)
    ctx = ToolContext(engine=engine, asked_at=case.asked_at, embedder=EMB)
    stopped: LLMError | None = None
    try:
        result = investigate(
            case.question,
            case.asked_at,
            runner=runner,
            ctx=ctx,
            store=None,
            reference=Reference.load(engine),
        )
    except _Stopped as stop:
        stopped = stop.error
    if stopped is not None:  # outside the handler, so the report is not buried in chained errors
        pytest.fail(stale_message(case, stopped), pytrace=False)
    if recording():
        for file in (CASSETTES / case.id).glob("*.json"):
            if file.name not in tracker.used:  # a recording the investigation no longer asks for
                file.unlink()
            else:  # the cache writes the platform's line endings; the repository keeps LF
                file.write_bytes(file.read_bytes().replace(b"\r\n", b"\n"))
    return result


# --- the database -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def replay_world(db_engine: Engine, agent_ro_engine: Engine) -> Iterator[Engine]:
    """The fixture world with the detector's output and the runbooks, all deterministic.

    The detector runs on the loaded data, and the runbooks are embedded with the hashing
    embedder, so the same inputs give the same rows on every machine.
    """
    load_world(make_fixture_world(), db_engine)
    run_detector(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM runbook_docs"))  # no vectors from an earlier test survive
    ingest(engine=db_engine, embedder=EMB)
    yield agent_ro_engine
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM anomalies"))
        conn.execute(text("DELETE FROM alerts"))


@pytest.fixture(autouse=True)
def provider_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay never builds a chat model, so it can never reach a provider. Recording can."""
    if recording():
        if _SHELL_GEMINI_KEY:  # `clean_env` removed it; the model factory reads the environment
            monkeypatch.setenv("GEMINI_API_KEY", _SHELL_GEMINI_KEY)
            get_settings.cache_clear()
        return

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("replay mode tried to create a chat model")

    monkeypatch.setattr("incident_agent.llm.runner.make_chat_model", refuse)


# --- the tests --------------------------------------------------------------------------------


def citation_issues(result: RunResult) -> list[str]:
    return [i for i in result.issues if "reference" in i.lower() or i.startswith("unresolved")]


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_investigation_replays_to_the_expected_outcome(case: Case, replay_world: Engine) -> None:
    result = run_case(case, replay_world)
    report = result.report

    assert result.status == "finished", result.error
    assert [s.error for s in result.steps if s.error] == []
    assert report.classification == case.classification, report.root_cause_summary
    if not case.known_miss:
        assert report.root_cause_category == case.category, report.root_cause_summary
    assert report.root_cause_node_id == case.root_node, report.root_cause_summary

    # Every citation points at evidence the run actually gathered, and none had to be repaired.
    assert citation_issues(result) == [], result.issues
    cited = all_refs(report)
    assert cited, "the report cites nothing"
    assert [r for r in cited if r not in result.evidence] == []
    assert set(case.must_cite) <= set(cited)

    # One model answered everything; the sizes stay within what the agent's limits allow.
    assert len(result.models_used) == 1 and not result.fell_back
    assert 3 <= result.usage.llm_calls <= 9
    assert 4 <= result.usage.tool_calls <= 17
    if not recording():
        assert result.usage.cached_calls == result.usage.llm_calls
        assert result.usage.live_requests == {}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="the recorded answer has the wrong category (see Case.known_miss); when a "
    "re-recording gets it right, remove known_miss from the case",
)
@pytest.mark.parametrize(
    "case", [c for c in CASES if c.known_miss], ids=[c.id for c in CASES if c.known_miss]
)
def test_the_category_of_a_known_miss_is_the_true_one(case: Case, replay_world: Engine) -> None:
    result = run_case(case, replay_world)
    assert result.report.root_cause_category == case.category, case.known_miss


def test_a_changed_prompt_fails_and_says_how_to_re_record(replay_world: Engine) -> None:
    if recording():
        pytest.skip("this test is about replay")
    case = replace(CASES[0], question=CASES[0].question + " Please be brief.")
    with pytest.raises(pytest.fail.Exception) as failure:
        run_case(case, replay_world)
    message = str(failure.value)
    assert "prompts or the tool output changed" in message
    assert RECORD_BASH in message and RECORD_POWERSHELL in message


def test_every_case_has_a_cassette_from_one_model() -> None:
    specs: set[str] = set()
    for case in CASES:
        found = _recorded_model_specs(CASSETTES / case.id)
        assert found, f"no recording for {case.id}: {RECORD_BASH}"
        specs |= found
    assert len(specs) == 1, f"cassettes mix models: {sorted(specs)}"


def recorded_runbook_queries() -> list[str]:
    queries: list[str] = []
    for file in sorted(CASSETTES.glob("*/*.json")):
        response = json.loads(file.read_text(encoding="utf-8"))["response"]
        queries += [
            c["args"]["query"] for c in response["tool_calls"] if c["name"] == "search_runbooks"
        ]
    return queries


def test_recorded_runbook_queries_rank_the_same_on_any_cpu(replay_world: Engine) -> None:
    """Vector distances come from pgvector's float32 code, which can differ in the last bits
    between CPUs. A ranking is safe when no two neighbours in the candidate list are that close
    (exact ties are broken by chunk id)."""
    queries = recorded_runbook_queries()
    assert queries, "no cassette searches the runbooks"
    sql = text(
        "SELECT embedding <=> CAST(:v AS vector) AS d FROM runbook_chunks "
        "ORDER BY d, chunk_id LIMIT 21"  # 20 candidates, plus the first one left out
    )
    with replay_world.connect() as conn:
        for query in queries:
            d = [r.d for r in conn.execute(sql, {"v": vector_literal(EMB.embed_query(query))})]
            gaps = [b - a for a, b in pairwise(d)]
            assert min(gaps) > 1e-6, f"near-tie in the ranking for {query!r}"
