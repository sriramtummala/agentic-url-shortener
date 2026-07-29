from fastapi.testclient import TestClient

from service.app.main import create_app
from service.app.rate_limiter import TokenBucketRateLimiter


def test_idempotency_key_returns_same_result_on_retry(client):
    headers = {"Idempotency-Key": "req-1"}
    resp1 = client.post("/api/urls", json={"destination_url": "https://example.com/a"}, headers=headers)
    resp2 = client.post("/api/urls", json={"destination_url": "https://example.com/a"}, headers=headers)
    assert resp1.json()["code"] == resp2.json()["code"]
    assert resp1.json()["owner_token"] == resp2.json()["owner_token"]


def test_without_idempotency_key_each_request_is_distinct(client):
    resp1 = client.post("/api/urls", json={"destination_url": "https://example.com/a"})
    resp2 = client.post("/api/urls", json={"destination_url": "https://example.com/a"})
    assert resp1.json()["code"] != resp2.json()["code"]


def test_rate_limit_blocks_after_capacity_exceeded(tmp_path):
    app = create_app(
        db_path=tmp_path / "test.db",
        rate_limiter=TokenBucketRateLimiter(capacity=2, refill_per_second=0),
    )
    client = TestClient(app)
    for _ in range(2):
        resp = client.post("/api/urls", json={"destination_url": "https://example.com/a"})
        assert resp.status_code == 201
    resp = client.post("/api/urls", json={"destination_url": "https://example.com/a"})
    assert resp.status_code == 429


def test_redirect_after_delete_is_not_served_from_stale_cache(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/a"}).json()
    code = created["code"]
    client.get(f"/{code}", follow_redirects=False)  # warm the cache
    client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": created["owner_token"]})
    resp = client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 404
