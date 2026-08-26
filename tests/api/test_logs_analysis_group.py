"""Regression tests for one-list-row-per-AI-log-analysis behaviour."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api import logs as logs_api
from app.models.database import Base, get_db
from app.models.log import LogRecord, LogStatus
from app.models.user import ChatAgentRun, User


def _metadata(
    *,
    session_id: str,
    group_id: str | None = None,
    has_analysis: bool = False,
) -> str:
    extra_fields = {"chat_session_id": session_id}
    if group_id:
        extra_fields["analysis_group_id"] = group_id
    if has_analysis:
        extra_fields["ai_analysis_result"] = {
            "status": "completed",
            "answer": "done",
        }
    return json.dumps(
        {"source": "ai_chat", "extra_fields": extra_fields}
    )


@pytest.fixture
def grouped_client(tmp_path) -> TestClient:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'logs.db'}"
    )
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    ids = {
        name: str(uuid.uuid4())
        for name in (
            "group_first",
            "group_primary",
            "legacy_first",
            "legacy_primary",
            "standalone",
        )
    }
    group_id = str(uuid.uuid4())

    files = {
        "group_first": ("companion.log", b"companion content"),
        "group_primary": ("capture.zip", b"capture content"),
        "legacy_first": ("old-a.log", b"old a"),
        "legacy_primary": ("old-b.zip", b"old b"),
        "standalone": ("single.log", b"single"),
    }
    paths: dict[str, Path] = {}
    for name, (filename, content) in files.items():
        path = tmp_path / f"{name}-{filename}"
        path.write_bytes(content)
        paths[name] = path

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            user = User(
                id=str(uuid.uuid4()),
                username="alice",
                display_name="Alice Chen",
                email="alice@example.com",
                password_hash="test-only",
            )
            session.add(user)
            session.add_all(
                [
                    LogRecord(
                        id=ids["group_first"],
                        filename="stored-companion.log",
                        original_filename="companion.log",
                        file_size=len(files["group_first"][1]),
                        file_path=str(paths["group_first"]),
                        archive_path=str(paths["group_first"]),
                        analysis_group_id=group_id,
                        status=LogStatus.COMPLETED,
                        progress=100,
                        issue_description="analyse this batch",
                        metadata_json=_metadata(
                            session_id="session-new",
                            group_id=group_id,
                        ),
                    ),
                    LogRecord(
                        id=ids["group_primary"],
                        filename="stored-capture.zip",
                        original_filename="capture.zip",
                        file_size=len(files["group_primary"][1]),
                        file_path=str(paths["group_primary"]),
                        archive_path=str(paths["group_primary"]),
                        analysis_group_id=group_id,
                        status=LogStatus.COMPLETED,
                        progress=100,
                        issue_description="analyse this batch",
                        metadata_json=_metadata(
                            session_id="session-new",
                            group_id=group_id,
                            has_analysis=True,
                        ),
                    ),
                    # Legacy records have no analysis_group_id but already
                    # carry enough AI-chat metadata to repair the old list.
                    LogRecord(
                        id=ids["legacy_first"],
                        filename="stored-old-a.log",
                        original_filename="old-a.log",
                        file_size=len(files["legacy_first"][1]),
                        file_path=str(paths["legacy_first"]),
                        archive_path=str(paths["legacy_first"]),
                        status=LogStatus.COMPLETED,
                        progress=100,
                        issue_description="old batch question",
                        metadata_json=_metadata(
                            session_id="session-legacy"
                        ),
                    ),
                    LogRecord(
                        id=ids["legacy_primary"],
                        filename="stored-old-b.zip",
                        original_filename="old-b.zip",
                        file_size=len(files["legacy_primary"][1]),
                        file_path=str(paths["legacy_primary"]),
                        archive_path=str(paths["legacy_primary"]),
                        status=LogStatus.COMPLETED,
                        progress=100,
                        issue_description="old batch question",
                        metadata_json=_metadata(
                            session_id="session-legacy",
                            has_analysis=True,
                        ),
                    ),
                    LogRecord(
                        id=ids["standalone"],
                        filename="stored-single.log",
                        original_filename="single.log",
                        file_size=len(files["standalone"][1]),
                        file_path=str(paths["standalone"]),
                        archive_path=str(paths["standalone"]),
                        status=LogStatus.COMPLETED,
                        progress=100,
                    ),
                ]
            )
            session.add_all(
                [
                    ChatAgentRun(
                        id=str(uuid.uuid4()),
                        session_id="session-new",
                        user_id=user.id,
                        owner_scope=f"user:{user.id}",
                        agent_kind="log_analysis",
                        status="succeeded",
                        user_message="analyse this batch",
                        request_json=json.dumps(
                            {"log_id": ids["group_primary"]}
                        ),
                        started_at=datetime(2026, 6, 4, 1, 2, 3),
                    ),
                    ChatAgentRun(
                        id=str(uuid.uuid4()),
                        session_id="session-legacy",
                        user_id=user.id,
                        owner_scope=f"user:{user.id}",
                        agent_kind="log_analysis",
                        status="succeeded",
                        user_message="old batch question",
                        request_json=json.dumps(
                            {"log_id": ids["legacy_primary"]}
                        ),
                        started_at=datetime(2026, 6, 3, 1, 2, 3),
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_seed())

    async def _get_db():
        async with factory() as session:
            yield session

    application = FastAPI()
    application.include_router(
        logs_api.router, prefix="/api/v1/logs"
    )
    application.dependency_overrides[get_db] = _get_db

    with TestClient(application) as client:
        client._ids = ids
        client._factory = factory
        client._paths = paths
        yield client

    asyncio.run(engine.dispose())


def test_list_groups_new_and_legacy_ai_attachments(
    grouped_client: TestClient,
) -> None:
    response = grouped_client.get("/api/v1/logs")
    assert response.status_code == 200, response.text
    payload = response.json()["data"]

    assert payload["pagination"]["total"] == 3
    assert len(payload["logs"]) == 3

    grouped = next(
        log
        for log in payload["logs"]
        if log["id"] == grouped_client._ids["group_primary"]
    )
    assert grouped["attachment_count"] == 2
    assert grouped["file_size"] == len(b"companion content") + len(
        b"capture content"
    )
    assert {
        attachment["filename"]
        for attachment in grouped["attachments"]
    } == {"companion.log", "capture.zip"}
    assert grouped["download_filename"].endswith(".zip")
    assert grouped["ai_analysis_triggered_by"]["user"]["display_name"] == "Alice Chen"

    legacy = next(
        log
        for log in payload["logs"]
        if log["id"] == grouped_client._ids["legacy_primary"]
    )
    assert legacy["attachment_count"] == 2
    assert {
        attachment["filename"]
        for attachment in legacy["attachments"]
    } == {"old-a.log", "old-b.zip"}
    assert legacy["ai_analysis_triggered_by"]["user"]["username"] == "alice"


def test_standalone_analysis_captures_authenticated_trigger(
    grouped_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.ai_analysis import run_ai_analysis_task

    fake_user = SimpleNamespace(
        id="user-standalone",
        username="standalone-user",
        display_name="Standalone User",
        email="standalone@example.com",
    )
    grouped_client.app.dependency_overrides[logs_api.get_optional_user] = (
        lambda: fake_user
    )
    monkeypatch.setattr(
        run_ai_analysis_task,
        "delay",
        lambda *_args, **_kwargs: SimpleNamespace(id="task-standalone"),
    )

    try:
        response = grouped_client.post(
            f"/api/v1/logs/{grouped_client._ids['standalone']}/analyze",
            data={"query": "find the root cause"},
        )
    finally:
        grouped_client.app.dependency_overrides.pop(
            logs_api.get_optional_user, None
        )

    assert response.status_code == 200, response.text
    detail = grouped_client.get(
        f"/api/v1/logs/{grouped_client._ids['standalone']}"
    ).json()["data"]
    trigger = detail["ai_analysis_triggered_by"]
    assert trigger["source"] == "log_detail"
    assert trigger["task_id"] == "task-standalone"
    assert trigger["user"] == {
        "id": "user-standalone",
        "username": "standalone-user",
        "display_name": "Standalone User",
        "email": "standalone@example.com",
    }


def test_standalone_analysis_records_anonymous_trigger(
    grouped_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks.ai_analysis import run_ai_analysis_task

    monkeypatch.setattr(
        run_ai_analysis_task,
        "delay",
        lambda *_args, **_kwargs: SimpleNamespace(id="task-anonymous"),
    )

    response = grouped_client.post(
        f"/api/v1/logs/{grouped_client._ids['standalone']}/analyze",
        data={"query": "anonymous analysis"},
    )

    assert response.status_code == 200, response.text
    detail = grouped_client.get(
        f"/api/v1/logs/{grouped_client._ids['standalone']}"
    ).json()["data"]
    assert detail["ai_analysis_triggered_by"]["source"] == "log_detail"
    assert detail["ai_analysis_triggered_by"]["user"] == {}


def test_group_download_contains_every_original_attachment(
    grouped_client: TestClient,
) -> None:
    response = grouped_client.get(
        f"/api/v1/logs/{grouped_client._ids['group_primary']}/download"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) >= {
            "companion.log",
            "capture.zip",
        }
        assert archive.read("companion.log") == b"companion content"
        assert archive.read("capture.zip") == b"capture content"


def test_deleting_group_row_deletes_all_attachments(
    grouped_client: TestClient,
) -> None:
    response = grouped_client.delete(
        f"/api/v1/logs/{grouped_client._ids['group_primary']}"
    )
    assert response.status_code == 200, response.text

    async def _load_records():
        async with grouped_client._factory() as session:
            result = await session.execute(
                select(LogRecord).where(
                    LogRecord.id.in_(
                        [
                            grouped_client._ids["group_first"],
                            grouped_client._ids["group_primary"],
                        ]
                    )
                )
            )
            return list(result.scalars().all())

    records = asyncio.run(_load_records())
    assert all(record.is_deleted for record in records)
    assert not grouped_client._paths["group_first"].exists()
    assert not grouped_client._paths["group_primary"].exists()
