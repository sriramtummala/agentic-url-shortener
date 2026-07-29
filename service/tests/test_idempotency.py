from service.app.idempotency import IdempotencyStore


def test_put_then_get_returns_stored_value():
    store = IdempotencyStore(ttl_seconds=10)
    store.put("key1", {"code": "abc1234"})
    assert store.get("key1") == {"code": "abc1234"}


def test_get_missing_key_returns_none():
    store = IdempotencyStore()
    assert store.get("missing") is None


def test_entry_expires_after_ttl():
    clock = [0.0]
    store = IdempotencyStore(ttl_seconds=5, clock=lambda: clock[0])
    store.put("key1", {"code": "abc1234"})
    clock[0] += 6
    assert store.get("key1") is None
