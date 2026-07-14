"""Shared admin authorization dependency helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, List

from fastapi import HTTPException, status
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db
from app.security.admin_auth import auth_manager as admin_auth_manager
from app.security.user_auth import user_auth_manager
from app.services import project_repo_member_service
from app.services.user_service import user_service


# Admin navigation keys understood by the frontend. Global admins receive all of
# them; project-member admins receive only the project surfaces.
ADMIN_NAV_KEYS_ALL: List[str] = [
    "prompts",
    "users",
    "announcements",
    "releases",
    "project-repos",
    "agent-skills",
    "model-settings",
    "metrics",
]
ADMIN_NAV_KEYS_PROJECT_MEMBER: List[str] = ["project-repos"]

ACCESS_LEVEL_GLOBAL_ADMIN = "global_admin"
ACCESS_LEVEL_PROJECT_MEMBER = "project_member"


@dataclass
class AdminPrincipal:
    """Structured admin identity used by admin authorization dependencies.

    ``is_global_admin`` distinguishes legacy admin tokens and ``role == "admin"``
    user tokens (full access) from project-member admins (scoped to their own
    enabled projects).
    """

    kind: str  # "legacy_admin" | "admin_user" | "project_member"
    username: str
    user_id: str | None = None
    is_global_admin: bool = False
    allowed_project_ids: List[int] = field(default_factory=list)
    allowed_project_codes: List[str] = field(default_factory=list)

    @property
    def access_level(self) -> str:
        return (
            ACCESS_LEVEL_GLOBAL_ADMIN
            if self.is_global_admin
            else ACCESS_LEVEL_PROJECT_MEMBER
        )

    @property
    def allowed_nav_keys(self) -> List[str]:
        return (
            list(ADMIN_NAV_KEYS_ALL)
            if self.is_global_admin
            else list(ADMIN_NAV_KEYS_PROJECT_MEMBER)
        )


@asynccontextmanager
async def _session_from_request(request: Request) -> AsyncIterator[AsyncSession]:
    provider: Callable = request.app.dependency_overrides.get(get_db, get_db)
    generator = provider()
    session = await generator.__anext__()
    try:
        yield session
    finally:
        await generator.aclose()


def _ensure_bearer(credentials: HTTPAuthorizationCredentials | None) -> str:
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
    return credentials.credentials


async def resolve_admin_identity(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession | None = None,
    request: Request | None = None,
) -> str:
    """Accept either a legacy admin token or an admin-role user token."""
    token = _ensure_bearer(credentials)
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


async def resolve_admin_principal(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession | None = None,
    request: Request | None = None,
) -> AdminPrincipal:
    """Resolve a structured admin principal.

    Order of resolution:
      1. Legacy admin token -> global admin principal.
      2. ``role == "admin"`` user token -> global admin principal.
      3. Active user token with at least one enabled project membership ->
         project-member admin principal scoped to those projects.

    Active users with no enabled membership are rejected with 403; missing or
    malformed credentials with 401.
    """
    token = _ensure_bearer(credentials)

    # 1. Legacy admin token.
    try:
        username = admin_auth_manager.validate_token(token)
        return AdminPrincipal(
            kind="legacy_admin",
            username=username,
            is_global_admin=True,
        )
    except HTTPException:
        pass

    # 2/3. User token.
    user_id, username = user_auth_manager.validate_token(token)
    if db is None:
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        async with _session_from_request(request) as scoped_db:
            return await _resolve_user_principal(scoped_db, user_id, username)
    return await _resolve_user_principal(db, user_id, username)


async def _resolve_user_principal(
    db: AsyncSession,
    user_id: str,
    username: str,
) -> AdminPrincipal:
    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active or user.username != username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if (user.role or "").lower() == "admin":
        return AdminPrincipal(
            kind="admin_user",
            username=user.username,
            user_id=user.id,
            is_global_admin=True,
        )

    repos = await project_repo_member_service.list_user_enabled_projects(db, user.id)
    if not repos:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Project membership required",
        )

    return AdminPrincipal(
        kind="project_member",
        username=user.username,
        user_id=user.id,
        is_global_admin=False,
        allowed_project_ids=[r.id for r in repos],
        allowed_project_codes=[r.project_code for r in repos],
    )
