from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import users as users_api
from app.config import settings
from app.models.database import Base, get_db


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        settings,
        "runtime_settings_path",
        str(tmp_path / "runtime_settings.json"),
    )
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
    application.dependency_overrides[users_api.require_admin] = lambda: "admin"

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
    assert body["data"]["user"]["profile_role"] == "developer"
    assert body["data"]["user"]["last_login_at"]

    me_resp = client.get(
        "/api/v1/users/auth/me",
        headers={"Authorization": f"Bearer {body['data']['token']}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    assert me_resp.json()["data"]["username"] == "alice"


def test_register_rejects_duplicate_username(client: TestClient) -> None:
    payload = {
        "username": "bob",
        "password": "secret123",
        "email": "bob@example.test",
    }

    first_resp = client.post("/api/v1/users/auth/register", json=payload)
    assert first_resp.status_code == 201, first_resp.text

    duplicate_resp = client.post("/api/v1/users/auth/register", json=payload)
    assert duplicate_resp.status_code == 400, duplicate_resp.text
    assert duplicate_resp.json()["detail"] == "用户名已存在"


def test_register_validates_username_and_password(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "bad name",
            "password": "123",
            "email": "bad@example.test",
        },
    )

    assert resp.status_code == 422, resp.text


def test_register_requires_email(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={"username": "charlie", "password": "secret123"},
    )

    assert resp.status_code == 422, resp.text


def test_register_rejects_invalid_email_format(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "charlie",
            "password": "secret123",
            "email": "not-an-email",
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "请输入有效的邮箱地址"


def test_admin_email_regex_and_message_are_enforced_on_registration(
    client: TestClient,
) -> None:
    settings_resp = client.put(
        "/api/v1/users/registration-email-settings",
        json={
            "email_regex": r"^[A-Za-z0-9._%+-]+@example\.com$",
            "email_validation_message": "请使用 example.com 企业邮箱注册",
        },
    )
    assert settings_resp.status_code == 200, settings_resp.text

    read_resp = client.get("/api/v1/users/registration-email-settings")
    assert read_resp.status_code == 200, read_resp.text
    assert read_resp.json()["data"] == settings_resp.json()["data"]

    rejected = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "outside",
            "password": "secret123",
            "email": "outside@other.com",
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"] == "请使用 example.com 企业邮箱注册"

    accepted = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "inside",
            "password": "secret123",
            "email": "inside@example.com",
        },
    )
    assert accepted.status_code == 201, accepted.text


def test_admin_rejects_invalid_registration_email_regex(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/users/registration-email-settings",
        json={
            "email_regex": "([unclosed",
            "email_validation_message": "请使用指定邮箱",
        },
    )

    assert resp.status_code == 400, resp.text
    assert "邮箱正则表达式无效" in resp.json()["detail"]
