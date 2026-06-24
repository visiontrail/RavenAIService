"""Integration tests for log upload project resolution (project_code / project_id / none).

The file-handling side of ``log_service.upload_log`` is mocked out; these tests
focus on how the ``POST /api/v1/logs/upload`` endpoint resolves the associated
project and threads ``project_id`` / ``project_code`` into the upload request.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import logs as logs_api
from app.models.database import Base, get_db
from app.models.log import LogFileInfo, LogStatus
from app.models.project_repo import ProjectRepo


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upload.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    state: dict[str, int] = {}
    captured: dict[str, object] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            # 日志分析域对「未关联代码仓库」的项目不可见，因此用于日志归类的
            # 项目必须关联了代码仓库（repo_url 非空）。
            stack = ProjectRepo(
                project_code="stack",
                project_name="Stack",
                repo_url="https://git.example/stack.git",
                enabled=True,
            )
            session.add(stack)
            await session.flush()
            state["stack_id"] = stack.id
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

    async def _fake_upload_log(db, file, upload_request):
        captured["request"] = upload_request
        info = LogFileInfo(
            id="uploaded-1",
            filename=file.filename,
            original_filename=file.filename,
            file_size=10,
            file_path=f"/tmp/{file.filename}",
            project_id=upload_request.project_id,
            project_code=upload_request.project_code,
            project_name="Stack" if upload_request.project_code == "stack" else None,
            status=LogStatus.PENDING,
        )
        captured["info"] = info
        return info

    async def _noop_backfill(db, log_info):
        return None

    # get_log_detail is called after backfill; return the info captured at upload.
    async def _passthrough_detail(db, log_id):
        return captured["info"]

    monkeypatch.setattr(logs_api.log_service, "upload_log", _fake_upload_log)
    monkeypatch.setattr(logs_api, "_try_extract_and_update_metadata", _noop_backfill)
    monkeypatch.setattr(logs_api.log_service, "get_log_detail", _passthrough_detail)

    application = FastAPI()
    application.include_router(logs_api.router, prefix="/api/v1/logs")
    application.dependency_overrides[get_db] = _get_db

    with TestClient(application) as test_client:
        test_client._seed_state = state
        test_client._captured = captured
        yield test_client

    asyncio.run(engine.dispose())


def _upload(client: TestClient, *, filename: str, data: dict | None = None):
    return client.post(
        "/api/v1/logs/upload",
        files={"file": (filename, b"log content", "application/octet-stream")},
        data=data or {},
    )


def test_upload_with_project_code(client: TestClient) -> None:
    resp = _upload(client, filename="anything.tar.gz", data={"project_code": "stack"})
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["project_id"] == client._seed_state["stack_id"]
    assert body["project_code"] == "stack"


def test_upload_with_project_id(client: TestClient) -> None:
    stack_id = client._seed_state["stack_id"]
    resp = _upload(client, filename="anything.tar.gz", data={"project_id": str(stack_id)})
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["project_id"] == stack_id
    assert body["project_code"] == "stack"


def test_upload_with_invalid_project_id_returns_400(client: TestClient) -> None:
    resp = _upload(client, filename="anything.tar.gz", data={"project_id": "9999"})
    assert resp.status_code == 400, resp.text


def test_upload_does_not_infer_project_from_filename(client: TestClient) -> None:
    # Filename-based auto-classification (stack/oam_antenna/full) was removed:
    # a "stack"-named file without an explicit project must stay unclassified.
    resp = _upload(client, filename="stack_log_20240101.tar.gz")
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["project_id"] is None
    assert body["project_code"] is None


def test_upload_unrecognized_filename_is_unclassified(client: TestClient) -> None:
    resp = _upload(client, filename="unknown_data.zip")
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["project_id"] is None
    assert body["project_code"] is None
