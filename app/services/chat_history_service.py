"""
Persistence helpers for user chat history.
"""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import List, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage as ChatMessageSchema
from app.models.user import ChatMessage, ChatSession
from app.services.base import BaseService


class ChatHistoryService(BaseService):
    """Store and load chat history for authenticated users."""

    @staticmethod
    def _title_from_hint(hint: Optional[str], fallback: str = "新对话") -> str:
        if not hint:
            return fallback
        cleaned = " ".join(hint.strip().split())
        return cleaned[:60] if cleaned else fallback

    async def _get_session(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        include_deleted: bool = False,
    ) -> Optional[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(ChatSession.is_deleted == False)  # noqa: E712
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def ensure_session(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        session_id: Optional[str] = None,
    ) -> ChatSession:
        session = None
        if session_id:
            session = await self._get_session(db, user_id, session_id, include_deleted=True)
        if not session:
            session = ChatSession(
                id=session_id or str(uuid.uuid4()),
                user_id=user_id,
                title="新对话",
                last_message_at=datetime.utcnow(),
                message_count=0,
                is_deleted=False,
            )
            db.add(session)
            await db.flush()
            await db.refresh(session)
            return session

        # revive soft-deleted sessions on new activity
        if session.is_deleted:
            session.is_deleted = False
        return session

    async def append_message(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: Optional[str],
        role: str,
        content: str,
        title_hint: Optional[str] = None,
    ) -> tuple[ChatSession, ChatMessage]:
        """Append a single message to a session, creating the session if needed.

        Used by the chat-run flow which persists the user message at run start
        and the assistant message at run terminal, instead of writing both at
        once. Maintains `message_count` / `last_message_at` and revives any
        soft-deleted session.
        """
        session = await self.ensure_session(db, user_id, session_id=session_id)
        if (session.message_count or 0) == 0 and role == "user":
            preferred_title = title_hint or content
            if preferred_title:
                session.title = self._title_from_hint(preferred_title, fallback=session.title)

        record = ChatMessage(session_id=session.id, role=role, content=content)
        db.add(record)
        session.message_count = (session.message_count or 0) + 1
        session.last_message_at = datetime.utcnow()
        await db.flush()
        await db.refresh(session)
        await db.refresh(record)
        return session, record

    async def save_exchange(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        user_content: str,
        ai_content: str,
        title_hint: Optional[str] = None,
        session_title: Optional[str] = None,
    ) -> ChatSession:
        session, _ = await self.append_message(
            db,
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=user_content,
            title_hint=session_title or title_hint,
        )
        session, _ = await self.append_message(
            db,
            user_id=user_id,
            session_id=session.id,
            role="ai",
            content=ai_content,
        )
        return session

    async def list_sessions(self, db: AsyncSession, user_id: str) -> List[ChatSession]:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.is_deleted == False)  # noqa: E712
            .order_by(
                ChatSession.is_pinned.desc(),
                ChatSession.pinned_at.desc(),
                ChatSession.last_message_at.desc(),
                ChatSession.created_at.desc(),
            )
        )
        return result.scalars().all()

    async def fetch_messages(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[ChatMessage]:
        session = await self._get_session(db, user_id, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在或已删除",
            )
        stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def delete_session(self, db: AsyncSession, *, user_id: str, session_id: str) -> bool:
        session = await self._get_session(db, user_id, session_id, include_deleted=True)
        if not session:
            return False
        session.is_deleted = True
        await db.flush()
        return True

    async def update_session_title(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        title: str,
    ) -> bool:
        session = await self._get_session(db, user_id, session_id, include_deleted=False)
        if not session:
            return False
        session.title = self._title_from_hint(title, fallback=session.title)
        await db.flush()
        return True

    async def set_session_pinned(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        pinned: bool,
    ) -> bool:
        session = await self._get_session(db, user_id, session_id, include_deleted=False)
        if not session:
            return False
        session.is_pinned = pinned
        session.pinned_at = datetime.utcnow() if pinned else None
        await db.flush()
        return True

    @staticmethod
    def to_chat_messages(records: Sequence[ChatMessage]) -> List[ChatMessageSchema]:
        """Convert DB records to ChatMessage schema objects."""
        messages: list[ChatMessageSchema] = []
        for record in records:
            role = record.role if record.role in {"user", "ai", "system"} else "user"
            messages.append(ChatMessageSchema(role=role, content=record.content))
        return messages


chat_history_service = ChatHistoryService()
