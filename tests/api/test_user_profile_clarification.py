"""Integration tests for the self-service clarification preferences."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import users as users_api
from app.models.database import Base, get_db


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'users.db'}")

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
        yield test_client

    asyncio.run(engine.dispose())


def _register(client: TestClient, username: str = "clarify_user") -> str:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@example.test",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["token"]


def test_new_user_clarification_defaults(client: TestClient) -> None:
    token = _register(client)
    me = client.get("/api/v1/users/auth/me", headers={"Authorization": f"Bearer {token}"})
    data = me.json()["data"]
    assert data["clarification_enabled"] is True
    assert data["clarification_max_rounds"] == 5
    assert data["clarification_on_timeout"] == "cancel"


def test_update_clarification_prefs_persist(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={
            "clarification_enabled": False,
            "clarification_max_rounds": 8,
            "clarification_on_timeout": "continue",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["clarification_enabled"] is False
    assert data["clarification_max_rounds"] == 8
    assert data["clarification_on_timeout"] == "continue"

    me = client.get("/api/v1/users/auth/me", headers=headers)
    assert me.json()["data"]["clarification_enabled"] is False
    assert me.json()["data"]["clarification_on_timeout"] == "continue"


def test_invalid_on_timeout_coerced_to_cancel(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"clarification_on_timeout": "weird"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["clarification_on_timeout"] == "cancel"


def test_out_of_range_max_rounds_rejected(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"clarification_max_rounds": 999},
        headers=headers,
    )
    # Field constraint (ge=0, le=20) rejects out-of-range values at validation.
    assert resp.status_code == 422
