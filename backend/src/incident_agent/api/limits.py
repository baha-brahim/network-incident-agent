"""Request body size limit, as a plain ASGI middleware (it must work for streaming bodies too)."""

import contextlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from incident_agent.api.events import dumps

MAX_BODY_BYTES = 8 * 1024


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        seen = 0
        rejected = False

        async def counted() -> Message:
            nonlocal seen, rejected
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    # Answer now: the framework would turn the error below into a 400.
                    rejected = True
                    await self._reject(send)
                    raise BodyTooLarge
            return message

        async def tracked(message: Message) -> None:
            if not rejected:
                await send(message)

        with contextlib.suppress(BodyTooLarge):
            await self.app(scope, counted, tracked)

    async def _reject(self, send: Send) -> None:
        body = dumps(
            {"error": {"code": "too_large", "message": f"The body exceeds {self.max_bytes} bytes."}}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
