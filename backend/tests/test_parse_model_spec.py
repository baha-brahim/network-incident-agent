import pytest

from incident_agent.llm.factory import LLMConfigError, parse_model_spec


def test_simple_spec() -> None:
    assert parse_model_spec("gemini:gemini-flash-latest") == ("gemini", "gemini-flash-latest")


def test_splits_on_first_colon_only() -> None:
    assert parse_model_spec("ollama:qwen3:4b") == ("ollama", "qwen3:4b")


def test_model_name_may_contain_slashes() -> None:
    assert parse_model_spec("groq:openai/gpt-oss-120b") == ("groq", "openai/gpt-oss-120b")


def test_provider_is_normalised() -> None:
    assert parse_model_spec("  Groq :x") == ("groq", "x")


@pytest.mark.parametrize("spec", ["", "gemini", ":model", "gemini:", "gemini: "])
def test_invalid_spec(spec: str) -> None:
    with pytest.raises(LLMConfigError):
        parse_model_spec(spec)
