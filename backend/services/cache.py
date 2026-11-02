"""An async cache that shares in-flight work, serves stale data when a refresh fails, and a request budget."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Dict, Hashable

Clock = Callable[[], float]


@dataclass
class _Hit:
    value: Any
    expires: float
    stale_until: float


class TTLCache:
    """Cache for async calls.

    * Concurrent callers for one key share a single in-flight call.
    * A failed call is never cached.
    * With ``stale_ttl`` set, an entry that has expired is still served when refreshing it fails
      (GitHub is down or rate limiting us), for up to ``stale_ttl`` seconds longer.
    """

    def __init__(self, ttl: float, *, stale_ttl: float = 0.0, max_items: int = 256, clock: Clock = time.monotonic) -> None:
        self._ttl = ttl
        self._stale_ttl = stale_ttl
        self._max_items = max_items
        self._clock = clock
        self._values: Dict[Hashable, _Hit] = {}
        self._inflight: Dict[Hashable, asyncio.Future[Any]] = {}

    def __len__(self) -> int:
        return len(self._values)

    async def get_or_create(self, key: Hashable, factory: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._values.get(key)
        if hit and self._clock() < hit.expires:
            return hit.value

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(factory())
            self._inflight[key] = task
            task.add_done_callback(lambda done, key=key: self._finish(key, done))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            stale = self._values.get(key)
            if stale and self._clock() < stale.stale_until:
                return stale.value
            raise

    def _finish(self, key: Hashable, task: asyncio.Future[Any]) -> None:
        self._inflight.pop(key, None)
        if task.cancelled() or task.exception() is not None:
            return  # reading exception() also marks it retrieved, so asyncio does not warn about it
        now = self._clock()
        self._values[key] = _Hit(task.result(), now + self._ttl, now + self._ttl + self._stale_ttl)
        self._prune(now)

    def _prune(self, now: float) -> None:
        if len(self._values) <= self._max_items:
            return
        for key in [k for k, hit in self._values.items() if hit.stale_until <= now]:
            del self._values[key]
        while len(self._values) > self._max_items:
            del self._values[next(iter(self._values))]


class SlidingBudget:
    """At most ``limit`` calls in any ``window`` seconds. Used to stay inside GitHub's search limit."""

    def __init__(self, limit: int, window: float = 60.0, clock: Clock = time.monotonic) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._calls: Deque[float] = deque()

    def try_acquire(self) -> float:
        """Spend one call and return 0, or return how many seconds until one is free."""
        now = self._clock()
        while self._calls and self._calls[0] <= now - self._window:
            self._calls.popleft()
        if len(self._calls) >= self._limit:
            return max(1.0, self._calls[0] + self._window - now)
        self._calls.append(now)
        return 0.0
