"""Integration tests for GET /api/v1/logs filtering by project_id."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import logs as logs_api
from app.models.database import Base, get_db
from app.models.log import LogRecord
from app.models.project_repo import ProjectRepo


def _make_log(record_id: str, filename: str, project_id):
    return LogRecord(
        id=record_id,
        filename=filename,
        original_filename=filename,
        file_size=123,
        file_path=f"/tmp/{filename}",
        project_id=project_id,
    )


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'logs.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    project_ids: dict[str, int] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            stack = ProjectRepo(
                project_code="stack", project_name="Stack", project_card="Stack project", repo_url="", enabled=True
            )
            oam = ProjectRepo(
                project_code="oam_antenna", project_name="OAM", project_card="OAM project", repo_url="", enabled=True
            )
            session.add_all([stack, oam])
            await session.flush()
            session.add_all([
                _make_log("log-stack-1", "stack_a.tar.gz", stack.id),
                _make_log("log-stack-2", "stack_b.tar.gz", stack.id),
                _make_log("log-oam-1", "oam_a.tar.gz", oam.id),
                _make_log("log-none-1", "mystery.tar.gz", None),
            ])
            await session.commit()
        # expose seeded ids for assertions
        async with factory() as session:
            from sqlalchemy import select

            rows = (await session.execute(select(ProjectRepo))).scalars().all()
            project_ids.update({r.project_code: r.id for r in rows})

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
    application.include_router(logs_api.router, prefix="/api/v1/logs")
    application.dependency_overrides[get_db] = _get_db

    with TestClient(application) as test_client:
        test_client._project_ids = project_ids
        yield test_client

    asyncio.run(engine.dispose())


def test_filter_by_project_id_returns_only_matching(client: TestClient) -> None:
    stack_id = client._project_ids["stack"]
    resp = client.get("/api/v1/logs", params={"project_id": stack_id})
    assert resp.status_code == 200, resp.text
    logs = resp.json()["data"]["logs"]
    assert {log["id"] for log in logs} == {"log-stack-1", "log-stack-2"}
    assert all(log["project_id"] == stack_id for log in logs)
    assert all(log["project_code"] == "stack" for log in logs)


def test_filter_unclassified_with_project_id_zero(client: TestClient) -> None:
    resp = client.get("/api/v1/logs", params={"project_id": 0})
    assert resp.status_code == 200, resp.text
    logs = resp.json()["data"]["logs"]
    assert {log["id"] for log in logs} == {"log-none-1"}
    assert logs[0]["project_id"] is None
    assert logs[0]["project_code"] is None


def test_no_project_filter_returns_all(client: TestClient) -> None:
    resp = client.get("/api/v1/logs")
    assert resp.status_code == 200, resp.text
    logs = resp.json()["data"]["logs"]
    assert len(logs) == 4
