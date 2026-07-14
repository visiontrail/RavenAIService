"""System announcement API models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemAnnouncement(BaseModel):
    """The single current announcement persisted in runtime settings."""

    id: str = Field(..., min_length=1, max_length=36)
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=4000)
    published_at: datetime
    published_by: str = Field(..., min_length=1, max_length=128)
    active: bool = True


class AnnouncementResponse(BaseModel):
    success: bool = True
    data: Optional[SystemAnnouncement] = None
    message: str = "ok"


class AnnouncementDismissData(BaseModel):
    announcement_id: str
    dismissed: bool = True


class AnnouncementDismissResponse(BaseModel):
    success: bool = True
    data: AnnouncementDismissData
    message: str = "ok"
