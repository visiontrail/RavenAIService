"""Unit coverage for normalized log-analysis attribution precedence."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.models.log import LogMetadata, LogRecord, LogStatus
from app.services.log_service import log_service
from app.tasks.ai_analysis import _update_ai_task_metadata


def _record(metadata: LogMetadata) -> LogRecord:
    return LogRecord(
        id="log-1",
        filename="stored.log",
        original_filename="source.log",
        file_size=10,
        file_path="/tmp/source.log",
        status=LogStatus.COMPLETED,
        progress=100,
        download_count=0,
        created_at=datetime(2026, 6, 1, 1, 2, 3),
        updated_at=datetime(2026, 6, 1, 1, 2, 3),
        metadata_json=metadata.model_dump_json(),
    )


@pytest.mark.asyncio
async def test_completed_result_trigger_is_normalized() -> None:
    result_trigger = {
        "source": "ai_chat",
        "user": {"display_name": "Alice"},
    }
    metadata = LogMetadata(
        extra_fields={
            "ai_analysis_result": {
                "status": "completed",
                "triggered_by": result_trigger,
            }
        }
    )

    info = await log_service._db_to_pydantic(_record(metadata), metadata)

    assert info.ai_analysis_triggered_by == result_trigger


@pytest.mark.asyncio
async def test_active_task_trigger_wins_over_previous_result() -> None:
    task_trigger = {"source": "log_detail", "user": {}}
    metadata = LogMetadata(
        extra_fields={
            "ai_analysis_result": {
                "status": "completed",
                "triggered_by": {
                    "source": "ai_chat",
                    "user": {"display_name": "Previous User"},
                },
            },
            "ai_analysis_task": {
                "status": "queued",
                "triggered_by": task_trigger,
            },
        }
    )

    info = await log_service._db_to_pydantic(_record(metadata), metadata)

    assert info.ai_analysis_triggered_by == task_trigger


@pytest.mark.asyncio
async def test_missing_trigger_remains_unavailable() -> None:
    metadata = LogMetadata(extra_fields={})

    info = await log_service._db_to_pydantic(_record(metadata), metadata)

    assert info.ai_analysis_triggered_by is None


def test_worker_copies_task_trigger_into_terminal_result() -> None:
    trigger = {
        "source": "log_detail",
        "task_id": "task-1",
        "user": {},
    }
    metadata = {
        "extra_fields": {
            "ai_analysis_task": {
                "status": "running",
                "query": "inspect",
                "triggered_by": trigger,
            }
        }
    }
    record = _record(LogMetadata(**metadata))

    class FakeSession:
        def add(self, _record: LogRecord) -> None:
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _record: LogRecord) -> None:
            return None

    _update_ai_task_metadata(
        FakeSession(),
        record,
        status="completed",
        progress=100,
        result={"status": "completed", "answer": "done"},
    )

    saved = json.loads(record.metadata_json or "{}")
    assert saved["extra_fields"]["ai_analysis_result"]["triggered_by"] == trigger
