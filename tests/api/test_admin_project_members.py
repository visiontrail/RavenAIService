"""Integration tests for /admin/project-repos/{id}/members endpoints."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.api.admin import require_admin, require_project_admin_by_repo_id
from app.models.database import Base, get_db
from app.models.project_repo import ProjectRepo
from app.models.user import User
from app.security.admin_dependency import AdminPrincipal


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'members.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    state: dict[str, str | int] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            repo = ProjectRepo(
                project_code="stack", project_name="Stack", project_card="Stack project", repo_url="", enabled=True
            )
            session.add(repo)
            user = User(
                id="user-1",
                username="alice",
                display_name="Alice",
                email="alice@example.com",
                password_hash="x",
            )
            session.add(user)
            await session.flush()
            state["repo_id"] = repo.id
            state["user_id"] = user.id
            await session.commit()

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
    application.dependency_overrides[get_db] = _get_db
    application.dependency_overrides[require_admin] = lambda: "admin"
    application.dependency_overrides[require_project_admin_by_repo_id] = (
        lambda: AdminPrincipal(
            kind="legacy_admin", username="admin", is_global_admin=True
        )
    )

    with TestClient(application) as test_client:
        test_client._state = state
        yield test_client

    asyncio.run(engine.dispose())


def test_add_list_and_member_count(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    user_id = client._state["user_id"]

    # Initially empty
    resp = client.get(f"/admin/project-repos/{repo_id}/members")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []

    # Add member
    resp = client.post(
        f"/admin/project-repos/{repo_id}/members", json={"user_id": user_id}
    )
    assert resp.status_code == 201, resp.text
    members = resp.json()["data"]
    assert len(members) == 1
    member = members[0]
    assert member["id"] == user_id
    assert member["username"] == "alice"
    assert member["email"] == "alice@example.com"
    # Never leak password hash
    assert "password_hash" not in member

    # member_count surfaces in repo detail
    resp = client.get(f"/admin/project-repos/{repo_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["member_count"] == 1


def test_add_member_is_idempotent(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    user_id = client._state["user_id"]

    client.post(f"/admin/project-repos/{repo_id}/members", json={"user_id": user_id})
    resp = client.post(
        f"/admin/project-repos/{repo_id}/members", json={"user_id": user_id}
    )
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["data"]) == 1

    resp = client.get(f"/admin/project-repos/{repo_id}")
    assert resp.json()["data"]["member_count"] == 1


def test_remove_member(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    user_id = client._state["user_id"]

    client.post(f"/admin/project-repos/{repo_id}/members", json={"user_id": user_id})
    resp = client.delete(f"/admin/project-repos/{repo_id}/members/{user_id}")
    assert resp.status_code == 204, resp.text

    resp = client.get(f"/admin/project-repos/{repo_id}/members")
    assert resp.json()["data"] == []


def test_add_unknown_user_404(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    resp = client.post(
        f"/admin/project-repos/{repo_id}/members", json={"user_id": "nope"}
    )
    assert resp.status_code == 404, resp.text


def test_non_admin_rejected(client: TestClient) -> None:
    # Drop the admin override so the real guard runs (no Authorization header).
    client.app.dependency_overrides.pop(require_admin, None)
    repo_id = client._state["repo_id"]
    resp = client.get(f"/admin/project-repos/{repo_id}/members")
    assert resp.status_code == 401, resp.text
