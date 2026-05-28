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


def test_register_creates_user_and_returns_auth_token(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "alice",
            "password": "secret123",
            "display_name": "Alice",
            "email": "alice@example.test",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "注册成功"
    assert body["data"]["token"]
    assert body["data"]["user"]["username"] == "alice"
    assert body["data"]["user"]["display_name"] == "Alice"
    assert body["data"]["user"]["role"] == "user"

    me_resp = client.get(
        "/api/v1/users/auth/me",
        headers={"Authorization": f"Bearer {body['data']['token']}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    assert me_resp.json()["data"]["username"] == "alice"


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    payload = {"username": "bob", "password": "secret123"}

    first_resp = client.post("/api/v1/users/auth/register", json=payload)
    assert first_resp.status_code == 201, first_resp.text

    duplicate_resp = client.post("/api/v1/users/auth/register", json=payload)
    assert duplicate_resp.status_code == 400, duplicate_resp.text
    assert duplicate_resp.json()["detail"] == "用户名已存在"


def test_register_validates_username_and_password(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={"username": "bad name", "password": "123"},
    )

    assert resp.status_code == 422, resp.text
