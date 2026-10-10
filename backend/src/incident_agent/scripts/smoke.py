"""Smoke test: DB connection plus one tiny prompt to every configured model.

Run with: uv run python -m incident_agent.scripts.smoke
"""

import sys
import time

from incident_agent.config import get_settings
from incident_agent.db import check_connection
from incident_agent.llm.factory import make_chat_model, parse_model_spec

PROMPT = "Reply with exactly one short sentence: say hello."


def _scrub(text: str) -> str:
    """Remove configured secrets from any error text before it is printed."""
    settings = get_settings()
    for secret in (settings.gemini_api_key, settings.groq_api_key):
        if secret is not None and secret.get_secret_value():
            text = text.replace(secret.get_secret_value(), "***")
    return text


def _one_line(text: str, width: int) -> str:
    return " ".join(text.split())[:width]


def probe(role: str, spec: str) -> tuple[str, str, str, str, str, str]:
    """Return (role, provider, model, status, latency, detail) for one model."""
    provider, model = parse_model_spec(spec)
    start = time.perf_counter()
    try:
        answer = make_chat_model(spec).invoke(PROMPT).text
        status, detail = "ok", _one_line(answer, 60)
    except Exception as exc:
        status = "error"
        detail = _scrub(f"{type(exc).__name__}: {exc}")
    latency = f"{time.perf_counter() - start:.1f}s"
    return role, provider, model, status, latency, _one_line(detail, 60 if status == "ok" else 110)


def main() -> int:
    settings = get_settings()
    failures = 0

    try:
        check_connection()
        print("db: ok (SELECT 1, vector extension present)")
    except Exception as exc:
        failures += 1
        print(f"db: ERROR {_scrub(f'{type(exc).__name__}: {exc}')[:200]}")

    targets = [("agent", settings.agent_model)]
    targets += [("fallback", spec) for spec in settings.fallback_models]
    targets += [("grader", settings.grader_model)]

    rows = [("role", "provider", "model", "status", "latency", "answer / error")]
    for role, spec in targets:
        row = probe(role, spec)
        failures += row[3] != "ok"
        rows.append(row)

    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for i, row in enumerate(rows):
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))
        if i == 0:
            print("  ".join("-" * w for w in widths))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
