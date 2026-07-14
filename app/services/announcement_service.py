"""Current system announcement persistence and validation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

from app.models.announcement import SystemAnnouncement
from app.services import runtime_settings_service


logger = logging.getLogger(__name__)

RUNTIME_KEY = "system_announcement"


def get_current(*, include_inactive: bool = True) -> Optional[SystemAnnouncement]:
    """Return the validated current announcement, if one is configured."""
    raw = runtime_settings_service.get_all().get(RUNTIME_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        announcement = SystemAnnouncement.model_validate(raw)
    except ValidationError as exc:
        logger.warning("Ignoring invalid runtime system announcement: %s", exc)
        return None
    if not include_inactive and not announcement.active:
        return None
    return announcement


def publish(*, title: str, content: str, published_by: str) -> SystemAnnouncement:
    """Replace the current announcement with a newly versioned active one."""
    announcement = SystemAnnouncement(
        id=str(uuid.uuid4()),
        title=title.strip(),
        content=content.strip(),
        published_at=datetime.now(timezone.utc),
        published_by=published_by.strip(),
        active=True,
    )
    runtime_settings_service.update(
        {RUNTIME_KEY: announcement.model_dump(mode="json")}
    )
    return announcement


def deactivate() -> Optional[SystemAnnouncement]:
    """Deactivate the current announcement while retaining it for Admin UI."""
    current = get_current(include_inactive=True)
    if current is None:
        return None
    if not current.active:
        return current
    inactive = current.model_copy(update={"active": False})
    runtime_settings_service.update(
        {RUNTIME_KEY: inactive.model_dump(mode="json")}
    )
    return inactive
