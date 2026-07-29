from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from service.app.db import Database
from service.app.dependencies import get_db
from service.app.schemas import AnalyticsResponse, DailyClicks

router = APIRouter(prefix="/api/urls", tags=["analytics"])


@router.get("/{code}/analytics", response_model=AnalyticsResponse)
def get_analytics(code: str, db: Database = Depends(get_db)) -> AnalyticsResponse:
    row = db.get_url(code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short URL not found")
    series = db.get_click_series(code)
    return AnalyticsResponse(
        code=code,
        click_count=row["click_count"],
        last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]) if row["last_accessed_at"] else None,
        daily_clicks=[DailyClicks(day=r["day"], count=r["count"]) for r in series],
    )
