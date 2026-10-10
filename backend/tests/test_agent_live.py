"""Live investigation across providers (`pytest -m llm tests/test_agent_live.py`).

Uses free-tier quota of all three providers (about 4 Gemini requests) and about 3 minutes, because
the local model is slow. It runs on the small fixture world in the test database.
"""

from collections.abc import Iterator

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine

from incident_agent.agent import AgentConfig, investigate
from incident_agent.agent.reference import Reference
from incident_agent.agent.state import AgentEvent, RunResult
from incident_agent.agent.store import TraceStore
from incident_agent.agent.types import ToolContext
from incident_agent.config import get_settings
from incident_agent.llm.runner import LLMRunner, MessagesInput, Runner, ToolSchemas
from incident_agent.llm.types import LLMResult
from tests.fixtures_world import at
from tests.test_agent_db import setup_world
from tests.test_tools_db import EMB

pytestmark = pytest.mark.llm


@pytest.fixture(scope="module")
def world(db_engine: Engine) -> Iterator[Engine]:
    yield from setup_world(db_engine)


QUESTION = "TEST: Why did the sites S-TUN-001 and S-TUN-002 lose service this evening?"
ASKED = at(1, 23.5)  # after the cut (day 1, 18:00 to 22:00) has been repaired

GEMINI = "gemini:gemini-3.5-flash-lite"
GROQ = "groq:openai/gpt-oss-120b"
OLLAMA = "ollama:qwen3:4b"


def _need_keys() -> None:
    settings = get_settings()
    if settings.gemini_api_key is None or settings.groq_api_key is None:
        pytest.skip("GEMINI_API_KEY and GROQ_API_KEY are needed")


def _run(world: Engine, agent_ro_engine: Engine, runner: Runner, **kw: object) -> RunResult:
    events: list[AgentEvent] = []
    result = investigate(
        QUESTION,
        ASKED,
        runner=runner,
        ctx=ToolContext(engine=agent_ro_engine, asked_at=ASKED, embedder=EMB),
        store=TraceStore(world),
        reference=Reference.load(agent_ro_engine),
        on_event=events.append,
        **kw,  # type: ignore[arg-type]
    )
    assert events[0].type == "run_started" and events[-1].type == "run_finished"
    return result


def _assert_valid(result: RunResult) -> None:
    assert result.status == "finished", result.error
    assert not [i for i in result.issues if i.startswith("unresolved")], result.issues
    report = result.report
    assert report.findings and all(f.refs for f in report.findings)
    assert all(ref in result.evidence for f in report.findings for ref in f.refs)
    assert report.classification == "incident"
    assert report.root_cause_category == "transport_failure"
    assert report.root_cause_node_id == "LNK-TUN-01-A"


class ProviderPlan:
    """Wraps a runner and sends each call to the provider planned for its purpose.

    Structured steps (intake, report) go to the hosted models: the local 4B model spends its output
    budget thinking and often cannot finish a JSON object. Tool-calling turns rotate through all
    three providers. The other models stay in the chain as fallbacks, so a provider that fails a
    step shows up as `fell_back` instead of ending the run.
    """

    TURNS = (GROQ, OLLAMA, GEMINI, OLLAMA, GROQ, OLLAMA)

    def __init__(self, inner: LLMRunner) -> None:
        self.inner = inner

    def planned(self, purpose: str) -> str:
        if purpose.startswith("investigate turn "):
            return self.TURNS[(int(purpose.rsplit(" ", 1)[1]) - 1) % len(self.TURNS)]
        return GEMINI

    def invoke(
        self,
        messages: MessagesInput,
        *,
        tools: ToolSchemas | None = None,
        schema: type[BaseModel] | None = None,
        purpose: str = "",
    ) -> LLMResult:
        first = self.planned(purpose)
        order = [first, *[s for s in (GEMINI, GROQ, OLLAMA) if s != first]]
        self.inner.route = lambda _index: order
        return self.inner.invoke(messages, tools=tools, schema=schema, purpose=purpose)


def test_forced_provider_switch_in_one_investigation(
    world: Engine,
    agent_ro_engine: Engine,
) -> None:
    """Gemini, Groq, Ollama, Gemini, ... answer consecutive steps of one investigation.

    The case file is plain text, so no provider needs the others' message formats or signatures.
    """
    _need_keys()
    inner = LLMRunner(
        "agent",
        chain=[GEMINI, GROQ, OLLAMA],
        route=lambda _index: [GEMINI],
        cache_mode="off",  # a cached answer would not prove that the provider could answer
    )
    plan = ProviderPlan(inner)
    result = _run(world, agent_ro_engine, plan, config=AgentConfig(max_iterations=4))
    for n, step in enumerate(result.steps):
        answered = f"{step.provider}:{step.model}"
        print(n, step.purpose, "planned", plan.planned(step.purpose), "answered", answered)
        for attempt in step.attempts:
            print("    ", attempt[:300])
    _assert_valid(result)
    for step in result.steps:
        planned = plan.planned(step.purpose)
        if not step.error and f"{step.provider}:{step.model}" != planned:
            # a step may only leave its planned provider because that provider failed it
            assert any(a.startswith(planned) and "error" in a for a in step.attempts), step.attempts
    turns = [s for s in result.steps if s.node == "investigate" and not s.error]
    assert {f"{s.provider}:{s.model}" for s in turns} >= {GROQ, OLLAMA}, [
        (s.purpose, s.attempts) for s in turns
    ]
    assert {GEMINI, GROQ, OLLAMA} <= set(result.models_used)
