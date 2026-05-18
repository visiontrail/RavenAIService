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
        logger.info(
            "_update_ai_task_metadata: 保存 ai_analysis_result log_id=%s status=%s model=%s duration=%.1fs",
            getattr(log_record, "id", "?"),
            result.get("status"),
            result.get("model"),
            result.get("duration_seconds", 0),
        )

    metadata_dict["extra_fields"] = extra_fields
    new_metadata_json = json.dumps(metadata_dict, ensure_ascii=False, default=str)
    log_record.metadata_json = new_metadata_json
    log_record.updated_at = datetime.utcnow()
    session.add(log_record)
    session.commit()
    session.refresh(log_record)

    # 提交后校验 extra_fields 是否完整写入
    try:
        refreshed = json.loads(log_record.metadata_json or "{}")
        ef_keys = list(refreshed.get("extra_fields", {}).keys())
        logger.info(
            "_update_ai_task_metadata: 提交成功 log_id=%s extra_fields_keys=%s",
            getattr(log_record, "id", "?"),
            ef_keys,
        )
    except Exception as ve:
        logger.warning("_update_ai_task_metadata: 提交后校验失败: %s", ve)


def _inject_repo_info(session, workspace_ctx) -> None:
    """Pre-resolve project_repo and write `repo_info` into task.json.

    The agent system prompt instructs the model to call the MCP tool
    `mcp__project_repo__lookup_project_repo` to obtain the clone URL, but some
    providers (e.g. deepseek) don't support MCP server tools. Pre-resolving
    here lets the agent `git clone` via plain Bash in that case. MCP-capable
    providers can still ignore this and use the tool — both paths produce the
    same shape.
    """
    from app.agents.log_analysis.mcp_tools import build_clone_url
    from app.models.project_repo import ProjectRepo

    logs_dir = Path(workspace_ctx.logs_dir)
    meta_path = next(logs_dir.rglob("metadata.json"), None)
    if meta_path is None:
        return

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("_inject_repo_info: failed to parse metadata.json: %s", exc)
        return

    project_info = meta.get("project_info") if isinstance(meta.get("project_info"), dict) else {}
    issue_info = meta.get("issue_info") if isinstance(meta.get("issue_info"), dict) else {}

    raw_candidates = [
        project_info.get("project_code"),
        meta.get("project_code"),
        issue_info.get("service_name"),
        project_info.get("project_name"),
        meta.get("project_name"),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for v in raw_candidates:
        if isinstance(v, str) and v.strip():
            norm = v.strip().lower()
            if norm not in seen:
                seen.add(norm)
                candidates.append(norm)

    if not candidates:
        logger.info("_inject_repo_info: no project identity in metadata.json")
        return

    repo = None
    matched_code: Optional[str] = None
    for code in candidates:
        repo = (
            session.query(ProjectRepo)
            .filter(ProjectRepo.project_code == code, ProjectRepo.enabled.is_(True))
            .first()
        )
        if repo:
            matched_code = code
            break

    if not repo:
        logger.info(
            "_inject_repo_info: no project_repo match candidates=%s",
            candidates,
        )
        return

    effective_token = repo.git_token or settings.code_repo_git_token or ""
    clone_url = build_clone_url(repo.repo_url, effective_token or None)

    task_json_path = Path(workspace_ctx.task_json_path)
    try:
        task_data = json.loads(task_json_path.read_text(encoding="utf-8"))
    except Exception:
        task_data = {}

    task_data["repo_info"] = {
        "project_code": repo.project_code,
        "project_name": repo.project_name,
        "repo_url": repo.repo_url,
        "clone_url": clone_url,
        "default_branch": repo.default_branch,
        "auth_required": bool(effective_token),
        "matched_via": matched_code,
    }
    task_json_path.write_text(
        json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "_inject_repo_info: injected repo_info project_code=%s matched_via=%s auth=%s",
        repo.project_code,
        matched_code,
        bool(effective_token),
    )


def _error_result(error_kind: str, message: str = "") -> Dict[str, Any]:
    return {
        "engine": "claude-agent-sdk",
        "model": settings.anthropic_model or "unknown",
        "schema_version": 3,
        "status": "error",
        "error_kind": error_kind,
        "question_type": "other",
        "answer": message,
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

        # Fast-fail: no archive (fall back to file_path for records uploaded before archive_path column was added)
        if not getattr(log_record, "archive_path", None) and not getattr(log_record, "file_path", None):
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

        # Pre-resolve project_repo from metadata.json so the agent can clone
        # via plain Bash. Required for providers (e.g. deepseek) that can't
        # invoke the MCP lookup tool.
        try:
            _inject_repo_info(session, workspace_ctx)
        except Exception as exc:
            logger.warning("repo_info injection failed (non-fatal): %s", exc)

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
            "AI analysis complete: log_id=%s status=%s engine=%s model=%s "
            "duration=%.1fs qtype=%s answer_len=%d summary_len=%d raw_len=%d "
            "hypotheses=%d actions=%d schema_version=%s",
            log_id,
            analysis_result.get("status"),
            analysis_result.get("engine"),
            analysis_result.get("model"),
            float(analysis_result.get("duration_seconds") or 0),
            analysis_result.get("question_type") or "-",
            len(analysis_result.get("answer") or ""),
            len(analysis_result.get("summary") or ""),
            len(analysis_result.get("raw") or ""),
            len(analysis_result.get("root_cause_hypotheses") or []),
            len(analysis_result.get("recommended_actions") or []),
            analysis_result.get("schema_version"),
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
