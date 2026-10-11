"""The event envelope and its Server-Sent Events framing."""

import json
from typing import Any

KEEPALIVE = ": keep-alive\n\n"
OPEN = ": open\n\n"

ApiEvent = dict[str, Any]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def envelope(seq: int, type_: str, run_id: str, t_ms: int, data: dict[str, Any]) -> ApiEvent:
    return {"seq": seq, "type": type_, "run_id": run_id, "t_ms": t_ms, "data": data}


def sse_frame(event: ApiEvent) -> str:
    """`event: <type>` and one `data:` line holding the whole envelope as JSON."""
    return f"event: {event['type']}\ndata: {dumps(event)}\n\n"
