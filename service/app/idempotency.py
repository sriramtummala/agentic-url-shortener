"""Tracks recently-seen Idempotency-Key values so a retried POST /api/urls
returns the original response instead of minting a second short code for
the same logical request. Entries expire after ttl_seconds to bound memory
growth -- this is a cache, not a durable log, so a restart losing in-flight
keys is an accepted trade-off for the prototype.
"""

import time
from threading import Lock
from typing import Optional


class IdempotencyStore:
    def __init__(self, ttl_seconds: float = 300.0, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = Lock()
        self._entries: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            self._evict_expired()
            entry = self._entries.get(key)
            return entry[1] if entry else None

    def put(self, key: str, response_body: dict) -> None:
        with self._lock:
            self._entries[key] = (self._clock(), response_body)

    def _evict_expired(self) -> None:
        now = self._clock()
        expired = [k for k, (stored_at, _) in self._entries.items() if now - stored_at > self._ttl]
        for k in expired:
            del self._entries[k]
