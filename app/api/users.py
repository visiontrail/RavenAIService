"""
User authentication, management, and chat history APIs.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import get_db
from app.models.user import (
    ChatMessageRecord,
    ChatMessagesResponse,
    ChatSessionListResponse,
    ChatSessionSummary,
    UserAuthPayload,
    UserAuthResponse,
    UserDetailResponse,
    UserListResponse,
    UserProfile,
)
from app.security.admin_auth import auth_manager as admin_auth_manager
from app.security.user_auth import user_auth_manager
from app.services.ai_chat_service import ai_chat_service
from app.services.chat_history_service import chat_history_service
from app.services.user_service import user_service

router = APIRouter(prefix="/api/v1/users", tags=["用户与会话"])

user_bearer = HTTPBearer(auto_error=False)
admin_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(user_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Require a valid user token."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    user_id, username = user_auth_manager.validate_token(credentials.credentials)
    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active or user.username != username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户无效或已禁用")
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(user_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user if token is provided, otherwise None."""
    if not credentials:
        return None
    try:
        user_id, username = user_auth_manager.validate_token(credentials.credentials)
    except HTTPException:
        return None
    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active or user.username != username:
        return None
    return user


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(admin_bearer)) -> str:
    """Validate admin bearer token."""
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
    return admin_auth_manager.validate_token(credentials.credentials)


# ==================== Auth endpoints ====================


class UserLoginRequest(BaseModel):
    """登录请求"""

    username: str
    password: str


@router.post("/auth/login", response_model=UserAuthResponse)
async def user_login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)) -> UserAuthResponse:
    user = await user_service.authenticate(db, username=payload.username, password=payload.password)
    token, expires_at = user_auth_manager.issue_token(user.id, user.username)
    return UserAuthResponse(
        message="登录成功",
        data=UserAuthPayload(
            token=token,
            expires_at=expires_at,
            user=UserProfile.model_validate(user, from_attributes=True),
        ),
    )


@router.get("/auth/me", response_model=UserDetailResponse)
async def get_profile(current_user=Depends(get_current_user)) -> UserDetailResponse:
    return UserDetailResponse(
        message="ok",
        data=UserProfile.model_validate(current_user, from_attributes=True),
    )


# ==================== Admin user management ====================


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.get("", response_model=UserListResponse)
async def list_users(
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    await user_service.ensure_admin_users(db, admin_auth_manager.list_config_users())
    users = await user_service.list_users(db)
    return UserListResponse(
        message="ok",
        data=[UserProfile.model_validate(u, from_attributes=True) for u in users],
    )


@router.post("", response_model=UserDetailResponse, status_code=201)
async def create_user(
    payload: CreateUserRequest,
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        email=payload.email,
    )
    return UserDetailResponse(
        message="用户创建成功",
        data=UserProfile.model_validate(user, from_attributes=True),
    )


@router.patch("/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.update_user(
        db,
        user_id,
        display_name=payload.display_name,
        email=payload.email,
        is_active=payload.is_active,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if payload.password:
        user = await user_service.set_password(db, user_id, payload.password)
    return UserDetailResponse(
        message="用户已更新",
        data=UserProfile.model_validate(user, from_attributes=True),
    )


@router.delete("/{user_id}", response_model=UserDetailResponse)
async def disable_user(
    user_id: str,
    _admin: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.update_user(db, user_id, is_active=False)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return UserDetailResponse(
        message="用户已禁用",
        data=UserProfile.model_validate(user, from_attributes=True),
    )


# ==================== Chat sessions for current user ====================


@router.get("/chat-sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    sessions = await chat_history_service.list_sessions(db, current_user.id)
    return ChatSessionListResponse(
        message="ok",
        data=[ChatSessionSummary.model_validate(s, from_attributes=True) for s in sessions],
    )


@router.get("/chat-sessions/{session_id}/messages", response_model=ChatMessagesResponse)
async def get_chat_messages(
    session_id: str,
    limit: Optional[int] = Query(None, ge=1, le=500),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessagesResponse:
    records = await chat_history_service.fetch_messages(
        db,
        user_id=current_user.id,
        session_id=session_id,
        limit=limit,
    )
    return ChatMessagesResponse(
        message="ok",
        data=[ChatMessageRecord.model_validate(r, from_attributes=True) for r in records],
    )


@router.delete("/chat-sessions/{session_id}", response_model=ChatSessionListResponse)
async def delete_chat_session(
    session_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    deleted = await chat_history_service.delete_session(db, user_id=current_user.id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    sessions = await chat_history_service.list_sessions(db, current_user.id)
    return ChatSessionListResponse(
        message="会话已删除",
        data=[ChatSessionSummary.model_validate(s, from_attributes=True) for s in sessions],
    )


class SaveMessagesRequest(BaseModel):
    """保存消息请求"""

    user_content: str
    ai_content: str
    title_hint: Optional[str] = None


class SaveMessagesResponse(BaseModel):
    """保存消息响应"""

    message: str
    session_id: str


@router.post("/chat-sessions/{session_id}/messages", response_model=SaveMessagesResponse)
async def save_messages(
    session_id: str,
    payload: SaveMessagesRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SaveMessagesResponse:
    """保存用户消息和AI回复到指定会话"""
    session = await chat_history_service.save_exchange(
        db,
        user_id=current_user.id,
        session_id=session_id,
        user_content=payload.user_content,
        ai_content=payload.ai_content,
        title_hint=None,
    )
    if (session.message_count or 0) <= 2:
        try:
            session_title = await asyncio.wait_for(
                ai_chat_service.generate_session_title(payload.user_content, payload.ai_content),
                timeout=8,
            )
            if session_title:
                await chat_history_service.update_session_title(
                    db,
                    user_id=current_user.id,
                    session_id=session_id,
                    title=session_title,
                )
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
    await db.commit()
    return SaveMessagesResponse(
        message="消息已保存",
        session_id=session.id,
    )
