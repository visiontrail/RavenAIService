"""Integration tests for DELETE /admin/project-repos/{id} log-reference guard."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.api.admin import require_admin
from app.exceptions import register_exception_handlers
from app.models.database import Base, get_db
from app.models.log import LogRecord
from app.models.project_repo import ProjectRepo


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    state: dict[str, int] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            repo = ProjectRepo(
                project_code="stack", project_name="Stack", project_card="Stack project", repo_url="", enabled=True
            )
            session.add(repo)
            await session.flush()
            state["repo_id"] = repo.id
            session.add(
                LogRecord(
                    id="log-1",
                    filename="stack_a.tar.gz",
                    original_filename="stack_a.tar.gz",
                    file_size=10,
                    file_path="/tmp/stack_a.tar.gz",
                    project_id=repo.id,
                )
            )
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
    # 与生产一致：注册全局异常处理器，保证结构化 detail 也能正确序列化
    register_exception_handlers(application)
    application.include_router(admin_api.router)
    application.dependency_overrides[get_db] = _get_db
    application.dependency_overrides[require_admin] = lambda: "admin"

    async def _log_count_for(repo_id: int) -> int:
        async with factory() as session:
            from sqlalchemy import func

            return (
                await session.execute(
                    select(func.count(LogRecord.id)).where(
                        LogRecord.project_id == repo_id
                    )
                )
            ).scalar() or 0

    async def _repo_exists(repo_id: int) -> bool:
        async with factory() as session:
            row = (
                await session.execute(
                    select(ProjectRepo).where(ProjectRepo.id == repo_id)
                )
            ).scalar_one_or_none()
            return row is not None

    with TestClient(application) as test_client:
        test_client._state = state
        test_client._log_count_for = _log_count_for
        test_client._repo_exists = _repo_exists
        yield test_client

    asyncio.run(engine.dispose())


def test_delete_blocked_with_409_when_logs_reference_project(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    resp = client.delete(f"/admin/project-repos/{repo_id}")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["affected_logs"] == 1
    # message/detail 必须是字符串，否则 ErrorResponse 校验失败会把 409 变成 500
    assert isinstance(body["message"], str)
    assert isinstance(body["detail"], str)
    assert "force=true" in body["message"]
    # Repo must still exist
    assert asyncio.run(client._repo_exists(repo_id)) is True


def test_force_delete_nulls_logs_and_removes_repo(client: TestClient) -> None:
    repo_id = client._state["repo_id"]
    resp = client.delete(f"/admin/project-repos/{repo_id}", params={"force": "true"})
    assert resp.status_code == 204, resp.text
    assert asyncio.run(client._repo_exists(repo_id)) is False
    # Referencing logs should have project_id set to NULL, not deleted
    assert asyncio.run(client._log_count_for(repo_id)) == 0
