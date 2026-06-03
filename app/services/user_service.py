"""
User management service.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import normalize as normalize_locale
from app.models.user import User
from app.security.admin_auth import AdminUser
from app.security.user_auth import hash_password, verify_password
from app.services.base import BaseService


VALID_ROLES = ("user", "admin")


def _normalize_role(role: Optional[str]) -> str:
    """Coerce role string to a known value, defaulting to ``user``."""
    if not role:
        return "user"
    value = str(role).strip().lower()
    if value in VALID_ROLES:
        return value
    if value in ("superuser", "ops", "administrator", "root"):
        return "admin"
    return "user"


class UserService(BaseService):
    """Encapsulate user CRUD and authentication."""

    async def get_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        db: AsyncSession,
        *,
        username: str,
        password: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "user",
    ) -> User:
        existing = await self.get_by_username(db, username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在",
            )
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name or username,
            email=email,
            role=_normalize_role(role),
        )
        db.add(user)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="保存用户失败",
            ) from exc
        await db.refresh(user)
        return user

    async def authenticate(
        self,
        db: AsyncSession,
        *,
        username: str,
        password: str,
    ) -> User:
        user = await self.get_by_username(db, username)
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
        user.last_login_at = datetime.utcnow()
        await db.flush()
        await db.refresh(user)
        return user

    async def list_users(self, db: AsyncSession, *, offset: int = 0, limit: int = 50) -> List[User]:
        result = await db.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit),
        )
        return result.scalars().all()

    async def ensure_admin_users(self, db: AsyncSession, admin_users: List[AdminUser]) -> None:
        """Sync admin auth users into users table so they can be managed in UI."""
        if not admin_users:
            return
        dirty = False
        for admin_user in admin_users:
            if not admin_user.username:
                continue
            user = await self.get_by_username(db, admin_user.username)
            expected_is_active = not admin_user.disabled
            if user:
                # Ensure existing users from admin_auth.yaml are tagged as admin role
                if user.role != "admin":
                    user.role = "admin"
                    dirty = True
                continue
            password_hash = (
                admin_user.password_hash
                or (hash_password(admin_user.password) if admin_user.password else None)
                or hash_password(secrets.token_urlsafe(24))
            )
            user = User(
                username=admin_user.username,
                display_name=admin_user.username,
                email=None,
                password_hash=password_hash,
                is_active=expected_is_active,
                role="admin",
            )
            db.add(user)
            dirty = True
        if dirty:
            await db.flush()

    async def update_user(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        is_active: Optional[bool] = None,
        role: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[User]:
        user = await self.get_by_id(db, user_id)
        if not user:
            return None
        if display_name is not None:
            user.display_name = display_name
        if email is not None:
            user.email = email
        if is_active is not None:
            user.is_active = is_active
        if role is not None:
            user.role = _normalize_role(role)
        if language is not None:
            # Coerce unsupported codes to a supported one; never store as-is.
            user.language = normalize_locale(language)
        await db.flush()
        await db.refresh(user)
        return user

    async def set_password(self, db: AsyncSession, user_id: str, new_password: str) -> Optional[User]:
        user = await self.get_by_id(db, user_id)
        if not user:
            return None
        user.password_hash = hash_password(new_password)
        await db.flush()
        await db.refresh(user)
        return user


user_service = UserService()
