"""Provider-agnostic chat model factory. Models are "provider:model" strings."""

from typing import Any, Literal

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from incident_agent.config import Settings, get_settings

PROVIDERS = ("gemini", "groq", "ollama")


class LLMConfigError(ValueError):
    """Bad model spec, unknown provider or missing credentials."""


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Split "provider:model" on the first colon only ("ollama:qwen3:4b" has two)."""
    provider, sep, model = spec.partition(":")
    if not sep or not provider.strip() or not model.strip():
        raise LLMConfigError(f"Invalid model spec {spec!r}; expected 'provider:model'")
    return provider.strip().lower(), model.strip()


def has_credentials(provider: str, settings: Settings) -> bool:
    """Ollama needs no key; gemini and groq need theirs set."""
    if provider == "gemini":
        return settings.gemini_api_key is not None
    if provider == "groq":
        return settings.groq_api_key is not None
    return provider == "ollama"


def _usable(spec: str, settings: Settings) -> bool:
    """A fallback is skipped only when its provider is known but its key is missing.

    Unknown providers are let through so make_chat_model raises a clear error.
    """
    provider, _ = parse_model_spec(spec)
    return provider not in PROVIDERS or has_credentials(provider, settings)


def make_chat_model(spec: str, **kwargs: Any) -> BaseChatModel:
    settings = get_settings()
    provider, model = parse_model_spec(spec)
    if provider not in PROVIDERS:
        raise LLMConfigError(f"Unknown provider {provider!r} in {spec!r}; use one of {PROVIDERS}")
    if not has_credentials(provider, settings):
        raise LLMConfigError(f"{provider.upper()}_API_KEY is not set; required for model {spec!r}")

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, api_key=settings.gemini_api_key, **kwargs)
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, api_key=settings.groq_api_key, **kwargs)

    from langchain_ollama import ChatOllama

    return ChatOllama(model=model, base_url=settings.ollama_base_url, **kwargs)


def get_llm(role: Literal["agent", "grader"]) -> Runnable[LanguageModelInput, AIMessage]:
    """agent = primary with fallbacks (skipping ones without keys); grader = no fallback."""
    settings = get_settings()
    if role == "grader":
        return make_chat_model(settings.grader_model)

    primary = make_chat_model(settings.agent_model)
    fallbacks = [
        make_chat_model(spec) for spec in settings.fallback_models if _usable(spec, settings)
    ]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
