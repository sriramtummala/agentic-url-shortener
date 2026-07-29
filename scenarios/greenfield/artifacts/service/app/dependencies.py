from fastapi import HTTPException, Request, status

from service.app.cache import LRUCache
from service.app.db import Database
from service.app.idempotency import IdempotencyStore


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_cache(request: Request) -> LRUCache:
    return request.app.state.redirect_cache


def get_idempotency_store(request: Request) -> IdempotencyStore:
    return request.app.state.idempotency_store


def enforce_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.allow(client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded, try again shortly")
