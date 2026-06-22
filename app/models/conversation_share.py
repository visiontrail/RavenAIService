"""
Conversation share model.

A ``ConversationShare`` is the system's first *public, unauthenticated* read
surface. It persists a redacted **snapshot** of a chat session at share time
so the public link is stable and decoupled from the owner's private tables:
deleting / continuing the session never changes an existing share.

Security invariants (see ``conversation_share_service`` and ``app/api/share.py``):

* ``token`` is a high-entropy, unguessable id (``secrets.token_urlsafe(16)``);
  ``session_id`` / ``user_id`` are NEVER exposed on the public URL or response.
* ``snapshot_json`` is redacted at write time to ``role`` / ``content`` /
  ``created_at`` plus an AI-only ``trace_events`` capture (thinking + tool
  calls) — never run links or owner identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseResponse
from .database import Base, TimestampMixin


class ConversationShare(Base, TimestampMixin):
    """Public, read-only snapshot of a chat session."""

    __tablename__ = "conversation_shares"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="分享ID",
    )
    token: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        comment="公开标识（token_urlsafe，不可猜测，与 session_id 解耦）",
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id"),
        nullable=False,
        index=True,
        comment="来源会话（owner 侧反查 / 去重）",
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="owner，用于权限校验",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="新对话",
        comment="快照时的会话标题",
    )
    snapshot_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        comment="脱敏后的消息数组 JSON：[{role, content, created_at, trace_events?}]",
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="快照消息数",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否有效（撤销置 false，公开端点立即 404）",
    )
    shared_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="最近一次生成 / 更新快照时间",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<ConversationShare id={self.id} token={self.token} "
            f"session_id={self.session_id} is_active={self.is_active}>"
        )


# ==================== Pydantic Schemas ====================


class ShareInfo(BaseModel):
    """Owner-facing share status for a session.

    ``is_active=False`` with empty token/url represents the *unshared* state so
    the owner UI can render a single shape for both states.
    """

    is_active: bool = False
    token: Optional[str] = None
    share_url: Optional[str] = None
    shared_at: Optional[datetime] = None
    message_count: Optional[int] = None


class ShareInfoResponse(BaseResponse):
    """Owner-side share endpoint response."""

    data: ShareInfo


class PublicShareMessage(BaseModel):
    """A single message in the public snapshot.

    ``created_at`` is an ISO-8601 string carried verbatim from ``snapshot_json``.
    ``trace_events`` is the AI-only agent trace (thinking + tool calls) captured
    at share time; it is present only on assistant turns that had a recorded run
    and carries no identity / session / run-id fields by construction. Older
    snapshots predating trace capture simply omit it. No owner identity or
    session fields exist on this model.
    """

    model_config = ConfigDict(extra="ignore")

    role: str
    content: str
    created_at: Optional[str] = None
    trace_events: Optional[list[dict[str, Any]]] = None


class PublicShareResponse(BaseModel):
    """Public, unauthenticated snapshot read response.

    Deliberately NOT a ``BaseResponse`` wrapper and deliberately flat: it
    contains only public fields so no owner identity or internal data can leak.
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    shared_at: datetime
    message_count: int
    messages: list[PublicShareMessage]
