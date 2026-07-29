from typing import Optional

from fastapi import FastAPI

from service.app.api import analytics, health, redirect, urls
from service.app.cache import LRUCache
from service.app.config import (
    DB_PATH,
    IDEMPOTENCY_TTL_SECONDS,
    RATE_LIMIT_CAPACITY,
    RATE_LIMIT_REFILL_PER_SECOND,
    REDIRECT_CACHE_SIZE,
)
from service.app.db import Database
from service.app.idempotency import IdempotencyStore
from service.app.rate_limiter import TokenBucketRateLimiter


def create_app(
    db_path: Optional[str] = None,
    rate_limiter: Optional[TokenBucketRateLimiter] = None,
    idempotency_store: Optional[IdempotencyStore] = None,
    redirect_cache: Optional[LRUCache] = None,
) -> FastAPI:
    app = FastAPI(title="URL Shortener Service", version="0.1.0")
    app.state.db = Database(db_path or DB_PATH)
    app.state.rate_limiter = rate_limiter or TokenBucketRateLimiter(
        capacity=RATE_LIMIT_CAPACITY, refill_per_second=RATE_LIMIT_REFILL_PER_SECOND
    )
    app.state.idempotency_store = idempotency_store or IdempotencyStore(ttl_seconds=IDEMPOTENCY_TTL_SECONDS)
    app.state.redirect_cache = redirect_cache or LRUCache(max_size=REDIRECT_CACHE_SIZE)

    # Registration order matters: redirect.router's GET /{code} is a
    # catch-all single-segment path. Every reserved literal path (health)
    # must be registered before it, or a short code that happens to collide
    # with the literal name would never be reachable -- and more
    # importantly, Starlette resolves routes in registration order, so the
    # catch-all would shadow the literal route entirely.
    app.include_router(urls.router)
    app.include_router(analytics.router)
    app.include_router(health.router)
    app.include_router(redirect.router)
    return app


app = create_app()
