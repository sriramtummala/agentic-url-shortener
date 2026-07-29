"""In-process LRU cache in front of redirect lookups -- the redirect path is
the hottest, most latency-sensitive one (every click hits it), so avoiding a
DB round trip on repeat lookups matters more here than anywhere else in the
service.
"""

from collections import OrderedDict
from threading import Lock
from typing import Optional


class LRUCache:
    def __init__(self, max_size: int = 1024):
        self.max_size = max_size
        self._lock = Lock()
        self._data: "OrderedDict[str, tuple]" = OrderedDict()

    def get(self, key: str) -> Optional[tuple]:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: tuple) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            if len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
