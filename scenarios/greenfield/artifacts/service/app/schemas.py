from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator


class CreateUrlRequest(BaseModel):
    destination_url: HttpUrl
    expires_at: Optional[datetime] = None

    @field_validator("expires_at")
    @classmethod
    def _expires_in_future(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None:
            aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if aware <= datetime.now(timezone.utc):
                raise ValueError("expires_at must be in the future")
        return value


class CreateUrlResponse(BaseModel):
    code: str
    destination_url: str
    owner_token: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class UrlMetadata(BaseModel):
    code: str
    destination_url: str
    created_at: datetime
    expires_at: Optional[datetime] = None
