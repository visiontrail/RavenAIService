from __future__ import annotations

import asyncio
from datetime import datetime
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import users as users_api
from app.models.database import Base, get_db
from app.models.user import ChatAgentRun, ChatSession


@pytest.fixture
def client_with_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat-sessions.db'}")

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = FastAPI()
    application.include_router(users_api.router)
    application.dependency_overrides[get_db] = _get_db

    with TestClient(application) as test_client:
        yield test_client, factory

    asyncio.run(engine.dispose())


def _register(client: TestClient) -> tuple[str, str]:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={"username": "history_user", "password": "secret123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    return data["token"], data["user"]["id"]


def test_chat_session_summary_includes_latest_agent_kind(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client)
    session_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    async def _seed() -> None:
        async with factory() as db:
            db.add(
                ChatSession(
                    id=session_id,
                    user_id=user_id,
                    title="项目专家历史",
                    last_message_at=datetime.utcnow(),
                    message_count=2,
                )
            )
            db.add(
                ChatAgentRun(
                    id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    owner_scope=f"user:{user_id}",
                    agent_kind="project_expert",
                    status="succeeded",
                    user_message="解释鉴权流程",
                    answer="鉴权流程如下",
                    started_at=datetime.utcnow(),
                    finished_at=datetime.utcnow(),
                )
            )
            await db.commit()

    asyncio.run(_seed())

    resp = client.get(
        "/api/v1/users/chat-sessions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == session_id
    assert rows[0]["run_agent_kind"] == "project_expert"
    assert rows[0]["run_status"] == "succeeded"
    assert rows[0]["active_run_id"] is None
