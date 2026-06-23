"""Metrics query APIs.

Read-only endpoints that expose the aggregation queries in
``app/services/metrics_service.py``:

- ``GET /admin/metrics/overview``           — system-wide token / invocation rollup
- ``GET /admin/metrics/users``              — per-user ranking with pagination
- ``GET /admin/metrics/users/{user_id}``    — single-user detail
- ``GET /admin/metrics/events``             — raw (sanitized) event audit feed
- ``GET /api/v1/users/me/metrics``          — the caller's own metrics only

Admin endpoints reuse the existing admin bearer auth; the self endpoint reuses
the user bearer auth so a user can never read another user's usage. All time /
pagination parsing goes through the shared helpers in this module so defaults and
bounds (default window, max range, max page size) are enforced uniformly and a
caller cannot trigger an unbounded full-table scan (design Decision 5, task 6.4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.api.users import get_current_user
from app.models.database import get_db
from app.models.metrics import (
    RawMetricEventsData,
    RawMetricEventsResponse,
    SelfMetricsResponse,
    SelfMetricsSummary,
    SystemOverview,
    SystemOverviewResponse,
    UserMetricsDetail,
    UserMetricsDetailResponse,
    UserMetricsListData,
    UserMetricsListResponse,
    UserMetricsRow,
)
from app.models.user import ChatSession, User
from app.services import metrics_service

# Two routers: admin endpoints under /admin, the self endpoint under /api/v1.
admin_router = APIRouter(prefix="/admin/metrics", tags=["Metrics"])
self_router = APIRouter(prefix="/api/v1/users", tags=["Metrics"])


# ==================== Shared parsing / validation (task 5.7, 6.4) ====================

# Default look-back window when the caller omits ``from``/``to``.
_DEFAULT_WINDOW_DAYS = 7
# Hard ceiling on the queryable range to keep aggregation bounded.
_MAX_WINDOW_DAYS = 366
# Pagination ceilings.
_MAX_PER_PAGE = 200
_DEFAULT_PER_PAGE_USERS = 20
_DEFAULT_PER_PAGE_EVENTS = 50


def _parse_dt(value: Optional[str], field: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp query param; raise 400 on malformed input."""
    if value is None or value == "":
        return None
    raw = value.strip()
    # Accept a trailing ``Z`` (UTC) which ``fromisoformat`` rejects pre-3.11.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime for '{field}': {value!r} (use ISO-8601)",
        ) from exc
    # Persisted ``occurred_at`` is naive UTC; normalize aware inputs to UTC before
    # dropping tzinfo for a like-for-like compare.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def resolve_time_range(
    from_: Optional[str], to: Optional[str]
) -> Tuple[datetime, datetime]:
    """Resolve and validate a ``[from, to)`` window with sensible defaults/bounds.

    Defaults to the last ``_DEFAULT_WINDOW_DAYS`` days. Rejects an inverted range
    and clamps any window wider than ``_MAX_WINDOW_DAYS`` to that ceiling (measured
    backwards from ``to``) so a single call can never scan the whole table.
    """
    to_time = _parse_dt(to, "to") or datetime.utcnow()
    from_time = _parse_dt(from_, "from")
    if from_time is None:
        from_time = to_time - timedelta(days=_DEFAULT_WINDOW_DAYS)
    if from_time >= to_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'from' must be earlier than 'to'",
        )
    max_from = to_time - timedelta(days=_MAX_WINDOW_DAYS)
    if from_time < max_from:
        from_time = max_from
    return from_time, to_time


def resolve_pagination(
    page: int, per_page: int, default_per_page: int
) -> Tuple[int, int]:
    """Clamp page (>=1) and per_page (1.._MAX_PER_PAGE)."""
    page = max(1, page)
    if per_page <= 0:
        per_page = default_per_page
    per_page = min(per_page, _MAX_PER_PAGE)
    return page, per_page


# ==================== User enrichment helpers ====================


async def _fetch_users(db: AsyncSession, user_ids: List[str]) -> Dict[str, User]:
    if not user_ids:
        return {}
    rows = (
        (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    )
    return {u.id: u for u in rows}


async def _message_counts(db: AsyncSession, user_ids: List[str]) -> Dict[str, int]:
    """Total chat messages per user (sum of session counters, not time-filtered)."""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ChatSession.user_id,
                func.coalesce(func.sum(ChatSession.message_count), 0),
            )
            .where(ChatSession.user_id.in_(user_ids))
            .group_by(ChatSession.user_id)
        )
    ).all()
    return {user_id: int(count or 0) for user_id, count in rows}


# ==================== Admin endpoints ====================


@admin_router.get("/overview", response_model=SystemOverviewResponse)
async def get_system_overview(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: str = Query("day"),
    project_repo_id: Optional[int] = Query(None, ge=1),
    _admin: str = Depends(require_admin),
) -> SystemOverviewResponse:
    """System-wide AI usage rollup + time series for the requested window."""
    from_time, to_time = resolve_time_range(from_, to)
    bucket = metrics_service.normalize_bucket(bucket)
    project_filter = str(project_repo_id) if project_repo_id is not None else None
    agg = await metrics_service.aggregate_system_metrics(
        from_time=from_time,
        to_time=to_time,
        bucket=bucket,
        project_repo_id=project_filter,
    )
    # Compose the AI-usage fact source with business-table summaries.
    chat = await metrics_service.aggregate_chat_metrics(
        from_time=from_time,
        to_time=to_time,
        project_repo_id=project_filter,
    )
    logs = await metrics_service.aggregate_log_metrics(
        from_time=from_time,
        to_time=to_time,
        project_repo_id=project_filter,
    )
    packages = await metrics_service.aggregate_package_metrics(
        from_time=from_time,
        to_time=to_time,
        project_repo_id=project_filter,
    )
    devices = metrics_service.aggregate_device_metrics()
    overview = SystemOverview(
        from_time=from_time,
        to_time=to_time,
        bucket=bucket,
        chat=chat,
        logs=logs,
        packages=packages,
        devices=devices,
        **agg,
    )
    return SystemOverviewResponse(data=overview)


@admin_router.get("/users", response_model=UserMetricsListResponse)
async def list_user_metrics(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    project_repo_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(_DEFAULT_PER_PAGE_USERS, ge=1),
    sort: str = Query("total_tokens"),
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserMetricsListResponse:
    """Per-user token/activity ranking with sorting and pagination."""
    from_time, to_time = resolve_time_range(from_, to)
    page, per_page = resolve_pagination(page, per_page, _DEFAULT_PER_PAGE_USERS)
    project_filter = str(project_repo_id) if project_repo_id is not None else None
    agg = await metrics_service.aggregate_user_metrics_list(
        from_time=from_time,
        to_time=to_time,
        page=page,
        per_page=per_page,
        sort=sort,
        project_repo_id=project_filter,
    )

    user_ids = [r["user_id"] for r in agg["rows"]]
    users = await _fetch_users(db, user_ids)
    msg_counts = await _message_counts(db, user_ids)

    rows: List[UserMetricsRow] = []
    for r in agg["rows"]:
        user = users.get(r["user_id"])
        rows.append(
            UserMetricsRow(
                username=user.username if user else None,
                display_name=user.display_name if user else None,
                role=user.role if user else None,
                message_count=msg_counts.get(r["user_id"], 0),
                **r,
            )
        )

    data = UserMetricsListData(
        from_time=from_time,
        to_time=to_time,
        page=agg["page"],
        per_page=agg["per_page"],
        total=agg["total"],
        sort=agg["sort"],
        rows=rows,
    )
    return UserMetricsListResponse(data=data)


@admin_router.get("/users/{user_id}", response_model=UserMetricsDetailResponse)
async def get_user_metrics_detail(
    user_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: str = Query("day"),
    project_repo_id: Optional[int] = Query(None, ge=1),
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserMetricsDetailResponse:
    """Single-user detail: token series, distributions, status/error groups, events."""
    from_time, to_time = resolve_time_range(from_, to)
    bucket = metrics_service.normalize_bucket(bucket)
    project_filter = str(project_repo_id) if project_repo_id is not None else None
    agg = await metrics_service.aggregate_user_detail(
        user_id=user_id,
        from_time=from_time,
        to_time=to_time,
        bucket=bucket,
        project_repo_id=project_filter,
    )
    users = await _fetch_users(db, [user_id])
    user = users.get(user_id)
    msg_counts = await _message_counts(db, [user_id])

    detail = UserMetricsDetail(
        user_id=user_id,
        username=user.username if user else None,
        display_name=user.display_name if user else None,
        role=user.role if user else None,
        from_time=from_time,
        to_time=to_time,
        bucket=bucket,
        message_count=msg_counts.get(user_id, 0),
        **agg,
    )
    return UserMetricsDetailResponse(data=detail)


@admin_router.get("/events", response_model=RawMetricEventsResponse)
async def list_raw_events(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    project_repo_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(_DEFAULT_PER_PAGE_EVENTS, ge=1),
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RawMetricEventsResponse:
    """Paginated raw (sanitized) event listing for audit/troubleshooting."""
    from_time, to_time = resolve_time_range(from_, to)
    page, per_page = resolve_pagination(page, per_page, _DEFAULT_PER_PAGE_EVENTS)
    agg = await metrics_service.list_metric_events(
        from_time=from_time,
        to_time=to_time,
        event_type=event_type,
        source=source,
        user_id=user_id,
        project_repo_id=str(project_repo_id) if project_repo_id is not None else None,
        page=page,
        per_page=per_page,
    )

    # Enrich each event with its triggering user (username/display_name) so the
    # audit feed shows who triggered the event, not just an opaque user_id.
    event_user_ids = list({e["user_id"] for e in agg["events"] if e.get("user_id")})
    users = await _fetch_users(db, event_user_ids)
    for event in agg["events"]:
        user = users.get(event.get("user_id"))
        event["username"] = user.username if user else None
        event["display_name"] = user.display_name if user else None

    data = RawMetricEventsData(
        from_time=from_time,
        to_time=to_time,
        page=agg["page"],
        per_page=agg["per_page"],
        total=agg["total"],
        events=agg["events"],
    )
    return RawMetricEventsResponse(data=data)


# ==================== Self endpoint ====================


@self_router.get("/me/metrics", response_model=SelfMetricsResponse)
async def get_self_metrics(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    bucket: str = Query("day"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SelfMetricsResponse:
    """Return ONLY the authenticated caller's own metrics summary."""
    from_time, to_time = resolve_time_range(from_, to)
    bucket = metrics_service.normalize_bucket(bucket)
    agg = await metrics_service.aggregate_self_metrics(
        user_id=current_user.id, from_time=from_time, to_time=to_time, bucket=bucket
    )
    msg_counts = await _message_counts(db, [current_user.id])
    summary = SelfMetricsSummary(
        user_id=current_user.id,
        from_time=from_time,
        to_time=to_time,
        bucket=bucket,
        message_count=msg_counts.get(current_user.id, 0),
        **agg,
    )
    return SelfMetricsResponse(data=summary)
