"""
User and chat history models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseResponse
from .database import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Application user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="用户ID",
    )
    username: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
        comment="用户名（唯一）",
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        comment="展示名称",
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="邮箱",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="密码哈希",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否启用",
    )
    role: Mapped[str] = mapped_column(
        String(32),
        default="user",
        nullable=False,
        comment="用户角色（user/admin）",
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="最近登录时间",
    )

    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} username={self.username}>"


class ChatSession(Base, TimestampMixin):
    """Persisted chat session."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="会话ID",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="所属用户",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="新对话",
        comment="会话标题",
    )
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="最近消息时间",
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="消息数量",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已删除",
    )

    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ChatSession id={self.id} user_id={self.user_id}>"


class ChatMessage(Base, TimestampMixin):
    """Single chat message inside a session."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="消息ID",
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id"),
        nullable=False,
        index=True,
        comment="所属会话",
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="角色（user/ai/system）",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="消息内容",
    )

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ChatMessage id={self.id} session_id={self.session_id} role={self.role}>"


# ==================== Pydantic Schemas ====================


class UserProfile(BaseModel):
    """用户信息展示模型"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True
    role: str = "user"
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserAuthPayload(BaseModel):
    """登录响应数据"""

    token: str
    expires_at: float
    user: UserProfile


class UserListResponse(BaseResponse):
    """用户列表响应"""

    data: list[UserProfile] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    """会话摘要"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    last_message_at: datetime
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatMessageRecord(BaseModel):
    """会话消息模型"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
    updated_at: datetime


class UserAuthResponse(BaseResponse):
    """登录响应"""

    data: UserAuthPayload


class UserDetailResponse(BaseResponse):
    """用户详情响应"""

    data: UserProfile


class ChatSessionListResponse(BaseResponse):
    """会话列表响应"""

    data: list[ChatSessionSummary] = Field(default_factory=list)


class ChatMessagesResponse(BaseResponse):
    """会话消息响应"""

    data: list[ChatMessageRecord] = Field(default_factory=list)
