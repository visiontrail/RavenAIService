"""Shared admin authorization dependency helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import HTTPException, status
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.security.admin_auth import auth_manager as admin_auth_manager
from app.security.user_auth import user_auth_manager
from app.services.user_service import user_service


@asynccontextmanager
async def _session_from_request(request: Request) -> AsyncIterator[AsyncSession]:
    provider: Callable = request.app.dependency_overrides.get(get_db, get_db)
    generator = provider()
    session = await generator.__anext__()
    try:
        yield session
    finally:
        await generator.aclose()


async def resolve_admin_identity(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession | None = None,
    request: Request | None = None,
) -> str:
    """Accept either a legacy admin token or an admin-role user token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported auth scheme",
        )

    token = credentials.credentials
    try:
        return admin_auth_manager.validate_token(token)
    except HTTPException:
        pass

    user_id, username = user_auth_manager.validate_token(token)
    if db is None:
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        async with _session_from_request(request) as scoped_db:
            return await _validate_admin_user_token(scoped_db, user_id, username)
    return await _validate_admin_user_token(db, user_id, username)


async def _validate_admin_user_token(
    db: AsyncSession,
    user_id: str,
    username: str,
) -> str:
    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active or user.username != username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    if (user.role or "").lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user.username
