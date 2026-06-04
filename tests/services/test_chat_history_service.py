"""Unit tests for chat_history_service.append_message and save_exchange."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base
from app.models.user import ChatSession, User
from app.services.chat_history_service import chat_history_service


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest_asyncio.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        id=str(uuid.uuid4()),
        username=f"u-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        is_active=True,
        role="user",
    )
    session.add(u)
    await session.commit()
    return u


@pytest.mark.asyncio
async def test_append_user_then_ai_increments_count(session: AsyncSession, user: User):
    new_session_id = str(uuid.uuid4())
    chat_session, _ = await chat_history_service.append_message(
        session,
        user_id=user.id,
        session_id=new_session_id,
        role="user",
        content="hello there",
    )
    assert chat_session.message_count == 1
    assert chat_session.title.startswith("hello")  # title derived from first user message

    chat_session, _ = await chat_history_service.append_message(
        session,
        user_id=user.id,
        session_id=new_session_id,
        role="ai",
        content="hi back",
    )
    assert chat_session.message_count == 2


@pytest.mark.asyncio
async def test_append_first_user_message_preserves_preseeded_summary_title(
    session: AsyncSession, user: User
):
    sid = str(uuid.uuid4())
    seeded = await chat_history_service.ensure_session(
        session,
        user.id,
        session_id=sid,
    )
    await chat_history_service.update_session_title(
        session,
        user_id=user.id,
        session_id=seeded.id,
        title="轻量模型摘要标题",
    )

    chat_session, _ = await chat_history_service.append_message(
        session,
        user_id=user.id,
        session_id=sid,
        role="user",
        content="用户输入的长问题不应该覆盖摘要标题",
    )

    assert chat_session.message_count == 1
    assert chat_session.title == "轻量模型摘要标题"


@pytest.mark.asyncio
async def test_append_message_revives_soft_deleted_session(
    session: AsyncSession, user: User
):
    sid = str(uuid.uuid4())
    chat_session, _ = await chat_history_service.append_message(
        session, user_id=user.id, session_id=sid, role="user", content="first"
    )
    # soft-delete
    chat_session.is_deleted = True
    await session.flush()

    chat_session, _ = await chat_history_service.append_message(
        session, user_id=user.id, session_id=sid, role="user", content="second"
    )
    assert chat_session.is_deleted is False
    assert chat_session.message_count == 2


@pytest.mark.asyncio
async def test_save_exchange_still_writes_two_messages(
    session: AsyncSession, user: User
):
    sid = str(uuid.uuid4())
    s = await chat_history_service.save_exchange(
        session,
        user_id=user.id,
        session_id=sid,
        user_content="q",
        ai_content="a",
    )
    assert s.message_count == 2
