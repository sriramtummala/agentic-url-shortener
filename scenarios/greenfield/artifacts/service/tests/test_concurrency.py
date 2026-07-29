"""Thread-safety checks for the in-memory reliability primitives. Each one
guards its state with a lock; these tests prove that under real concurrent
access, not just in isolated single-threaded calls."""

import threading

from service.app.cache import LRUCache
from service.app.idempotency import IdempotencyStore
from service.app.rate_limiter import TokenBucketRateLimiter


def _run_concurrently(worker, count: int) -> None:
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_rate_limiter_never_exceeds_capacity_under_concurrent_access():
    limiter = TokenBucketRateLimiter(capacity=50, refill_per_second=0)
    results = []
    lock = threading.Lock()

    def worker(_i):
        allowed = limiter.allow("shared-key")
        with lock:
            results.append(allowed)

    _run_concurrently(worker, count=200)

    assert results.count(True) == 50


def test_cache_respects_max_size_under_concurrent_access():
    cache = LRUCache(max_size=10)

    def worker(i):
        cache.set(f"key{i}", (i,))
        cache.get(f"key{i}")

    _run_concurrently(worker, count=100)

    assert len(cache) <= 10


def test_idempotency_store_is_consistent_under_concurrent_access():
    store = IdempotencyStore(ttl_seconds=100)
    failures = []

    def worker(i):
        store.put(f"key{i}", {"code": f"code{i}"})
        if store.get(f"key{i}") != {"code": f"code{i}"}:
            failures.append(i)

    _run_concurrently(worker, count=100)

    assert failures == []
