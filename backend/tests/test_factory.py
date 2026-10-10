from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from incident_agent.config import Settings
from incident_agent.llm.factory import LLMConfigError, get_llm, make_chat_model

UseSettings = Callable[..., Settings]


def test_routes_gemini(use_settings: UseSettings) -> None:
    use_settings(gemini_api_key="g")
    model = make_chat_model("gemini:gemini-flash-latest")
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model.endswith("gemini-flash-latest")


def test_routes_groq(use_settings: UseSettings) -> None:
    use_settings(groq_api_key="k")
    model = make_chat_model("groq:openai/gpt-oss-120b")
    assert isinstance(model, ChatGroq)
    assert model.model_name == "openai/gpt-oss-120b"


def test_routes_ollama_without_key(use_settings: UseSettings) -> None:
    use_settings(ollama_base_url="http://example:1234")
    model = make_chat_model("ollama:qwen3:4b")
    assert isinstance(model, ChatOllama)
    assert model.model == "qwen3:4b"
    assert model.base_url == "http://example:1234"


def test_kwargs_are_forwarded(use_settings: UseSettings) -> None:
    use_settings()
    model = make_chat_model("ollama:qwen3:4b", temperature=0.0)
    assert isinstance(model, ChatOllama)
    assert model.temperature == 0.0


def test_unknown_provider(use_settings: UseSettings) -> None:
    use_settings()
    with pytest.raises(LLMConfigError, match="Unknown provider 'openai'"):
        make_chat_model("openai:gpt-4o")


@pytest.mark.parametrize(
    ("spec", "var"), [("gemini:m", "GEMINI_API_KEY"), ("groq:m", "GROQ_API_KEY")]
)
def test_missing_key(use_settings: UseSettings, spec: str, var: str) -> None:
    use_settings()
    with pytest.raises(LLMConfigError, match=var):
        make_chat_model(spec)


def _fallback_types(llm: Any) -> list[type]:
    assert isinstance(llm, RunnableWithFallbacks)
    return [type(f) for f in llm.fallbacks]


def test_agent_has_fallback_chain(use_settings: UseSettings) -> None:
    use_settings(gemini_api_key="g", groq_api_key="k")
    llm = get_llm("agent")
    assert isinstance(llm, RunnableWithFallbacks)
    assert isinstance(llm.runnable, ChatGoogleGenerativeAI)
    assert _fallback_types(llm) == [ChatGroq, ChatOllama]


def test_agent_skips_fallbacks_without_keys(use_settings: UseSettings) -> None:
    use_settings(gemini_api_key="g")  # no groq key
    assert _fallback_types(get_llm("agent")) == [ChatOllama]


def test_agent_without_any_fallback_returns_primary(use_settings: UseSettings) -> None:
    use_settings(gemini_api_key="g", fallback_models=["groq:openai/gpt-oss-120b"])
    assert isinstance(get_llm("agent"), ChatGoogleGenerativeAI)


def test_agent_unknown_fallback_provider_raises(use_settings: UseSettings) -> None:
    use_settings(gemini_api_key="g", fallback_models=["nope:x"])
    with pytest.raises(LLMConfigError, match="Unknown provider"):
        get_llm("agent")


def test_grader_has_no_fallback(use_settings: UseSettings) -> None:
    use_settings(groq_api_key="k", gemini_api_key="g")
    llm = get_llm("grader")
    assert isinstance(llm, ChatGroq)
    assert llm.model_name == "qwen/qwen3.8-27b"


def test_agent_requires_primary_key(use_settings: UseSettings) -> None:
    use_settings(groq_api_key="k")
    with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
        get_llm("agent")
