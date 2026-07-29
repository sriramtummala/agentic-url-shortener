from typing import Optional

from fastapi import FastAPI

from service.app.config import DB_PATH
from service.app.db import Database
from service.app.api import analytics, redirect, urls


def create_app(db_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="URL Shortener Service", version="0.1.0")
    app.state.db = Database(db_path or DB_PATH)

    # Registration order matters: redirect.router's GET /{code} is a
    # catch-all single-segment path. Any reserved literal path (e.g. a
    # future /health) must be registered before it, or a short code that
    # happens to collide with the literal name would never be reachable --
    # and more importantly, Starlette resolves routes in registration
    # order, so the catch-all would shadow the literal route entirely.
    app.include_router(urls.router)
    app.include_router(analytics.router)
    app.include_router(redirect.router)
    return app


app = create_app()
