"""Turn provider exceptions into something the runner can act on (and print safely)."""

import re
from dataclasses import dataclass
from typing import Literal

# Cooldowns in seconds.
DEFAULT_RATE_LIMIT_COOLDOWN = 60.0
DAILY_QUOTA_COOLDOWN = 6 * 3600.0
TRANSIENT_COOLDOWN = 10.0
MAX_ERROR_CHARS = 300

_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),  # Groq API keys
    re.compile(r"(?i)bearer\s+[\w\-.]{10,}"),
    re.compile(r"(?i)\b(api[_-]?key|key|token)=[^\s&'\",]{6,}"),  # ?key=... in URLs
]

_RETRY_HINTS = [
    re.compile(r"(?i)retry in (\d+(?:\.\d+)?)\s*s"),  # Gemini: "Please retry in 12.3s"
    re.compile(r"(?i)retrydelay\W+(\d+(?:\.\d+)?)\s*s"),  # Gemini: retryDelay: '12s'
]
_GROQ_HINT = re.compile(
    r"(?i)try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?"
)
_DAILY = re.compile(r"(?i)per ?day|\bRPD\b|\bTPD\b|daily")
_RATE_LIMIT = re.compile(r"(?i)\b429\b|rate.?limit|resource_exhausted|quota|too many requests")
_TRANSIENT = re.compile(
    r"(?i)\b(500|502|503|504)\b|unavailable|overloaded|high demand|timed? ?out|deadline|"
    r"connection (error|refused|reset)|temporarily"
)

ErrorKind = Literal["rate_limit", "transient", "other"]


def scrub(text: str, secrets: list[str] | None = None) -> str:
    """Remove API keys from a message and cut it to a printable length."""
    for secret in secrets or []:
        if secret:
            text = text.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***", text)
    text = " ".join(text.split())
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 3] + "..."


@dataclass(frozen=True)
class ErrorInfo:
    kind: ErrorKind
    cooldown: float  # seconds to leave this model alone (0 = none)


def _status(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _retry_hint(exc: BaseException, text: str) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        try:
            return float(headers.get("retry-after"))
        except (TypeError, ValueError):
            pass
    for pattern in _RETRY_HINTS:
        if m := pattern.search(text):
            return float(m.group(1))
    if m := _GROQ_HINT.search(text):
        hours, minutes, seconds, millis = m.groups()
        total = (
            int(hours or 0) * 3600
            + int(minutes or 0) * 60
            + float(seconds or 0)
            + int(millis or 0) / 1000
        )
        return total or None
    return None


def classify(exc: BaseException) -> ErrorInfo:
    """Rate limits cool down by the provider's hint (or 60 s; much longer for daily quotas)."""
    text = f"{type(exc).__name__} {exc}"
    status = _status(exc)
    if status == 429 or (status is None and _RATE_LIMIT.search(text)):
        hint = _retry_hint(exc, text)
        cooldown = (hint + 1.0) if hint is not None else DEFAULT_RATE_LIMIT_COOLDOWN
        if _DAILY.search(text):
            cooldown = max(cooldown, DAILY_QUOTA_COOLDOWN)
        return ErrorInfo("rate_limit", cooldown)
    if (status is not None and status >= 500) or isinstance(exc, TimeoutError):
        return ErrorInfo("transient", TRANSIENT_COOLDOWN)
    if status is None and _TRANSIENT.search(text):
        return ErrorInfo("transient", TRANSIENT_COOLDOWN)
    return ErrorInfo("other", 0.0)
