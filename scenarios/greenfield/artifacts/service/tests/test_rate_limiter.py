from service.app.rate_limiter import TokenBucketRateLimiter


def test_allows_up_to_capacity_then_blocks():
    clock = [0.0]
    limiter = TokenBucketRateLimiter(capacity=3, refill_per_second=0, clock=lambda: clock[0])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False


def test_refills_over_time():
    clock = [0.0]
    limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=1, clock=lambda: clock[0])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False
    clock[0] += 1.0
    assert limiter.allow("ip1") is True


def test_keys_are_independent():
    clock = [0.0]
    limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=0, clock=lambda: clock[0])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip2") is True
    assert limiter.allow("ip1") is False
