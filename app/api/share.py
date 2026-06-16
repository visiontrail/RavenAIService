"""
Public, unauthenticated conversation-share read surface.

This router is the system's first public read API. It MUST NOT depend on any
user authentication and MUST NOT return owner identity or internal data — it
only echoes the redacted snapshot built at share time by
``conversation_share_service``.

The JSON endpoint lives under ``/api/v1/share/{token}`` (the project's public
API convention, e.g. ``/api/v1/releases``) so it can coexist on the same origin
with the SPA's public *page* route ``/share/:token``. ``share_url`` returned to
owners points at that page, not at this JSON endpoint.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.conversation_share import PublicShareResponse
from app.models.database import get_db
from app.services.conversation_share_service import conversation_share_service

router = APIRouter(prefix="/api/v1/share", tags=["对话分享（公开）"])

# Frontend SPA route that renders the public read-only page. ``share_url`` is
# built from the public site root + this path, NOT from the JSON API path.
PUBLIC_SHARE_PAGE_PATH = "/share"


def build_share_url(request: Request, token: str) -> str:
    """Build the full, browser-openable public share URL for ``token``.

    Priority: configured ``PUBLIC_BASE_URL`` → request ``Origin`` header →
    request base URL. This keeps local dev (frontend on a different port) and
    multi-domain deploys correct without hard-coding a host.
    """
    base = (settings.public_base_url or "").strip()
    if not base:
        origin = request.headers.get("origin")
        base = origin.strip() if origin else str(request.base_url)
    base = base.rstrip("/")
    return f"{base}{PUBLIC_SHARE_PAGE_PATH}/{token}"


# ---------------------------------------------------------------------------
# Basic per-IP rate limit (anti token-space scanning).
#
# A fixed-window counter keyed by client IP. In-memory and single-process —
# sufficient as a "basic" scan deterrent per the design; a distributed limiter
# can replace it later without changing the route contract.
# ---------------------------------------------------------------------------
_rate_state: dict[str, tuple[float, int]] = {}
_rate_lock = threading.Lock()


def reset_rate_limit_state() -> None:
    """Clear the in-memory rate-limit counters (used by tests)."""
    with _rate_lock:
        _rate_state.clear()


async def enforce_share_rate_limit(request: Request) -> None:
    """Reject requests from an IP that exceeds the configured window budget."""
    limit = settings.share_public_rate_limit
    window = settings.share_public_rate_window_seconds
    if limit <= 0 or window <= 0:
        return

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        window_start, count = _rate_state.get(client_ip, (now, 0))
        if now - window_start >= window:
            window_start, count = now, 0
        count += 1
        _rate_state[client_ip] = (window_start, count)
        exceeded = count > limit

    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )


@router.get("/{token}", response_model=PublicShareResponse)
async def get_public_share(
    token: str,
    _rate: None = Depends(enforce_share_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> PublicShareResponse:
    """Return the public snapshot for ``token``, or 404.

    Unknown and revoked tokens are indistinguishable (both 404) so existence is
    never disclosed. No authentication is required or consulted.
    """
    snapshot = await conversation_share_service.get_public_snapshot(db, token=token)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="分享不存在或已失效",
        )
    return PublicShareResponse(**snapshot)
