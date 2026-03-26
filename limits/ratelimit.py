"""Sliding-window rate limiter keyed by string (e.g. client IP)."""

from __future__ import annotations

import time
from collections import defaultdict


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: int) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._timestamps: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, str]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        stamps = [t for t in self._timestamps[key] if t > cutoff]
        if len(stamps) >= self.max_events:
            return (
                False,
                f"Too many messages. Limit is {self.max_events} per "
                f"{self.window_seconds // 60} minutes. Try again later.",
            )
        stamps.append(now)
        self._timestamps[key] = stamps
        return True, ""
