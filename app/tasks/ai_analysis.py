"""AI 日志分析 Celery 任务（Claude Agent SDK 版）。"""

import json
import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from celery import current_task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.log_analysis.agent import LogAnalysisAgent
from app.agents.log_analysis.workspace import (
    MissingArchiveError,
    MissingMetadataJsonError,
    WorkspaceError,
    cleanup,
    prepare,
)
from app.celery_app import celery_app
from app.config import settings
from app.models.log import LogRecord

logger = logging.getLogger(__name__)


def _get_sync_database_url() -> str:
    database_url = settings.get_database_url()
    if "sqlite+aiosqlite" in database_url:
        return database_url.replace("sqlite+aiosqlite", "sqlite")
    if "postgresql+asyncpg" in database_url:
        return database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return database_url.replace("+asyncpg", "").replace("+aiosqlite", "")


_sync_engine = create_engine(
    _get_sync_database_url(),
    pool_size=1,
    max_overflow=0,
    pool_timeout=30,
    pool_recycle=3600,
    echo=False,
)
SessionLocal = sessionmaker(bind=_sync_engine)


def _update_ai_task_metadata(
    session,
    log_record: LogRecord,
    *,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    task_id: Optional[str] = None,
) -> None:
    metadata_dict: Dict[str, Any] = {}
    try:
        if log_record.metadata_json:
            metadata_dict = json.loads(log_record.metadata_json) or {}
    except Exception:
        metadata_dict = {}

    extra_fields = metadata_dict.get("extra_fields")
    if not isinstance(extra_fields, dict):
        extra_fields = {}

    task_info = extra_fields.get("ai_analysis_task")
    if not isinstance(task_info, dict):
        task_info = {}

    if task_id:
        task_info["task_id"] = task_id
    if status:
        task_info["status"] = status
    if progress is not None:
        task_info["progress"] = float(progress)
    if query:
        task_info["query"] = query
    if error is not None:
        task_info["error"] = error
    if started_at:
        task_info["started_at"] = started_at.isoformat()
    if finished_at:
        task_info["finished_at"] = finished_at.isoformat()

    extra_fields["ai_analysis_task"] = task_info

    if result is not None:
        extra_fields["ai_analysis_result"] = result

    metadata_dict["extra_fields"] = extra_fields
    log_record.metadata_json = json.dumps(metadata_dict, ensure_ascii=False, default=str)
    log_record.updated_at = datetime.utcnow()
    session.add(log_record)
    session.commit()
    session.refresh(log_record)


def _error_result(error_kind: str, message: str = "") -> Dict[str, Any]:
    return {
        "engine": "claude-agent-sdk",
        "model": settings.anthropic_model or "unknown",
        "schema_version": 2,
        "status": "error",
        "error_kind": error_kind,
        "summary": message,
        "severity": "error",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": [],
        "tool_trace": [],
        "raw": "",
        "duration_seconds": 0.0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
    }


_timeout = settings.anthropic_request_timeout_seconds
_soft_limit = _timeout + 60
_hard_limit = _soft_limit + 60


@celery_app.task(
    bind=True,
    name="app.tasks.ai_analysis.run_ai_analysis_task",
    max_retries=settings.max_retry_attempts,
    soft_time_limit=_soft_limit,
    time_limit=_hard_limit,
)
def run_ai_analysis_task(self, log_id: str, query: str) -> Dict[str, Any]:
    """Celery 任务：调用 Claude Agent SDK LogAnalysisAgent 完成日志分析。"""
    session = SessionLocal()
    log_record: Optional[LogRecord] = None
    task_id = getattr(current_task.request, "id", None)
    start_time = datetime.utcnow()
    workspace_ctx = None

    try:
        log_record = session.query(LogRecord).filter(LogRecord.id == log_id).first()
        if not log_record or getattr(log_record, "is_deleted", False):
            raise FileNotFoundError(f"Log with id {log_id} not found")

        _update_ai_task_metadata(
            session, log_record,
            status="running", progress=5.0,
            query=query, started_at=start_time, task_id=task_id,
        )

        # Fast-fail: no archive
        if not getattr(log_record, "archive_path", None):
            result = _error_result("missing_archive", "No archive_path on LogRecord")
            _update_ai_task_metadata(
                session, log_record,
                status="failed", progress=100.0,
                result=result, finished_at=datetime.utcnow(), task_id=task_id,
            )
            return {"status": "error", "error_kind": "missing_archive", "log_id": log_id}

        # Prepare workspace (extract archive, verify metadata.json)
        try:
            workspace_ctx = prepare(log_record)
        except MissingArchiveError as exc:
            result = _error_result("missing_archive", str(exc))
            _update_ai_task_metadata(
                session, log_record,
                status="failed", progress=100.0,
                result=result, finished_at=datetime.utcnow(), task_id=task_id,
            )
            return {"status": "error", "error_kind": "missing_archive", "log_id": log_id}
        except MissingMetadataJsonError as exc:
            result = _error_result("missing_metadata_json", str(exc))
            _update_ai_task_metadata(
                session, log_record,
                status="failed", progress=100.0,
                result=result, finished_at=datetime.utcnow(), task_id=task_id,
            )
            return {"status": "error", "error_kind": "missing_metadata_json", "log_id": log_id}
        except WorkspaceError as exc:
            result = _error_result("workspace_error", str(exc))
            _update_ai_task_metadata(
                session, log_record,
                status="failed", progress=100.0,
                result=result, finished_at=datetime.utcnow(), task_id=task_id,
            )
            return {"status": "error", "error_kind": "workspace_error", "log_id": log_id}

        _update_ai_task_metadata(
            session, log_record, status="running", progress=20.0, task_id=task_id,
        )

        # Store question in workspace context metadata
        workspace_ctx.metadata["question"] = query
        workspace_ctx.metadata["log_type"] = getattr(log_record, "log_type", None)

        try:
            analysis_result = LogAnalysisAgent().run_sync(workspace_ctx)
        finally:
            cleanup(workspace_ctx)

        _update_ai_task_metadata(
            session, log_record,
            status="completed", progress=100.0,
            result=analysis_result, finished_at=datetime.utcnow(), task_id=task_id,
        )

        logger.info(
            "AI analysis complete: log_id=%s status=%s engine=%s model=%s",
            log_id,
            analysis_result.get("status"),
            analysis_result.get("engine"),
            analysis_result.get("model"),
        )
        return {"status": "completed", "task_id": task_id, "log_id": log_id}

    except Exception as exc:
        logger.error("AI analysis task failed: log_id=%s error=%s", log_id, exc, exc_info=True)
        if workspace_ctx:
            try:
                cleanup(workspace_ctx)
            except Exception:
                pass
        try:
            if log_record:
                _update_ai_task_metadata(
                    session, log_record,
                    status="failed", progress=100.0,
                    error=str(exc), finished_at=datetime.utcnow(), task_id=task_id,
                )
        except Exception:
            pass
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass
