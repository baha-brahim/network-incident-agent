import json
from pathlib import Path
from typing import Any, Literal

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from incident_agent.config import Settings
from incident_agent.llm.cache import cache_key, request_description
from incident_agent.llm.errors import DAILY_QUOTA_COOLDOWN, classify, scrub
from incident_agent.llm.runner import (
    ChainEntry,
    LLMRunner,
    _tool_calls,
    build_model_kwargs,
)
from incident_agent.llm.testing import FakeChatModel, ai
from incident_agent.llm.types import AllModelsFailed, CacheMiss, ToolCall

MSGS = [("system", "You are an analyst."), ("human", "Why did traffic drop in Sfax?")]
TOOLS = [
    {
        "name": "get_alarms",
        "description": "List alarms.",
        "parameters": {"type": "object", "properties": {"start": {"type": "string"}}},
    }
]


class Verdict(BaseModel):
    cause: Literal["fiber", "power"]
    node: str | None = None


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class RateLimitError(Exception):
    status_code = 429


def entry(spec: str, *script: Any) -> ChainEntry:
    return ChainEntry(spec, FakeChatModel(script=list(script)))


def runner(
    *chain: ChainEntry | str, tmp_path: Path, clock: FakeClock | None = None, **kwargs: Any
) -> LLMRunner:
    clock = clock or FakeClock()
    kwargs.setdefault("min_interval_seconds", 0.0)
    kwargs.setdefault("cache_mode", "off")
    return LLMRunner(
        chain=list(chain),
        settings=Settings(_env_file=None, llm_cache_dir=tmp_path / "cache"),
        clock=clock.now,
        sleep=clock.sleep,
        **kwargs,
    )


# --- fallback -----------------------------------------------------------------------------------


def test_first_model_answers(tmp_path: Path) -> None:
    r = runner(entry("gemini:a", ai("hello", input_tokens=12, output_tokens=3)), tmp_path=tmp_path)
    result = r.invoke(MSGS)
    assert result.text == "hello"
    u = result.usage
    assert (u.provider, u.model, u.input_tokens, u.output_tokens) == ("gemini", "a", 12, 3)
    assert not u.fell_back
    assert [(a.model, a.status) for a in u.attempts] == [("gemini:a", "ok")]


def test_fallback_order_and_attempt_records(tmp_path: Path) -> None:
    r = runner(
        entry("gemini:a", RuntimeError("503 overloaded")),
        entry("groq:b", ValueError("bad request")),
        entry("ollama:c", ai("from c")),
        entry("gemini:d", ai("never")),
        tmp_path=tmp_path,
    )
    result = r.invoke(MSGS)
    assert result.text == "from c"
    assert (result.usage.provider, result.usage.model, result.usage.fell_back) == (
        "ollama",
        "c",
        True,
    )
    got = [(a.model, a.status) for a in result.usage.attempts]
    assert got == [("gemini:a", "error"), ("groq:b", "error"), ("ollama:c", "ok")]
    assert "503 overloaded" in (result.usage.attempts[0].error or "")


def test_all_fail_raises_one_error_listing_attempts(tmp_path: Path) -> None:
    r = runner(
        entry("gemini:a", RuntimeError("boom a")),
        entry("groq:b", RuntimeError("boom b")),
        tmp_path=tmp_path,
    )
    with pytest.raises(AllModelsFailed) as info:
        r.invoke(MSGS)
    assert "boom a" in str(info.value) and "boom b" in str(info.value)
    assert [a.model for a in info.value.attempts] == ["gemini:a", "groq:b"]


def test_route_forces_a_model_per_call(tmp_path: Path) -> None:
    a, b = entry("gemini:a", ai("A1"), ai("A2")), entry("groq:b", ai("B1"))
    order = [["gemini:a"], ["groq:b", "gemini:a"], ["gemini:a"]]
    r = runner(a, b, tmp_path=tmp_path, route=lambda i: order[i])
    assert [r.invoke(MSGS).usage.model for _ in range(3)] == ["a", "b", "a"]


# --- cooldown -----------------------------------------------------------------------------------


def test_rate_limit_cooldown_uses_hint_then_expires(tmp_path: Path) -> None:
    clock = FakeClock()
    err = RateLimitError("429 RESOURCE_EXHAUSTED. Please retry in 20.0s")
    a = entry("gemini:a", err, ai("A back"))
    r = runner(a, entry("groq:b", ai("B1"), ai("B2"), ai("B3")), tmp_path=tmp_path, clock=clock)
    assert r.invoke(MSGS).text == "B1"  # a fails, b answers
    second = r.invoke(MSGS)
    assert second.text == "B2"
    assert second.usage.attempts[0].status == "skipped"
    assert "cooling down" in (second.usage.attempts[0].error or "")
    clock.t += 22  # hint 20 s + 1 s margin has passed
    assert r.invoke(MSGS).text == "A back"


def test_rate_limit_without_hint_waits_60s(tmp_path: Path) -> None:
    clock = FakeClock()
    r = runner(
        entry("gemini:a", RateLimitError("too many requests"), ai("A")),
        entry("groq:b", ai("B1"), ai("B2")),
        tmp_path=tmp_path,
        clock=clock,
    )
    r.invoke(MSGS)
    clock.t += 50
    assert r.invoke(MSGS).text == "B2"
    clock.t += 15
    assert r.invoke(MSGS).text == "A"


def test_classify_variants() -> None:
    assert classify(RateLimitError("x")).cooldown == 60
    assert classify(
        RuntimeError("Rate limit reached ... Please try again in 1m2.5s")
    ).cooldown == pytest.approx(63.5)
    assert classify(RuntimeError("429 ... try again in 850ms")).cooldown == pytest.approx(1.85)
    daily = (
        "429 quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier. Please retry in 5s"
    )
    assert classify(RuntimeError(daily)).cooldown == DAILY_QUOTA_COOLDOWN
    assert classify(RuntimeError("503 Service Unavailable")).kind == "transient"
    assert classify(TimeoutError("read timed out")).kind == "transient"
    assert classify(ValueError("bad schema")).cooldown == 0


# --- size-aware skipping ------------------------------------------------------------------------


def test_groq_skipped_when_request_too_large(tmp_path: Path) -> None:
    big = [("system", "s"), ("human", "x" * 30_000)]  # ~8.5k tokens
    groq = entry("groq:b", ai("never"))
    r = runner(
        entry("gemini:a", RuntimeError("down")), groq, entry("gemini:c", ai("C")), tmp_path=tmp_path
    )
    result = r.invoke(big)
    assert result.text == "C"
    statuses = [(a.model, a.status) for a in result.usage.attempts]
    assert statuses == [("gemini:a", "error"), ("groq:b", "skipped"), ("gemini:c", "ok")]
    assert "request too large" in (result.usage.attempts[1].error or "")
    assert isinstance(groq.model, FakeChatModel) and groq.model.seen == []


def test_small_request_goes_to_groq(tmp_path: Path) -> None:
    r = runner(entry("groq:b", ai("B")), tmp_path=tmp_path)
    assert r.invoke(MSGS).text == "B"


# --- throttle -----------------------------------------------------------------------------------


def test_throttle_spaces_calls_to_the_same_hosted_model(tmp_path: Path) -> None:
    clock = FakeClock()
    r = runner(
        entry("gemini:a", ai("1"), ai("2"), ai("3")),
        tmp_path=tmp_path,
        clock=clock,
        min_interval_seconds=4.5,
    )
    r.invoke(MSGS)
    assert clock.slept == []
    clock.t += 1.5
    r.invoke(MSGS)
    assert clock.slept == [pytest.approx(3.0)]
    clock.t += 10
    r.invoke(MSGS)
    assert len(clock.slept) == 1  # enough time had passed


def test_throttle_exempts_ollama_and_is_per_model(tmp_path: Path) -> None:
    clock = FakeClock()
    r = runner(
        entry("ollama:c", ai("1"), ai("2")),
        tmp_path=tmp_path,
        clock=clock,
        min_interval_seconds=4.5,
    )
    r.invoke(MSGS)
    r.invoke(MSGS)
    assert clock.slept == []
    r2 = runner(
        entry("gemini:a", RuntimeError("x")),
        entry("groq:b", ai("1")),
        tmp_path=tmp_path,
        clock=clock,
        min_interval_seconds=4.5,
    )
    r2.invoke(MSGS)
    assert clock.slept == []  # different models do not wait for each other


# --- structured output --------------------------------------------------------------------------


def test_structured_output_is_validated(tmp_path: Path) -> None:
    r = runner(entry("gemini:a", ai('{"cause": "fiber", "node": null}')), tmp_path=tmp_path)
    result = r.invoke(MSGS, schema=Verdict)
    assert result.parsed == Verdict(cause="fiber", node=None)


def test_invalid_structured_output_triggers_fallback(tmp_path: Path) -> None:
    r = runner(
        entry("gemini:a", ai('{"cause": "aliens"}')),
        entry("groq:b", ai("not json at all")),
        entry("ollama:c", ai('{"cause": "power", "node": "S-1"}')),
        tmp_path=tmp_path,
    )
    result = r.invoke(MSGS, schema=Verdict)
    assert result.parsed == Verdict(cause="power", node="S-1")
    assert [a.status for a in result.usage.attempts] == ["error", "error", "ok"]
    assert result.usage.fell_back


def test_tools_and_schema_together_are_rejected(tmp_path: Path) -> None:
    r = runner(entry("gemini:a"), tmp_path=tmp_path)
    with pytest.raises(ValueError, match="cannot be combined"):
        r.invoke(MSGS, tools=TOOLS, schema=Verdict)


# --- tool calls ---------------------------------------------------------------------------------


def test_tool_calls_are_normalised(tmp_path: Path) -> None:
    msg = ai("checking", tool_calls=[("get_alarms", {"start": "2026-09-20"}), ("get_changes", {})])
    chat = FakeChatModel(script=[msg])
    r = runner(ChainEntry("gemini:a", chat), tmp_path=tmp_path)
    result = r.invoke(MSGS, tools=TOOLS)
    assert result.tool_calls == [
        ToolCall(name="get_alarms", args={"start": "2026-09-20"}),
        ToolCall(name="get_changes", args={}),
    ]
    assert result.text == "checking"
    assert chat.bound_tools == [TOOLS]


def test_unknown_tool_name_is_returned_not_a_failure(tmp_path: Path) -> None:
    r = runner(entry("gemini:a", ai(tool_calls=[("made_up_tool", {"x": 1})])), tmp_path=tmp_path)
    result = r.invoke(MSGS, tools=TOOLS)
    assert result.tool_calls == [ToolCall(name="made_up_tool", args={"x": 1})]
    assert not result.usage.fell_back


def test_malformed_tool_call_triggers_fallback(tmp_path: Path) -> None:
    bad = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "get_alarms",
                "args": '{"start": ',
                "id": "1",
                "error": "bad json",
                "type": "invalid_tool_call",
            }
        ],
    )
    r = runner(
        entry("gemini:a", bad),
        entry("groq:b", ai(tool_calls=[("get_alarms", {})])),
        tmp_path=tmp_path,
    )
    result = r.invoke(MSGS, tools=TOOLS)
    assert result.usage.fell_back and result.tool_calls[0].name == "get_alarms"
    assert "malformed tool call" in (result.usage.attempts[0].error or "")


def test_json_string_args_are_decoded_and_junk_rejected() -> None:
    def msg(args: Any) -> AIMessage:
        return AIMessage.model_construct(
            content="", tool_calls=[{"name": "t", "args": args, "id": "1"}], invalid_tool_calls=[]
        )

    assert _tool_calls(msg('{"a": 1}')) == [ToolCall(name="t", args={"a": 1})]
    assert _tool_calls(msg("")) == [ToolCall(name="t", args={})]
    for junk in ("{not json", "[1, 2]", 5):
        with pytest.raises(Exception, match=r"malformed|not JSON"):
            _tool_calls(msg(junk))


def test_empty_answer_triggers_fallback(tmp_path: Path) -> None:
    r = runner(entry("gemini:a", ai("")), entry("groq:b", ai("ok")), tmp_path=tmp_path)
    assert r.invoke(MSGS).usage.fell_back


def test_tool_call_alone_is_a_valid_answer(tmp_path: Path) -> None:
    r = runner(entry("gemini:a", ai("", tool_calls=[("get_alarms", {})])), tmp_path=tmp_path)
    assert not r.invoke(MSGS, tools=TOOLS).usage.fell_back


def test_think_tags_are_stripped(tmp_path: Path) -> None:
    r = runner(entry("ollama:c", ai("<think>hmm\nlet me see</think>\nPong.")), tmp_path=tmp_path)
    assert r.invoke(MSGS).text == "Pong."


def test_stray_closing_think_tag_drops_the_thinking(tmp_path: Path) -> None:
    thinking = "Okay, the user wants pong.\n</think>\n\npong"
    r = runner(entry("ollama:c", ai(thinking)), tmp_path=tmp_path)
    assert r.invoke(MSGS).text == "pong"


# --- cache --------------------------------------------------------------------------------------


def test_readwrite_records_then_replays_without_calling(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    chat = FakeChatModel(script=[ai("recorded", input_tokens=40, output_tokens=7)])
    r = runner(
        ChainEntry("gemini:a", chat), tmp_path=tmp_path, cache_mode="readwrite", cache_dir=cache
    )
    first = r.invoke(MSGS, purpose="unit")
    again = r.invoke(MSGS, purpose="unit")  # the fake would raise if it were called again
    assert not first.usage.cached and again.usage.cached
    assert again.text == "recorded"
    assert (again.usage.provider, again.usage.model, again.usage.input_tokens) == (
        "gemini",
        "a",
        40,
    )
    assert len(chat.seen) == 1


def test_cache_file_is_readable_json_with_debug_info(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    r = runner(
        entry("gemini:a", ai("hi")), tmp_path=tmp_path, cache_mode="readwrite", cache_dir=cache
    )
    r.invoke(MSGS, tools=TOOLS, purpose="investigate step 2")
    files = list(cache.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    req = data["request"]
    assert req["purpose"] == "investigate step 2"
    assert "Sfax" in req["prompt_preview"] and req["tool_names"] == ["get_alarms"]
    assert req["messages_hash"] and req["tools_hash"] and data["usage"]["model"] == "a"
    assert data["response"]["text"] == "hi"


def test_cache_never_stores_api_keys(tmp_path: Path) -> None:
    secret = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE12345"
    settings = Settings(_env_file=None, gemini_api_key=secret, llm_cache_dir=tmp_path / "c")
    r = LLMRunner(
        chain=[
            entry("gemini:a", RuntimeError(f"401 for https://x/v1?key={secret} bad key {secret}")),
            entry("groq:b", ai("fine")),
        ],
        settings=settings,
        cache_mode="readwrite",
        min_interval_seconds=0,
    )
    result = r.invoke(MSGS)
    assert secret not in result.usage.attempts[0].error  # type: ignore[operator]
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "c").glob("*.json"))
    assert secret not in text and "AIza" not in text


def test_replay_miss_raises_and_never_calls_a_provider(tmp_path: Path) -> None:
    chat = FakeChatModel(script=[ai("should not be used")])
    r = runner(
        ChainEntry("gemini:a", chat),
        tmp_path=tmp_path,
        cache_mode="replay",
        cache_dir=tmp_path / "c",
    )
    with pytest.raises(CacheMiss, match="Sfax"):
        r.invoke(MSGS, purpose="p")
    assert chat.seen == []


def test_replay_serves_a_recording_made_by_another_model(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    rec = runner(
        entry("groq:x", ai('{"cause": "fiber", "node": "N1"}')),
        tmp_path=tmp_path,
        cache_mode="readwrite",
        cache_dir=cache,
    )
    rec.invoke(MSGS, schema=Verdict)
    rep = runner(entry("gemini:y"), tmp_path=tmp_path, cache_mode="replay", cache_dir=cache)
    hit = rep.invoke(MSGS, schema=Verdict)
    assert hit.parsed == Verdict(cause="fiber", node="N1")
    assert hit.usage.cached and (hit.usage.provider, hit.usage.model) == ("groq", "x")


def test_off_mode_ignores_existing_recordings(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    runner(
        entry("gemini:a", ai("old")), tmp_path=tmp_path, cache_mode="readwrite", cache_dir=cache
    ).invoke(MSGS)
    fresh = runner(
        entry("gemini:a", ai("new")), tmp_path=tmp_path, cache_mode="off", cache_dir=cache
    )
    assert fresh.invoke(MSGS).text == "new"


def test_cache_key_is_stable_and_independent_of_model_and_purpose() -> None:
    from langchain_core.messages import convert_to_messages

    msgs = convert_to_messages(MSGS)
    d1 = request_description("agent", msgs, TOOLS, Verdict, "step 1")
    d2 = request_description("agent", convert_to_messages(MSGS), TOOLS, Verdict, "other purpose")
    assert cache_key(d1) == cache_key(d2)
    assert len(cache_key(d1)) == 64
    # everything that matters changes the key
    other = [
        request_description("grader", msgs, TOOLS, Verdict, ""),
        request_description(
            "agent", convert_to_messages([*MSGS, ("human", "more")]), TOOLS, Verdict, ""
        ),
        request_description("agent", msgs, None, Verdict, ""),
        request_description("agent", msgs, TOOLS, None, ""),
    ]
    assert len({cache_key(d) for d in [d1, *other]}) == 5


def test_cache_key_golden_value() -> None:
    """Guards against accidental key changes, which would orphan committed cassettes."""
    from langchain_core.messages import convert_to_messages

    key = cache_key(request_description("agent", convert_to_messages(MSGS), TOOLS, None, ""))
    assert key == GOLDEN_KEY


GOLDEN_KEY = "46023b8da9d28b61a868e6ac4b4bcfbccff4eede0aca30c34c91dfe0a3be1809"


# --- client settings ----------------------------------------------------------------------------


def test_model_kwargs_turn_reasoning_down() -> None:
    g = build_model_kwargs("gemini", "gemini-3.5-flash-lite", max_output_tokens=100)
    assert g["thinking_level"] == "minimal" and "temperature" not in g and g["max_retries"] == 1
    assert (
        build_model_kwargs("gemini", "gemini-3.1-flash-lite", max_output_tokens=1)["temperature"]
        == 0
    )
    assert (
        build_model_kwargs("gemini", "gemini-2.5-flash", max_output_tokens=1)["thinking_budget"]
        == 0
    )
    assert (
        build_model_kwargs("groq", "openai/gpt-oss-120b", max_output_tokens=1)["reasoning_effort"]
        == "low"
    )
    q = build_model_kwargs("groq", "qwen/qwen3.8-27b", max_output_tokens=1)
    assert q["reasoning_effort"] == "none" and q["max_retries"] == 0
    o = build_model_kwargs("ollama", "qwen3:4b", max_output_tokens=1)
    assert o["reasoning"] is True and o["temperature"] == 0


def test_real_clients_accept_the_kwargs(use_settings: Any) -> None:
    from incident_agent.llm.factory import make_chat_model

    use_settings(gemini_api_key="g", groq_api_key="k")
    for spec in (
        "gemini:gemini-3.5-flash-lite",
        "groq:openai/gpt-oss-120b",
        "groq:qwen/qwen3.8-27b",
        "ollama:qwen3:4b",
    ):
        provider, _, model = spec.partition(":")
        make_chat_model(spec, **build_model_kwargs(provider, model, max_output_tokens=256))


def test_scrub_removes_keys_and_truncates() -> None:
    assert "AIza" not in scrub("bad AIzaSyABCDEFGHIJKLMNOPQRSTUV end")
    assert "gsk_" not in scrub("Invalid gsk_abcdefghijklmnopqrstuvwxyz1234")
    assert "sekret99" not in scrub("url?key=sekret99&x=1")
    assert len(scrub("x " * 500)) <= 300


def test_lookalike_hyphens_and_spaces_are_normalised(tmp_path: Path) -> None:
    ugly = "LNK" + chr(0x2011) + "TUN" + chr(0x2011) + "02 at 02:09" + chr(0x202F) + "UTC"
    r = runner(
        entry(
            "groq:b",
            ai(ugly, tool_calls=[("get_alarms", {"node_ids": [ugly]})]),
            ai(json.dumps({"cause": "fiber", "node": ugly})),
        ),
        tmp_path=tmp_path,
    )
    clean = "LNK-TUN-02 at 02:09 UTC"
    first = r.invoke(MSGS, tools=TOOLS)
    assert first.text == clean and first.tool_calls[0].args == {"node_ids": [clean]}
    parsed = r.invoke(MSGS, schema=Verdict).parsed
    assert isinstance(parsed, Verdict) and parsed.node == clean
