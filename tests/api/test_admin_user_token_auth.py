from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.api import users as users_api
from app.models.database import Base, get_db
from app.models.user import User
from app.security.user_auth import user_auth_manager


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin_user_token.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    state: dict[str, str] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            admin = User(
                id="admin-user-id",
                username="admin",
                display_name="Admin",
                password_hash="x",
                role="admin",
            )
            regular = User(
                id="regular-user-id",
                username="alice",
                display_name="Alice",
                password_hash="x",
                role="user",
            )
            session.add_all([admin, regular])
            await session.commit()
        state["admin_token"] = user_auth_manager.issue_token("admin-user-id", "admin")[0]
        state["regular_token"] = user_auth_manager.issue_token("regular-user-id", "alice")[0]

    asyncio.run(_seed())

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = FastAPI()
    application.include_router(admin_api.router)
    application.include_router(users_api.router)
    application.dependency_overrides[get_db] = _get_db

    with TestClient(application) as test_client:
        test_client._state = state
        yield test_client

    asyncio.run(engine.dispose())


def test_admin_routes_accept_admin_role_user_token(client: TestClient) -> None:
    resp = client.get(
        "/admin/auth/me",
        headers={"Authorization": f"Bearer {client._state['admin_token']}"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["username"] == "admin"


def test_admin_routes_reject_regular_user_token(client: TestClient) -> None:
    # A regular user with no enabled project membership is not admitted to the
    # admin console as a project-member admin.
    resp = client.get(
        "/admin/auth/me",
        headers={"Authorization": f"Bearer {client._state['regular_token']}"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Project membership required"


def test_user_management_accepts_admin_role_user_token(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {client._state['admin_token']}"},
    )

    assert resp.status_code == 200, resp.text
    assert {item["username"] for item in resp.json()["data"]} == {"admin", "alice"}
