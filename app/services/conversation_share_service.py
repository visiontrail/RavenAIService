"""
Conversation share lifecycle: snapshot capture, redaction and public read.

This service owns the single point of redaction for the system's first public,
unauthenticated read surface. Snapshots are built *at write time* from chat
messages keeping only ``role`` / ``content`` / ``created_at`` — owner identity
(``user_id`` / ``username`` / ``email``), ``session_id``, agent trace events and
run links are explicitly dropped and never persisted into ``snapshot_json``.
The public read path returns the stored snapshot verbatim, so redaction can
never drift between write and read.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_share import ConversationShare
from app.models.user import ChatMessage, ChatSession
from app.services.base import BaseService

# Public-snapshot messages keep only these fields. Anything else (trace events,
# run ids, owner identity) MUST NOT leak into ``snapshot_json``.
_ALLOWED_MESSAGE_ROLES = {"user", "ai", "system"}
_TOKEN_BYTES = 16  # secrets.token_urlsafe(16) → ~22 chars, ~128 bit entropy


class ConversationShareService(BaseService):
    """Create, refresh, revoke and publicly read conversation shares."""

    async def _get_owned_session(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        session_id: str,
    ) -> Optional[ChatSession]:
        """Return the (non-deleted) session iff it belongs to ``user_id``.

        Non-owners and unknown sessions both resolve to ``None`` so callers can
        return 404 without revealing whether the session exists.
        """
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_active_share(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> Optional[ConversationShare]:
        stmt = select(ConversationShare).where(
            ConversationShare.session_id == session_id,
            ConversationShare.user_id == user_id,
            ConversationShare.is_active == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def _build_snapshot(
        self,
        db: AsyncSession,
        *,
        session_id: str,
    ) -> list[dict]:
        """Build the redacted message snapshot for a session.

        Only ``role`` / ``content`` / ``created_at`` survive; ``created_at`` is
        serialized to an ISO-8601 string so the public read is a pure
        passthrough of ``snapshot_json``.
        """
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        snapshot: list[dict] = []
        for record in result.scalars().all():
            role = record.role if record.role in _ALLOWED_MESSAGE_ROLES else "user"
            snapshot.append(
                {
                    "role": role,
                    "content": record.content or "",
                    "created_at": (
                        record.created_at.isoformat() if record.created_at else None
                    ),
                }
            )
        return snapshot

    async def _generate_unique_token(self, db: AsyncSession) -> str:
        """Generate a high-entropy token, retrying on the rare unique clash."""
        for _ in range(5):
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            existing = await db.execute(
                select(ConversationShare.id).where(ConversationShare.token == token)
            )
            if existing.scalar_one_or_none() is None:
                return token
        # Extremely unlikely; surface rather than risk silently reusing.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法生成唯一的分享标识，请重试",
        )

    async def create_or_refresh_share(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> ConversationShare:
        """Create a new share or refresh the session's existing active share.

        Validates ownership (404 for non-owner / unknown) and non-emptiness
        (422 for a 0-message session). On an existing active share the same
        ``token`` is reused and ``snapshot_json`` / ``title`` / ``message_count``
        / ``shared_at`` are refreshed — never a second active row.
        """
        session = await self._get_owned_session(
            db, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在",
            )

        snapshot = await self._build_snapshot(db, session_id=session_id)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="空会话无法分享",
            )

        snapshot_json = json.dumps(snapshot, ensure_ascii=False)
        now = datetime.utcnow()

        share = await self._get_active_share(
            db, session_id=session_id, user_id=user_id
        )
        if share is not None:
            share.title = session.title
            share.snapshot_json = snapshot_json
            share.message_count = len(snapshot)
            share.shared_at = now
        else:
            share = ConversationShare(
                token=await self._generate_unique_token(db),
                session_id=session_id,
                user_id=user_id,
                title=session.title,
                snapshot_json=snapshot_json,
                message_count=len(snapshot),
                is_active=True,
                shared_at=now,
            )
            db.add(share)

        await db.flush()
        await db.refresh(share)
        return share

    async def get_share_for_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> Optional[ConversationShare]:
        """Return the current active share for an owned session, else None.

        Validates ownership so a non-owner / unknown session resolves to None
        (the API returns 404), never leaking existence.
        """
        session = await self._get_owned_session(
            db, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在",
            )
        return await self._get_active_share(
            db, session_id=session_id, user_id=user_id
        )

    async def revoke_share(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> bool:
        """Soft-revoke the session's active share (``is_active=False``).

        Returns True if a share was revoked, False if there was no active share.
        Raises 404 if the session is not owned by ``user_id``.
        """
        session = await self._get_owned_session(
            db, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在",
            )
        share = await self._get_active_share(
            db, session_id=session_id, user_id=user_id
        )
        if share is None:
            return False
        share.is_active = False
        await db.flush()
        return True

    async def get_public_snapshot(
        self,
        db: AsyncSession,
        *,
        token: str,
    ) -> Optional[dict]:
        """Return the public snapshot for a token, or None.

        Only ``is_active=True`` records resolve; revoked or unknown tokens both
        return None so the public endpoint can 404 without revealing whether the
        token ever existed. The returned dict contains only public fields.
        """
        result = await db.execute(
            select(ConversationShare).where(
                ConversationShare.token == token,
                ConversationShare.is_active == True,  # noqa: E712
            )
        )
        share = result.scalar_one_or_none()
        if share is None:
            return None

        try:
            messages = json.loads(share.snapshot_json or "[]")
            if not isinstance(messages, list):
                messages = []
        except (ValueError, TypeError):
            messages = []

        return {
            "title": share.title,
            "shared_at": share.shared_at,
            "message_count": share.message_count,
            "messages": messages,
        }


conversation_share_service = ConversationShareService()
