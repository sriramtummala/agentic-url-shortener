from service.app.cache import LRUCache


def test_set_then_get():
    cache = LRUCache(max_size=2)
    cache.set("a", (1,))
    assert cache.get("a") == (1,)


def test_get_missing_returns_none():
    cache = LRUCache()
    assert cache.get("missing") is None


def test_evicts_least_recently_used_when_full():
    cache = LRUCache(max_size=2)
    cache.set("a", (1,))
    cache.set("b", (2,))
    cache.set("c", (3,))  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") == (2,)
    assert cache.get("c") == (3,)


def test_get_refreshes_recency():
    cache = LRUCache(max_size=2)
    cache.set("a", (1,))
    cache.set("b", (2,))
    cache.get("a")  # "a" is now most-recently-used
    cache.set("c", (3,))  # evicts "b", not "a"
    assert cache.get("a") == (1,)
    assert cache.get("b") is None


def test_invalidate_removes_entry():
    cache = LRUCache()
    cache.set("a", (1,))
    cache.invalidate("a")
    assert cache.get("a") is None
