"""In-process event bus.

Events are the only mechanism the UI and the monitor consume: no polling.
Names follow ``domain.action`` (e.g. ``chat.delta``, ``request.stage``,
``node.discovered``). Payloads are JSON-serializable dicts.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self, history: int = 500):
        self._subscribers: list[Handler] = []
        self._async_subscribers: list[Callable[[dict[str, Any]], Any]] = []
        self._lock = threading.Lock()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)

    def subscribe(self, handler: Handler) -> None:
        with self._lock:
            self._subscribers.append(handler)

    def unsubscribe(self, handler: Handler) -> None:
        with self._lock:
            if handler in self._subscribers:
                self._subscribers.remove(handler)

    def subscribe_async(self, coro_handler: Callable[[dict[str, Any]], Any]) -> None:
        with self._lock:
            self._async_subscribers.append(coro_handler)

    def unsubscribe_async(self, coro_handler: Callable[[dict[str, Any]], Any]) -> None:
        with self._lock:
            if coro_handler in self._async_subscribers:
                self._async_subscribers.remove(coro_handler)

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "type": event_type,
            "payload": payload,
        }
        self._history.append(event)
        with self._lock:
            subs = list(self._subscribers)
            async_subs = list(self._async_subscribers)
        for handler in subs:
            try:
                handler(event)
            except Exception:  # a subscriber must never break the publisher
                pass
        for coro_handler in async_subs:
            try:
                asyncio.ensure_future(coro_handler(event))
            except Exception:
                pass
        return event

    def recent(self, n: int = 100) -> list[dict[str, Any]]:
        return list(self._history)[-n:]
