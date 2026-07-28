"""The registration email policy also governs self-service email changes."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import users as users_api
from app.config import settings
from app.models.database import Base, get_db


COMPANY_ONLY_REGEX = r"^[A-Za-z0-9._%+-]+@example\.com$"
POLICY_MESSAGE = "请使用 example.com 企业邮箱"


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


def _set_policy(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/users/registration-email-settings",
        json={
            "email_regex": COMPANY_ONLY_REGEX,
            "email_validation_message": POLICY_MESSAGE,
        },
    )
    assert resp.status_code == 200, resp.text


def _register(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/users/auth/register",
        json={
            "username": "erin",
            "password": "secret123",
            "email": "erin@example.com",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["token"]


def _patch_profile(client: TestClient, token: str, payload: dict):
    return client.patch(
        "/api/v1/users/auth/me",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_profile_email_change_is_rejected_by_the_admin_policy(client: TestClient) -> None:
    _set_policy(client)
    token = _register(client)

    resp = _patch_profile(client, token, {"email": "erin@other.com"})

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == POLICY_MESSAGE

    me = client.get("/api/v1/users/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["email"] == "erin@example.com"


def test_profile_email_change_is_rejected_for_a_malformed_address(client: TestClient) -> None:
    token = _register(client)

    resp = _patch_profile(client, token, {"email": "not-an-email"})

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "请输入有效的邮箱地址"


def test_compliant_profile_email_change_is_accepted(client: TestClient) -> None:
    _set_policy(client)
    token = _register(client)

    resp = _patch_profile(client, token, {"email": "erin.new@example.com"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["email"] == "erin.new@example.com"


def test_other_profile_fields_are_unaffected_by_the_policy(client: TestClient) -> None:
    _set_policy(client)
    token = _register(client)

    resp = _patch_profile(client, token, {"display_name": "Erin"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["display_name"] == "Erin"
    assert resp.json()["data"]["email"] == "erin@example.com"


def test_clearing_the_email_stays_allowed(client: TestClient) -> None:
    """Accounts predating the policy may have no email; a blank stays a blank."""
    _set_policy(client)
    token = _register(client)

    resp = _patch_profile(client, token, {"email": None})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["email"] is None
