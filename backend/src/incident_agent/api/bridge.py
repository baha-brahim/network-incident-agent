"""Serve a blocking iterator as Server-Sent Events without blocking the event loop."""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator

from incident_agent.api.events import KEEPALIVE, OPEN, ApiEvent, sse_frame

log = logging.getLogger(__name__)
_DONE = object()


async def sse_from_iterator(
    make: Callable[[], Iterator[ApiEvent]], keepalive: float
) -> AsyncIterator[str]:
    """Frames of the events `make()` yields, produced on a worker thread.

    A comment frame is sent whenever `keepalive` seconds pass without an event. If the client goes
    away, the iterator is closed after the event it is currently producing.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[object] = asyncio.Queue()
    stop = threading.Event()

    def put(item: object) -> bool:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # the loop is gone
            return False
        return True

    def work() -> None:
        events: Iterator[ApiEvent] | None = None
        try:
            events = make()
            for event in events:
                if not put(event) or stop.is_set():
                    break
        except Exception:
            log.exception("event stream failed")
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                close()
            put(_DONE)

    threading.Thread(target=work, name="investigation", daemon=True).start()
    yield OPEN
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), keepalive)
            except TimeoutError:
                yield KEEPALIVE
                continue
            if item is _DONE:
                return
            assert isinstance(item, dict)
            yield sse_frame(item)
    finally:
        stop.set()
