"""Regression test for a brownfield bug: idempotent retries of POST
/api/urls were consuming rate-limit budget on every retry, even though a
retry with a matching Idempotency-Key never reaches the code-generation/
insert path -- it's served straight from the idempotency cache. That let a
client's own safe retries exhaust its rate-limit capacity and get 429'd
purely from retrying, defeating the point of idempotency support.
"""

from fastapi.testclient import TestClient

from service.app.main import create_app
from service.app.rate_limiter import TokenBucketRateLimiter


def test_idempotent_retries_do_not_consume_rate_limit_budget(tmp_path):
    app = create_app(
        db_path=tmp_path / "test.db",
        rate_limiter=TokenBucketRateLimiter(capacity=1, refill_per_second=0),
    )
    client = TestClient(app)
    headers = {"Idempotency-Key": "retry-key"}

    first = client.post("/api/urls", json={"destination_url": "https://example.com/a"}, headers=headers)
    assert first.status_code == 201

    # Capacity (1) is exhausted after the first real attempt. Retries with
    # the SAME idempotency key must still succeed via the cache, not burn
    # more budget.
    for _ in range(5):
        retry = client.post("/api/urls", json={"destination_url": "https://example.com/a"}, headers=headers)
        assert retry.status_code == 201
        assert retry.json()["code"] == first.json()["code"]

    # A genuinely new request (no matching idempotency key) still gets
    # rate-limited -- capacity enforcement for real new work is unaffected.
    fresh = client.post("/api/urls", json={"destination_url": "https://example.com/b"})
    assert fresh.status_code == 429
