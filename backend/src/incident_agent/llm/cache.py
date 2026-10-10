"""On-disk LLM response cache: one readable JSON file per request.

The key hashes (role, messages, tool schemas, output schema). The model is not part of it, so a
recording replays whichever model answers. Files hold no credentials: only the request (with a
short preview and per-part hashes, to debug a miss), the response and the original usage.
"""

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from incident_agent.llm.types import LLMResult, LLMUsage, ToolCall

CACHE_VERSION = 1
PREVIEW_CHARS = 200


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def message_parts(messages: Sequence[BaseMessage]) -> list[list[Any]]:
    return [[m.type, m.content] for m in messages]


def request_description(
    role: str,
    messages: Sequence[BaseMessage],
    tools: Sequence[dict[str, Any]] | None,
    schema: type[BaseModel] | None,
    purpose: str,
) -> dict[str, Any]:
    """Everything the key depends on (as hashes), plus human hints for debugging a miss."""
    last = messages[-1].text if messages else ""
    return {
        "role": role,
        "purpose": purpose,
        "messages_hash": _digest(message_parts(messages)),
        "tools_hash": _digest(list(tools or [])),
        "schema_hash": _digest(schema.model_json_schema()) if schema else "",
        "n_messages": len(messages),
        "tool_names": [t.get("name") or t.get("function", {}).get("name") for t in tools or []],
        "schema_name": schema.__name__ if schema else None,
        "prompt_preview": " ".join(last.split())[:PREVIEW_CHARS],
    }


def cache_key(description: dict[str, Any]) -> str:
    keyed = {k: description[k] for k in ("role", "messages_hash", "tools_hash", "schema_hash")}
    return _digest([CACHE_VERSION, keyed])


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, key: str) -> Path:
        return self.directory / f"{key[:24]}.json"

    def load(self, key: str, schema: type[BaseModel] | None) -> LLMResult | None:
        path = self.path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        if entry.get("key") != key:
            return None
        response = entry["response"]
        parsed = None
        if schema is not None and response.get("parsed") is not None:
            parsed = schema.model_validate(response["parsed"])
        usage = LLMUsage.model_validate({**entry["usage"], "cached": True})
        return LLMResult(
            text=response["text"],
            tool_calls=[ToolCall.model_validate(c) for c in response["tool_calls"]],
            parsed=parsed,
            usage=usage,
        )

    def save(self, key: str, description: dict[str, Any], result: LLMResult) -> None:
        entry = {
            "key": key,
            "request": description,
            "response": {
                "text": result.text,
                "tool_calls": [c.model_dump() for c in result.tool_calls],
                "parsed": result.parsed.model_dump(mode="json") if result.parsed else None,
            },
            "usage": result.usage.model_dump(mode="json", exclude={"cached"}),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(key)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
