"""API tests for conversation sharing (owner side + public read side).

Owner side (authenticated): create / get / revoke closed loop, empty-session
rejection, non-owner isolation. Public side (unauthenticated): readable without
any Authorization header, no identity / internal fields leak, 404 hides
existence, and per-IP rate limiting kicks in.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import share as share_api
from app.api import users as users_api
from app.config import settings
from app.models.database import Base, get_db
from app.models.user import ChatAgentRun, ChatMessage, ChatSession


@pytest.fixture
def client_with_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shares.db'}")

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
    application.include_router(share_api.router)
    application.dependency_overrides[get_db] = _get_db

    share_api.reset_rate_limit_state()
    with TestClient(application) as test_client:
        yield test_client, factory

    asyncio.run(engine.dispose())


def _register(client: TestClient, username: str) -> tuple[str, str]:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@example.test",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    return data["token"], data["user"]["id"]


def _seed_session(factory, *, user_id: str, with_messages: bool = True) -> str:
    session_id = str(uuid.uuid4())

    async def _seed() -> None:
        async with factory() as db:
            db.add(
                ChatSession(
                    id=session_id,
                    user_id=user_id,
                    title="排障对话",
                    last_message_at=datetime.utcnow(),
                    message_count=2 if with_messages else 0,
                )
            )
            if with_messages:
                db.add(ChatMessage(session_id=session_id, role="user", content="你好"))
                db.add(ChatMessage(session_id=session_id, role="ai", content="```mermaid\ngraph TD;A-->B;\n```"))
            await db.commit()

    asyncio.run(_seed())
    return session_id


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Owner side
# ---------------------------------------------------------------------------


def test_create_get_revoke_closed_loop(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_a")
    session_id = _seed_session(factory, user_id=user_id)

    # create
    created = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["is_active"] is True
    share_token = data["token"]
    assert share_token
    assert data["message_count"] == 2
    assert data["share_url"].endswith(f"/share/{share_token}")

    # get returns the same active share
    got = client.get(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    assert got.status_code == 200
    assert got.json()["data"]["token"] == share_token

    # revoke
    revoked = client.delete(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"]["is_active"] is False

    # get now reports unshared state
    after = client.get(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    assert after.status_code == 200
    assert after.json()["data"]["is_active"] is False
    assert after.json()["data"]["token"] is None


def test_create_share_rejects_empty_session(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_empty")
    session_id = _seed_session(factory, user_id=user_id, with_messages=False)

    resp = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    assert resp.status_code == 422, resp.text


def test_non_owner_cannot_manage_share(client_with_db) -> None:
    client, factory = client_with_db
    token_a, user_a = _register(client, "owner_a")
    token_b, _user_b = _register(client, "owner_b")
    session_id = _seed_session(factory, user_id=user_a)

    # B cannot create / get / revoke A's share
    assert client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token_b)
    ).status_code == 404
    assert client.get(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token_b)
    ).status_code == 404
    assert client.delete(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token_b)
    ).status_code == 404


def test_refresh_reuses_token(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_refresh")
    session_id = _seed_session(factory, user_id=user_id)

    first = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]
    second = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]
    assert first["token"] == second["token"]


# ---------------------------------------------------------------------------
# Public side
# ---------------------------------------------------------------------------


def test_public_read_without_auth_and_no_identity_leak(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_pub")
    session_id = _seed_session(factory, user_id=user_id)
    share_token = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]["token"]

    # No Authorization header at all.
    resp = client.get(f"/api/v1/share/{share_token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "排障对话"
    assert body["message_count"] == 2
    assert [m["role"] for m in body["messages"]] == ["user", "ai"]

    # No identity / internal fields anywhere in the response.
    import json as _json

    raw = _json.dumps(body)
    for forbidden in ("user_id", "username", "email", "session_id", "trace", user_id):
        assert forbidden not in raw
    for message in body["messages"]:
        assert set(message.keys()) == {"role", "content", "created_at"}


def test_public_read_carries_ai_trace_events(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_trace")
    session_id = _seed_session(factory, user_id=user_id)
    # The seeded AI message content; the run's answer must equal it to bind.
    ai_answer = "```mermaid\ngraph TD;A-->B;\n```"
    events = [
        {"type": "thinking_end", "task_id": "t", "seq": 1, "timestamp": 1.0, "text": "reasoning"},
        {
            "type": "step_start",
            "task_id": "t",
            "seq": 2,
            "timestamp": 2.0,
            "step_id": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
        {"type": "step_end", "task_id": "t", "seq": 3, "timestamp": 3.0, "step_id": "s1", "status": "ok"},
        {"type": "run_complete", "task_id": "t", "seq": 4, "timestamp": 4.0},
    ]

    async def _seed_run() -> None:
        async with factory() as db:
            db.add(
                ChatAgentRun(
                    session_id=session_id,
                    user_id=user_id,
                    agent_kind="log_analysis",
                    status="succeeded",
                    answer=ai_answer,
                    trace_events_json=json.dumps(events),
                )
            )
            await db.commit()

    asyncio.run(_seed_run())

    share_token = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]["token"]

    body = client.get(f"/api/v1/share/{share_token}").json()
    user_msg, ai_msg = body["messages"]
    # Trace is AI-only and carried verbatim onto the public snapshot.
    assert "trace_events" not in user_msg
    assert ai_msg["trace_events"] == events

    # Trace is now public, but owner / session / run identity still must not leak.
    raw = json.dumps(body)
    for forbidden in ("user_id", "username", "email", "session_id", "run_id", user_id):
        assert forbidden not in raw


def test_public_unknown_token_returns_404(client_with_db) -> None:
    client, _factory = client_with_db
    resp = client.get("/api/v1/share/this-token-does-not-exist")
    assert resp.status_code == 404


def test_public_revoked_token_returns_404(client_with_db) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_revoke_pub")
    session_id = _seed_session(factory, user_id=user_id)
    share_token = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]["token"]

    assert client.get(f"/api/v1/share/{share_token}").status_code == 200
    client.delete(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    )
    # Immediately 404 after revoke.
    assert client.get(f"/api/v1/share/{share_token}").status_code == 404


def test_public_endpoint_rate_limited(client_with_db, monkeypatch) -> None:
    client, factory = client_with_db
    token, user_id = _register(client, "owner_rl")
    session_id = _seed_session(factory, user_id=user_id)
    share_token = client.post(
        f"/api/v1/users/chat-sessions/{session_id}/share", headers=_auth(token)
    ).json()["data"]["token"]

    monkeypatch.setattr(settings, "share_public_rate_limit", 2)
    monkeypatch.setattr(settings, "share_public_rate_window_seconds", 60)
    share_api.reset_rate_limit_state()

    assert client.get(f"/api/v1/share/{share_token}").status_code == 200
    assert client.get(f"/api/v1/share/{share_token}").status_code == 200
    # Third request in the window exceeds the budget.
    assert client.get(f"/api/v1/share/{share_token}").status_code == 429
