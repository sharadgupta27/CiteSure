"""A small in-memory sliding-window limiter. It protects a single API process; behind several replicas, move it to
the reverse proxy (Caddy) or a shared store."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.errors import TooManyRequests


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise TooManyRequests("Too many requests. Please slow down.")
        hits.append(now)
