from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from service.app.cache import LRUCache
from service.app.db import Database
from service.app.dependencies import get_cache, get_db

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
def redirect_to_destination(
    code: str, db: Database = Depends(get_db), cache: LRUCache = Depends(get_cache),
) -> RedirectResponse:
    now = datetime.now(timezone.utc)

    cached = cache.get(code)
    if cached is not None:
        destination_url, expires_at_iso = cached
        if expires_at_iso is not None and datetime.fromisoformat(expires_at_iso) <= now:
            cache.invalidate(code)
        else:
            db.record_click(code, day=now.date().isoformat(), accessed_at=now.isoformat())
            return RedirectResponse(destination_url, status_code=status.HTTP_302_FOUND)

    row = db.get_url(code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short URL not found")
    if row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) <= now:
        raise HTTPException(status.HTTP_410_GONE, "short URL has expired")

    cache.set(code, (row["destination_url"], row["expires_at"]))
    db.record_click(code, day=now.date().isoformat(), accessed_at=now.isoformat())
    return RedirectResponse(row["destination_url"], status_code=status.HTTP_302_FOUND)
