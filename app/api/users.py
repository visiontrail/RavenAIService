"""
User authentication, management, and chat history APIs.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.i18n.deps import LOCALE_HEADER, resolve_locale
from app.i18n.messages import t
from app.models.conversation_share import ShareInfo, ShareInfoResponse
from app.models.database import get_db
from app.models.user import (
    ChatAgentRun,
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
from app.api.share import build_share_url
from app.security.admin_auth import auth_manager as admin_auth_manager
from app.security.user_auth import user_auth_manager
from app.services.ai_chat_service import ai_chat_service
from app.services.chat_history_service import chat_history_service
from app.services.conversation_share_service import conversation_share_service
from app.services.user_service import user_service

router = APIRouter(prefix="/api/v1/users", tags=["用户与会话"])

user_bearer = HTTPBearer(auto_error=False)
admin_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(user_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Require a valid user token."""
    # No authenticated user yet, so resolve the locale for auth errors from the
    # request headers only (explicit app header, then Accept-Language).
    locale = resolve_locale(
        header_locale=request.headers.get(LOCALE_HEADER),
        accept_language=request.headers.get("Accept-Language"),
    )
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("auth.not_logged_in", locale),
        )
    user_id, username = user_auth_manager.validate_token(credentials.credentials)
    user = await user_service.get_by_id(db, user_id)
    if not user or not user.is_active or user.username != username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("auth.user_invalid", locale),
        )
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


async def get_request_locale(
    request: Request,
    current_user=Depends(get_optional_user),
) -> str:
    """Resolve the active locale for the current request.

    Priority: explicit locale header → authenticated user's stored language →
    Accept-Language → default. Always returns a supported code.
    """
    return resolve_locale(
        header_locale=request.headers.get(LOCALE_HEADER),
        accept_language=request.headers.get("Accept-Language"),
        user=current_user,
    )


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

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空")
        return username


class UserRegisterRequest(BaseModel):
    """普通用户注册请求"""

    username: str = Field(..., min_length=3, max_length=128)
    password: str = Field(..., min_length=6, max_length=256)
    display_name: Optional[str] = Field(None, max_length=128)
    email: Optional[str] = Field(None, max_length=255)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        username = value.strip()
        if not username:
            raise ValueError("用户名不能为空")
        if any(ch.isspace() for ch in username):
            raise ValueError("用户名不能包含空白字符")
        return username

    @field_validator("display_name", "email", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


@router.post("/auth/login", response_model=UserAuthResponse)
async def user_login(
    payload: UserLoginRequest,
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserAuthResponse:
    # Ensure admin users from admin_auth.yaml are provisioned with the admin role
    # so they can access the backend management entry after their first login.
    try:
        await user_service.ensure_admin_users(db, admin_auth_manager.list_config_users())
    except Exception:
        pass
    user = await user_service.authenticate(db, username=payload.username, password=payload.password)
    token, expires_at = user_auth_manager.issue_token(user.id, user.username)
    return UserAuthResponse(
        message=t("auth.login_success", locale),
        data=UserAuthPayload(
            token=token,
            expires_at=expires_at,
            user=UserProfile.model_validate(user, from_attributes=True),
        ),
    )


@router.post("/auth/register", response_model=UserAuthResponse, status_code=201)
async def user_register(
    payload: UserRegisterRequest,
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserAuthResponse:
    user = await user_service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        email=payload.email,
        role="user",
    )
    token, expires_at = user_auth_manager.issue_token(user.id, user.username)
    return UserAuthResponse(
        message=t("auth.register_success", locale),
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


class UpdateProfileRequest(BaseModel):
    """当前用户自助更新个人资料请求"""

    display_name: Optional[str] = Field(None, max_length=128)
    email: Optional[str] = Field(None, max_length=255)
    language: Optional[str] = Field(None, max_length=8)


@router.patch("/auth/me", response_model=UserDetailResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    """Allow the authenticated user to update their own profile preferences.

    Unsupported ``language`` codes are coerced to a supported code by the
    service layer rather than rejected, so the UI never gets stuck.
    """
    user = await user_service.update_user(
        db,
        current_user.id,
        display_name=payload.display_name,
        email=payload.email,
        language=payload.language,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("user.not_found", locale)
        )
    await db.commit()
    return UserDetailResponse(
        message=t("user.profile_updated", locale),
        data=UserProfile.model_validate(user, from_attributes=True),
    )


# ==================== Admin user management ====================


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = "user"


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    role: Optional[str] = None


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
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        email=payload.email,
        role=payload.role or "user",
    )
    return UserDetailResponse(
        message=t("user.created", locale),
        data=UserProfile.model_validate(user, from_attributes=True),
    )


@router.patch("/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    _admin: str = Depends(require_admin),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.update_user(
        db,
        user_id,
        display_name=payload.display_name,
        email=payload.email,
        is_active=payload.is_active,
        role=payload.role,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("user.not_found", locale)
        )
    if payload.password:
        user = await user_service.set_password(db, user_id, payload.password)
    return UserDetailResponse(
        message=t("user.updated", locale),
        data=UserProfile.model_validate(user, from_attributes=True),
    )


@router.delete("/{user_id}", response_model=UserDetailResponse)
async def disable_user(
    user_id: str,
    _admin: str = Depends(require_admin),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> UserDetailResponse:
    user = await user_service.update_user(db, user_id, is_active=False)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("user.not_found", locale)
        )
    return UserDetailResponse(
        message=t("user.disabled", locale),
        data=UserProfile.model_validate(user, from_attributes=True),
    )


# ==================== Chat sessions for current user ====================


@router.get("/chat-sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    from datetime import datetime

    from app.services.chat_run_service import chat_run_service
    from app.services.owner_scope import owner_scope_for_user

    sessions = await chat_history_service.list_sessions(db, current_user.id)
    owner_scope = owner_scope_for_user(current_user) or ""
    latest_runs_by_session: dict[str, ChatAgentRun] = {}
    session_ids = [session.id for session in sessions]
    if session_ids:
        runs_result = await db.execute(
            select(ChatAgentRun)
            .where(
                ChatAgentRun.user_id == current_user.id,
                ChatAgentRun.session_id.in_(session_ids),
            )
            .order_by(
                ChatAgentRun.session_id.asc(),
                ChatAgentRun.started_at.desc(),
                ChatAgentRun.created_at.desc(),
            )
        )
        for run in runs_result.scalars().all():
            latest_runs_by_session.setdefault(run.session_id, run)

    summaries: list[ChatSessionSummary] = []
    for session in sessions:
        summary = ChatSessionSummary.model_validate(session, from_attributes=True)
        latest_run = latest_runs_by_session.get(session.id)
        if latest_run is not None:
            summary.run_status = latest_run.status
            summary.run_agent_kind = latest_run.agent_kind
            summary.run_started_at = latest_run.started_at
            summary.run_updated_at = latest_run.finished_at or latest_run.updated_at

        # Overlay the in-memory active run state, scoped strictly to the
        # current user. Anonymous brokers / other users' runs MUST NOT leak
        # into this user's sidebar spinner.
        job = chat_run_service.get_active_job_for_session(owner_scope, session.id)
        if job is not None:
            summary.active_run_id = job.run_id
            summary.run_status = job.status
            summary.run_agent_kind = job.agent_kind
            # ``started_at`` is monotonic seconds; convert via current wall time delta
            # so the frontend can render a relative timestamp.
            import time as _time

            wall_now = _time.time()
            mono_now = _time.monotonic()
            summary.run_started_at = datetime.utcfromtimestamp(
                wall_now - (mono_now - job.started_at)
            )
            summary.run_updated_at = datetime.utcfromtimestamp(
                wall_now - (mono_now - job.updated_at)
            )
        summaries.append(summary)
    return ChatSessionListResponse(message="ok", data=summaries)


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
    runs_result = await db.execute(
        select(ChatAgentRun)
        .where(
            ChatAgentRun.user_id == current_user.id,
            ChatAgentRun.session_id == session_id,
            ChatAgentRun.trace_events_json.is_not(None),
        )
        .order_by(ChatAgentRun.finished_at.asc(), ChatAgentRun.started_at.asc())
    )
    unmatched_runs = list(runs_result.scalars().all())
    messages: list[ChatMessageRecord] = []
    for record in records:
        message = ChatMessageRecord.model_validate(record, from_attributes=True)
        if record.role == "ai" and record.content:
            matched_index: int | None = None
            for idx, run in enumerate(unmatched_runs):
                if (run.answer or "") == record.content:
                    matched_index = idx
                    break
            if matched_index is not None:
                run = unmatched_runs.pop(matched_index)
                trace_events = None
                try:
                    parsed = json.loads(run.trace_events_json or "[]")
                    if isinstance(parsed, list):
                        trace_events = parsed
                except Exception:  # noqa: BLE001
                    trace_events = None
                message.run_id = run.id
                message.run_status = run.status
                message.run_agent_kind = run.agent_kind
                message.trace_events = trace_events
        messages.append(message)
    return ChatMessagesResponse(
        message="ok",
        data=messages,
    )


@router.delete("/chat-sessions/{session_id}", response_model=ChatSessionListResponse)
async def delete_chat_session(
    session_id: str,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    deleted = await chat_history_service.delete_session(db, user_id=current_user.id, session_id=session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("session.not_found", locale)
        )
    sessions = await chat_history_service.list_sessions(db, current_user.id)
    return ChatSessionListResponse(
        message=t("session.deleted", locale),
        data=[ChatSessionSummary.model_validate(s, from_attributes=True) for s in sessions],
    )


class PinSessionRequest(BaseModel):
    """置顶/取消置顶请求"""

    pinned: bool = True


@router.patch("/chat-sessions/{session_id}/pin", response_model=ChatSessionListResponse)
async def pin_chat_session(
    session_id: str,
    payload: PinSessionRequest,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    updated = await chat_history_service.set_session_pinned(
        db,
        user_id=current_user.id,
        session_id=session_id,
        pinned=payload.pinned,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("session.not_found", locale)
        )
    sessions = await chat_history_service.list_sessions(db, current_user.id)
    return ChatSessionListResponse(
        message=t("session.pinned" if payload.pinned else "session.unpinned", locale),
        data=[ChatSessionSummary.model_validate(s, from_attributes=True) for s in sessions],
    )


class RenameSessionRequest(BaseModel):
    """重命名会话请求"""

    title: str


@router.patch("/chat-sessions/{session_id}/rename", response_model=ChatSessionListResponse)
async def rename_chat_session(
    session_id: str,
    payload: RenameSessionRequest,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    if not payload.title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=t("session.title_empty", locale),
        )
    updated = await chat_history_service.update_session_title(
        db,
        user_id=current_user.id,
        session_id=session_id,
        title=payload.title.strip(),
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("session.not_found", locale)
        )
    await db.commit()
    sessions = await chat_history_service.list_sessions(db, current_user.id)
    return ChatSessionListResponse(
        message=t("session.renamed", locale),
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
    locale: str = Depends(get_request_locale),
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
                ai_chat_service.generate_session_title(
                    payload.user_content,
                    payload.ai_content,
                    user_id=str(current_user.id),
                    session_id=session_id,
                    locale=locale,
                ),
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
        message=t("chat.message_saved", locale),
        session_id=session.id,
    )


# ==================== Conversation sharing (owner side) ====================


def _share_info(request: Request, share) -> ShareInfo:
    """Build the owner-facing ShareInfo for an active share record."""
    return ShareInfo(
        is_active=share.is_active,
        token=share.token,
        share_url=build_share_url(request, share.token),
        shared_at=share.shared_at,
        message_count=share.message_count,
    )


@router.post("/chat-sessions/{session_id}/share", response_model=ShareInfoResponse)
async def create_chat_share(
    session_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> ShareInfoResponse:
    """Create or refresh a public share for the current user's session.

    Empty sessions are rejected (422); non-owners / unknown sessions get 404.
    """
    share = await conversation_share_service.create_or_refresh_share(
        db, session_id=session_id, user_id=current_user.id
    )
    await db.commit()
    return ShareInfoResponse(
        message=t("share.created", locale),
        data=_share_info(request, share),
    )


@router.get("/chat-sessions/{session_id}/share", response_model=ShareInfoResponse)
async def get_chat_share(
    session_id: str,
    request: Request,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareInfoResponse:
    """Return the current share status for the session (unshared state if none)."""
    share = await conversation_share_service.get_share_for_session(
        db, session_id=session_id, user_id=current_user.id
    )
    if share is None:
        return ShareInfoResponse(message="ok", data=ShareInfo(is_active=False))
    return ShareInfoResponse(message="ok", data=_share_info(request, share))


@router.delete("/chat-sessions/{session_id}/share", response_model=ShareInfoResponse)
async def revoke_chat_share(
    session_id: str,
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
    db: AsyncSession = Depends(get_db),
) -> ShareInfoResponse:
    """Revoke the session's active share; the public link 404s immediately."""
    await conversation_share_service.revoke_share(
        db, session_id=session_id, user_id=current_user.id
    )
    await db.commit()
    return ShareInfoResponse(message=t("share.revoked", locale), data=ShareInfo(is_active=False))
