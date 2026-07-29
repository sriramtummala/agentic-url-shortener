import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status

from service.app.codegen import CodeGenerationError, generate_code
from service.app.config import SHORT_CODE_LENGTH, SHORT_CODE_MAX_ATTEMPTS
from service.app.db import Database
from service.app.dependencies import get_db
from service.app.schemas import CreateUrlRequest, CreateUrlResponse, UrlMetadata

router = APIRouter(prefix="/api/urls", tags=["urls"])


def _is_expired(row) -> bool:
    if row["expires_at"] is None:
        return False
    return datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)


@router.post("", response_model=CreateUrlResponse, status_code=status.HTTP_201_CREATED)
def create_url(payload: CreateUrlRequest, db: Database = Depends(get_db)) -> CreateUrlResponse:
    try:
        code = generate_code(db.code_exists, length=SHORT_CODE_LENGTH, max_attempts=SHORT_CODE_MAX_ATTEMPTS)
    except CodeGenerationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    owner_token = secrets.token_urlsafe(24)
    created_at = datetime.now(timezone.utc)
    destination_url = str(payload.destination_url)

    db.insert_url(
        code=code,
        destination_url=destination_url,
        owner_token=owner_token,
        created_at=created_at.isoformat(),
        expires_at=payload.expires_at.isoformat() if payload.expires_at else None,
    )

    return CreateUrlResponse(
        code=code, destination_url=destination_url, owner_token=owner_token,
        created_at=created_at, expires_at=payload.expires_at,
    )


@router.get("/{code}", response_model=UrlMetadata)
def get_url_metadata(code: str, db: Database = Depends(get_db)) -> UrlMetadata:
    row = db.get_url(code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short URL not found")
    if _is_expired(row):
        raise HTTPException(status.HTTP_410_GONE, "short URL has expired")
    return UrlMetadata(
        code=row["code"], destination_url=row["destination_url"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
    )


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_url(code: str, x_owner_token: str = Header(...), db: Database = Depends(get_db)) -> None:
    row = db.get_url(code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "short URL not found")
    if not secrets.compare_digest(row["owner_token"], x_owner_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner token does not match")
    db.delete_url(code)
