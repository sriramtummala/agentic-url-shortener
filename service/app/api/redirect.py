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
    if row["expires_at"] is not None and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "short URL has expired")
    return RedirectResponse(row["destination_url"], status_code=status.HTTP_302_FOUND)
