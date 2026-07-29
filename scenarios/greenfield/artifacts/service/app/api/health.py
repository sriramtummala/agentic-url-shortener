from fastapi import APIRouter, Depends, HTTPException, status

from service.app.db import Database
from service.app.dependencies import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(db: Database = Depends(get_db)) -> dict:
    try:
        db.code_exists("__health_check__")
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"database unavailable: {exc}") from exc
    return {"status": "ok"}
