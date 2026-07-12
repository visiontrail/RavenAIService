"""Integration tests for the self-service profile language field."""

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


def _register(client: TestClient, username: str = "lang_user") -> str:
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


def test_new_user_defaults_to_zh(client: TestClient) -> None:
    token = _register(client)
    me = client.get(
        "/api/v1/users/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["data"]["language"] == "zh"


def test_update_profile_language_persists(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"language": "en"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["language"] == "en"

    # Re-read to confirm persistence.
    me = client.get("/api/v1/users/auth/me", headers=headers)
    assert me.json()["data"]["language"] == "en"


def test_update_profile_identity_fields_persist(client: TestClient) -> None:
    token = _register(client, username="profile_user")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={
            "display_name": "  Profile User  ",
            "email": "  profile@example.test  ",
            "profile_role": "QA",
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["display_name"] == "Profile User"
    assert data["email"] == "profile@example.test"
    assert data["profile_role"] == "tester"

    me = client.get("/api/v1/users/auth/me", headers=headers)
    assert me.json()["data"]["display_name"] == "Profile User"
    assert me.json()["data"]["email"] == "profile@example.test"
    assert me.json()["data"]["profile_role"] == "tester"


def test_update_profile_can_clear_optional_identity_fields(client: TestClient) -> None:
    token = _register(client, username="clear_profile")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"display_name": "", "email": None, "profile_role": "bad role!"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["display_name"] is None
    assert data["email"] is None
    assert data["profile_role"] == "developer"


def test_update_profile_unsupported_language_is_coerced(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"language": "ja"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # Unsupported code coerced to the default, never stored as-is.
    assert resp.json()["data"]["language"] == "zh"


def test_update_profile_locale_variant_normalized(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.patch(
        "/api/v1/users/auth/me",
        json={"language": "en-US"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["language"] == "en"
