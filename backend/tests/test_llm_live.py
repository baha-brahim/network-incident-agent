import pytest

from incident_agent.config import get_settings
from incident_agent.llm.factory import make_chat_model

PROMPT = "Reply with one short sentence."


def _invoke(spec: str) -> None:
    answer = make_chat_model(spec).invoke(PROMPT).text
    assert answer.strip()


@pytest.mark.llm
def test_gemini_live() -> None:
    if get_settings().gemini_api_key is None:
        pytest.skip("GEMINI_API_KEY not set")
    _invoke(get_settings().agent_model)


@pytest.mark.llm
def test_groq_live() -> None:
    if get_settings().groq_api_key is None:
        pytest.skip("GROQ_API_KEY not set")
    _invoke("groq:openai/gpt-oss-120b")


@pytest.mark.llm
def test_ollama_live() -> None:
    _invoke("ollama:qwen3:4b")
