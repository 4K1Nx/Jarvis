"""Tiny async event bus: every subsystem publishes trace events, the HUD subscribes."""
import asyncio, time
from typing import Any, Dict, List


class EventBus:
    def __init__(self) -> None:
        self._subs: List[asyncio.Queue] = []
        self._loops = {}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subs.append(q)
        self._loops[q] = asyncio.get_running_loop()
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)
            self._loops.pop(q, None)

    def emit(self, channel: str, text: str = "", **extra: Any) -> None:
        evt: Dict[str, Any] = {"ts": time.time(), "channel": channel, "text": text, **extra}
        def deliver(q):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass
        for q in list(self._subs):
            loop = self._loops.get(q)
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(deliver, q)


BUS = EventBus()
