"""In-memory token-bucket rate limiter, keyed by caller (e.g. client IP).

Applied only to URL creation (see DESIGN.md's resolved ambiguity: creation,
not redirection, is the operation worth protecting). In-memory and
per-process by design -- see docs/testing_and_tradeoffs.md for what that
means for multi-instance deployments.
"""

import time
from threading import Lock


class TokenBucketRateLimiter:
    def __init__(self, capacity: int, refill_per_second: float, clock=time.monotonic):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._clock = clock
        self._lock = Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill_ts)

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self._clock()
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True
            self._buckets[key] = (tokens, now)
            return False
