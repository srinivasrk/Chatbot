"""Sliding-window rate limiter keyed by string (e.g. client IP)."""

from __future__ import annotations

import time
from collections import defaultdict

# Run a full sweep of expired keys every this many successful check() calls.
_CLEANUP_INTERVAL = 200


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: int) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._call_count = 0

    def check(self, key: str) -> tuple[bool, str]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        stamps = [t for t in self._timestamps[key] if t > cutoff]
        if len(stamps) >= self.max_events:
            self._timestamps[key] = stamps  # save pruned list even on refusal
            return (
                False,
                f"Too many messages. Limit is {self.max_events} per "
                f"{self.window_seconds // 60} minutes. Try again later.",
            )
        stamps.append(now)
        self._timestamps[key] = stamps

        # Periodically remove keys whose windows have fully expired to prevent
        # the dict from growing unboundedly on long-running servers.
        self._call_count += 1
        if self._call_count % _CLEANUP_INTERVAL == 0:
            self._prune_expired(cutoff)

        return True, ""

    def _prune_expired(self, cutoff: float) -> None:
        """Delete entries where every timestamp is older than the current window."""
        expired = [k for k, ts in self._timestamps.items() if not ts or max(ts) <= cutoff]
        for k in expired:
            del self._timestamps[k]
