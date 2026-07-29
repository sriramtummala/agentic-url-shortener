from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from service.app.db import Database
from service.app.dependencies import get_db

router = APIRouter(tags=["redirect"])


@router.get("/{code}")
def redirect_to_destination(code: str, db: Database = Depends(get_db)) -> RedirectResponse:
    row = db.get_url(code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short URL not found")
    now = datetime.now(timezone.utc)
    if row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) <= now:
        raise HTTPException(status.HTTP_410_GONE, "short URL has expired")
    db.record_click(code, day=now.date().isoformat(), accessed_at=now.isoformat())
    return RedirectResponse(row["destination_url"], status_code=status.HTTP_302_FOUND)
