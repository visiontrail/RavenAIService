"""Integration tests for the admin disable note and its delivery at login."""

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
    application.dependency_overrides[users_api.require_admin] = lambda: "admin"

    with TestClient(application) as test_client:
        yield test_client

    asyncio.run(engine.dispose())


def _register(client: TestClient, username: str = "dana") -> str:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@example.test",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["user"]["id"]


def _login(client: TestClient, username: str = "dana", password: str = "secret123"):
    return client.post(
        "/api/v1/users/auth/login",
        json={"username": username, "password": password},
    )


def test_disable_with_message_is_returned_at_login(client: TestClient) -> None:
    user_id = _register(client)

    disabled = client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "is_active": False,
            "disabled_message": "请补充企业邮箱后联系管理员恢复账号",
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["is_active"] is False
    assert disabled.json()["data"]["disabled_message"] == "请补充企业邮箱后联系管理员恢复账号"
    assert disabled.json()["data"]["disabled_at"]

    rejected = _login(client)
    assert rejected.status_code == 403, rejected.text
    assert rejected.json()["detail"] == "请补充企业邮箱后联系管理员恢复账号"


def test_disable_without_message_falls_back_to_default_notice(client: TestClient) -> None:
    user_id = _register(client)

    disabled = client.patch(f"/api/v1/users/{user_id}", json={"is_active": False})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["disabled_message"] is None

    rejected = _login(client)
    assert rejected.status_code == 403, rejected.text
    assert rejected.json()["detail"] == "该账号已被管理员停用，请联系管理员处理。"

    localized = client.post(
        "/api/v1/users/auth/login",
        json={"username": "dana", "password": "secret123"},
        headers={"X-App-Locale": "en"},
    )
    assert localized.status_code == 403, localized.text
    assert "disabled by an administrator" in localized.json()["detail"]


def test_wrong_password_never_reveals_the_disabled_state(client: TestClient) -> None:
    user_id = _register(client)
    client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "disabled_message": "内部留言"},
    )

    rejected = _login(client, password="wrong-password")
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["detail"] == "用户名或密码错误"


def test_message_can_be_edited_while_the_account_stays_disabled(client: TestClient) -> None:
    user_id = _register(client)
    client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "disabled_message": "第一版留言"},
    )

    updated = client.patch(
        f"/api/v1/users/{user_id}",
        json={"disabled_message": "第二版留言"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["is_active"] is False
    assert updated.json()["data"]["disabled_message"] == "第二版留言"
    assert _login(client).json()["detail"] == "第二版留言"


def test_reenabling_clears_the_message_and_restores_login(client: TestClient) -> None:
    user_id = _register(client)
    client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "disabled_message": "补充邮箱"},
    )

    enabled = client.patch(f"/api/v1/users/{user_id}", json={"is_active": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["disabled_message"] is None
    assert enabled.json()["data"]["disabled_at"] is None

    assert _login(client).status_code == 200


def test_message_is_ignored_for_an_active_account(client: TestClient) -> None:
    """A note only describes a locked account; it must not attach to an active one."""
    user_id = _register(client)

    resp = client.patch(
        f"/api/v1/users/{user_id}",
        json={"disabled_message": "不应生效"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["disabled_message"] is None
    assert _login(client).status_code == 200


def test_message_length_is_capped(client: TestClient) -> None:
    user_id = _register(client)

    resp = client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "disabled_message": "长" * 1001},
    )
    assert resp.status_code == 422, resp.text
