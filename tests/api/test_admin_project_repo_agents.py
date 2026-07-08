from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.api import project_repos as project_repos_api
from app.models.database import Base, get_db
from app.security.admin_dependency import AdminPrincipal


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _admin() -> str:
        return "admin"

    async def _principal() -> AdminPrincipal:
        return AdminPrincipal(
            kind="test",
            username="admin",
            is_global_admin=True,
        )

    monkeypatch.setattr(
        admin_api, "_seed_default_prompts", lambda _project_code, _has_repo: None
    )

    app = FastAPI()
    app.include_router(admin_api.router)
    app.include_router(project_repos_api.router)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[admin_api.require_admin] = _admin
    app.dependency_overrides[admin_api.require_admin_principal] = _principal

    with TestClient(app) as test_client:
        yield test_client

    asyncio.run(engine.dispose())


def test_list_project_agents(client: TestClient) -> None:
    resp = client.get("/admin/project-agents")
    assert resp.status_code == 200, resp.text
    keys = {item["key"] for item in resp.json()["data"]}
    assert {"project_expert", "log_analysis", "package_search"} <= keys


def test_create_project_persists_selected_agents(client: TestClient) -> None:
    resp = client.post(
        "/admin/project-repos",
        json={
            "project_code": "alpha",
            "project_name": "Alpha",
            "repo_url": "https://git.example/alpha.git",
            "enabled_agent_keys": ["log_analysis", "package_search"],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["project_code"] == "alpha"
    assert data["enabled_agent_keys"] == ["log_analysis", "package_search"]

    resp = client.get("/api/v1/project-repos", params={"agent_key": "package_search"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    assert [item["project_code"] for item in items] == ["alpha"]
    assert items[0]["enabled_agent_keys"] == ["log_analysis", "package_search"]


def test_create_repoless_project_rejects_repo_bound_agent(client: TestClient) -> None:
    resp = client.post(
        "/admin/project-repos",
        json={
            "project_code": "docs-only",
            "project_name": "Docs Only",
            "repo_url": "",
            "enabled_agent_keys": ["log_analysis"],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "不能启用" in resp.json()["detail"]
