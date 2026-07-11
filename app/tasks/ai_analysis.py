"""AI 日志分析 Celery 任务（Claude Agent SDK 版）。"""

import json
import logging
import re
import subprocess
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from celery import current_task
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.database import _apply_sqlite_pragmas

from app.agents.log_analysis.agent import LogAnalysisAgent
from app.agents.log_analysis.trace import summarize as summarize_trace
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
from app.services.agent_trace_redis import get_buffer as get_trace_buffer

logger = logging.getLogger(__name__)

_TOKEN_URL_RE = re.compile(r"https://[^@\s]+@")
_HEX_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

_REPO_URL_FIELD_PATHS = (
    ("repo_info", "clone_url"),
    ("repo_info", "repo_url"),
    ("project_info", "clone_url"),
    ("project_info", "repo_url"),
    ("project_info", "repository_url"),
    ("clone_url",),
    ("repo_url",),
    ("repository_url",),
    ("git_context", "clone_url"),
    ("git_context", "repo_url"),
    ("git_context", "repository_url"),
    ("git_context", "remote_url"),
    ("git_context", "git_url"),
    ("scm", "repository_url"),
    ("scm", "repo_url"),
    ("vcs", "repository_url"),
    ("vcs", "repo_url"),
    ("extra_fields", "metadata_json", "repo_info", "clone_url"),
    ("extra_fields", "metadata_json", "repo_info", "repo_url"),
    ("extra_fields", "metadata_json", "project_info", "repo_url"),
    ("extra_fields", "metadata_json", "project_info", "repository_url"),
    ("extra_fields", "metadata_json", "git_context", "clone_url"),
    ("extra_fields", "metadata_json", "git_context", "repo_url"),
    ("extra_fields", "metadata_json", "git_context", "repository_url"),
)

_BRANCH_FIELD_PATHS = (
    ("repo_info", "default_branch"),
    ("repo_info", "branch_name"),
    ("repo_info", "branch"),
    ("project_info", "default_branch"),
    ("project_info", "branch_name"),
    ("project_info", "branch"),
    ("default_branch",),
    ("branch_name",),
    ("branch",),
    ("git_context", "default_branch"),
    ("git_context", "branch_name"),
    ("git_context", "branch"),
    ("git_context", "ref_name"),
    ("scm", "branch_name"),
    ("scm", "branch"),
    ("vcs", "branch_name"),
    ("vcs", "branch"),
    ("extra_fields", "metadata_json", "repo_info", "default_branch"),
    ("extra_fields", "metadata_json", "repo_info", "branch_name"),
    ("extra_fields", "metadata_json", "project_info", "default_branch"),
    ("extra_fields", "metadata_json", "project_info", "branch_name"),
    ("extra_fields", "metadata_json", "git_context", "default_branch"),
    ("extra_fields", "metadata_json", "git_context", "branch_name"),
    ("extra_fields", "metadata_json", "git_context", "branch"),
)

_COMMIT_FIELD_PATHS = (
    ("repo_info", "commit_id"),
    ("repo_info", "commit_sha"),
    ("project_info", "commit_id"),
    ("project_info", "commit_sha"),
    ("commit_id",),
    ("commit_sha",),
    ("revision",),
    ("git_context", "commit_id"),
    ("git_context", "commit_sha"),
    ("git_context", "revision"),
    ("scm", "commit_id"),
    ("scm", "commit_sha"),
    ("vcs", "commit_id"),
    ("vcs", "commit_sha"),
    ("extra_fields", "metadata_json", "repo_info", "commit_id"),
    ("extra_fields", "metadata_json", "repo_info", "commit_sha"),
    ("extra_fields", "metadata_json", "project_info", "commit_id"),
    ("extra_fields", "metadata_json", "project_info", "commit_sha"),
    ("extra_fields", "metadata_json", "git_context", "commit_id"),
    ("extra_fields", "metadata_json", "git_context", "commit_sha"),
    ("extra_fields", "metadata_json", "git_context", "revision"),
)


def _get_sync_database_url() -> str:
    database_url = settings.get_database_url()
    if "sqlite+aiosqlite" in database_url:
        return database_url.replace("sqlite+aiosqlite", "sqlite")
    if "postgresql+asyncpg" in database_url:
        return database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return database_url.replace("+asyncpg", "").replace("+aiosqlite", "")


_sync_database_url = _get_sync_database_url()
_is_sqlite_sync = _sync_database_url.startswith("sqlite")

_sync_engine_kwargs: Dict[str, Any] = {
    "pool_recycle": 3600,
    "echo": False,
}
if not _is_sqlite_sync:
    _sync_engine_kwargs.update(pool_size=1, max_overflow=0, pool_timeout=30)

_sync_engine = create_engine(_sync_database_url, **_sync_engine_kwargs)

if _is_sqlite_sync:
    @event.listens_for(_sync_engine, "connect")
    def _set_sqlite_pragma_sync(dbapi_connection, _connection_record):
        # 与 async 引擎共用同一份 PRAGMA，避免两个引擎并发写时
        # 因为只有一边启用了 WAL/busy_timeout 而触发 "database is locked"。
        _apply_sqlite_pragmas(dbapi_connection)

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
        # 把本轮提问写入结果并追加到多轮对话历史，使详情页能展示完整问答记录
        turn_query = task_info.get("query") or query
        if turn_query and isinstance(result, dict) and not result.get("query"):
            result["query"] = turn_query
        from app.services.log_service import (
            append_analysis_conversation_turn,
            seed_conversation_from_legacy_result,
        )
        # 升级兼容：覆盖前先把旧版本遗留的上一轮结果补种进历史，避免丢失上一轮问答
        seed_conversation_from_legacy_result(extra_fields)
        extra_fields["ai_analysis_result"] = result
        append_analysis_conversation_turn(extra_fields, result, query=turn_query)
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


def _mask_repo_url(url: str) -> str:
    return _TOKEN_URL_RE.sub("https://***@", url)


def _get_nested_string(data: Dict[str, Any], path: tuple[str, ...]) -> Optional[str]:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, str) and current.strip():
        return current.strip()
    return None


def _first_nested_string(
    data: Dict[str, Any],
    paths: tuple[tuple[str, ...], ...],
) -> tuple[Optional[str], Optional[str]]:
    for path in paths:
        value = _get_nested_string(data, path)
        if value:
            return value, ".".join(path)
    return None, None


def _normalize_project_code(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return None


def _log_type_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return None


def _project_code_candidates_from_metadata(
    meta: Dict[str, Any],
    log_type: Any = None,
) -> list[str]:
    """Collect likely project codes from known metadata.json shapes.

    OAM archives may carry the real code under
    `log_types.<component_type>.project_code` while `issue_info.service_name`
    can be a human name. Keep the human-facing fallback, but prefer structured
    project codes first.
    """
    project_info = meta.get("project_info") if isinstance(meta.get("project_info"), dict) else {}
    issue_info = meta.get("issue_info") if isinstance(meta.get("issue_info"), dict) else {}
    log_types = meta.get("log_types") if isinstance(meta.get("log_types"), dict) else {}

    preferred_log_type = _log_type_value(log_type)
    log_type_codes: list[str] = []
    if log_types:
        if preferred_log_type:
            for key, info in log_types.items():
                if str(key).strip().lower() == preferred_log_type and isinstance(info, dict):
                    code = _normalize_project_code(info.get("project_code"))
                    if code:
                        log_type_codes.append(code)
        for info in log_types.values():
            if isinstance(info, dict):
                code = _normalize_project_code(info.get("project_code"))
                if code:
                    log_type_codes.append(code)

    raw_candidates: list[Any] = [
        project_info.get("project_code"),
        meta.get("project_code"),
        issue_info.get("project_code"),
        *log_type_codes,
        project_info.get("project_name"),
        meta.get("project_name"),
        issue_info.get("project_name"),
        issue_info.get("service_name"),
    ]

    candidates: list[str] = []
    seen: set[str] = set()
    for value in raw_candidates:
        code = _normalize_project_code(value)
        if code and code not in seen:
            seen.add(code)
            candidates.append(code)
    return candidates


def _match_project_repo_by_candidates(session, candidates: list[str]):
    """Return ``(repo, matched_code)`` for the first enabled ProjectRepo whose
    project_code matches a candidate, else ``(None, None)``."""
    from app.models.project_repo import ProjectRepo

    for code in candidates:
        repo = (
            session.query(ProjectRepo)
            .filter(ProjectRepo.project_code == code, ProjectRepo.enabled.is_(True))
            .first()
        )
        if repo and _project_repo_supports_agent(session, repo, "log_analysis"):
            return repo, code
    return None, None


def _project_repo_supports_agent(session, repo, agent_key: str) -> bool:
    """Synchronous mirror of project_repo_service.supports_agent for Celery tasks."""
    if not repo or not getattr(repo, "enabled", True):
        return False
    has_repo = bool(str(getattr(repo, "repo_url", "") or "").strip())
    if agent_key in {"log_analysis", "package_search"} and not has_repo:
        return False
    if agent_key == "project_expert":
        default_allowed = True
    elif agent_key in {"log_analysis", "package_search"}:
        default_allowed = has_repo
    else:
        return False

    try:
        from app.models.project_repo import ProjectRepoAgent

        rows = (
            session.query(ProjectRepoAgent.agent_key)
            .filter(ProjectRepoAgent.project_repo_id == repo.id)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("project agent lookup failed, using default: %s", exc)
        return default_allowed
    stored = [row[0] for row in rows]
    if not stored:
        return default_allowed
    return agent_key in stored


def _normalize_branch_name(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    branch = value.strip()
    if not branch or branch == "HEAD" or any(ch.isspace() for ch in branch):
        return None
    for prefix in ("refs/heads/", "origin/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix):].strip()
            break
    if not branch or branch == "HEAD" or _HEX_COMMIT_RE.fullmatch(branch):
        return None
    return branch


def _extract_repo_fields_from_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extract explicit git fields from known metadata.json shapes."""
    repo_url, repo_source = _first_nested_string(meta, _REPO_URL_FIELD_PATHS)
    branch_raw, branch_source = _first_nested_string(meta, _BRANCH_FIELD_PATHS)
    commit_id, commit_source = _first_nested_string(meta, _COMMIT_FIELD_PATHS)
    branch_name = _normalize_branch_name(branch_raw)

    extracted: Dict[str, Any] = {}
    if repo_url:
        extracted["repo_url"] = repo_url
        extracted["repo_source"] = repo_source
    if branch_raw:
        extracted["branch_raw"] = branch_raw
        extracted["branch_source"] = branch_source
    if branch_name:
        extracted["branch_name"] = branch_name
        extracted["default_branch"] = branch_name
    if commit_id:
        extracted["commit_id"] = commit_id.strip()
        extracted["commit_source"] = commit_source
    return extracted


def _extract_repo_metadata(log_record) -> tuple[Optional[str], Optional[str], Optional[str], Dict[str, Any]]:
    """Backward-compatible wrapper for tests and ad-hoc diagnostics."""
    try:
        meta = json.loads(getattr(log_record, "metadata_json", "") or "{}")
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    fields = _extract_repo_fields_from_metadata(meta)
    return (
        fields.get("repo_url"),
        fields.get("commit_id"),
        fields.get("branch_name"),
        fields,
    )


def _clone_repository(
    repo_url: str,
    *,
    commit_id: Optional[str] = None,
    branch_name: Optional[str] = None,
) -> str:
    """Backward-compatible clone helper used by legacy tests."""
    from app.agents.log_analysis.mcp_tools import build_clone_url

    workspace = tempfile.mkdtemp(prefix="ai-analysis-repo-")
    clone_url = build_clone_url(repo_url, settings.code_repo_git_token or None)
    branch = _normalize_branch_name(branch_name)
    cmd = ["git", "clone"]
    if branch:
        cmd.extend(["--single-branch", "--branch", branch])
    cmd.extend([clone_url, workspace])
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if commit_id:
        subprocess.run(
            ["git", "-C", workspace, "checkout", commit_id],
            capture_output=True,
            text=True,
            timeout=120,
        )
    return workspace


def _metadata_debug_keys(meta: Dict[str, Any]) -> Dict[str, Any]:
    def _keys_at(path: tuple[str, ...]) -> list[str]:
        current: Any = meta
        for key in path:
            if not isinstance(current, dict):
                return []
            current = current.get(key)
        if isinstance(current, dict):
            return sorted(str(k) for k in current.keys())[:30]
        return []

    log_types = meta.get("log_types") if isinstance(meta.get("log_types"), dict) else {}
    log_type_project_codes = {
        str(key): value.get("project_code")
        for key, value in log_types.items()
        if isinstance(value, dict) and value.get("project_code")
    }

    return {
        "top_keys": sorted(str(k) for k in meta.keys())[:30],
        "project_info_keys": _keys_at(("project_info",)),
        "issue_info_keys": _keys_at(("issue_info",)),
        "log_types_keys": sorted(str(k) for k in log_types.keys())[:30],
        "log_type_project_codes": log_type_project_codes,
        "git_context_keys": _keys_at(("git_context",)),
        "extra_metadata_keys": _keys_at(("extra_fields", "metadata_json")),
    }


def _write_task_json_fields(workspace_ctx, fields: Dict[str, Any]) -> None:
    task_json_path = Path(workspace_ctx.task_json_path)
    try:
        task_data = json.loads(task_json_path.read_text(encoding="utf-8"))
        if not isinstance(task_data, dict):
            task_data = {}
    except Exception:
        task_data = {}

    task_data.update(fields)
    task_json_path.write_text(
        json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _bind_query_to_workspace(workspace_ctx, *, query: str, project_id: Any = None) -> None:
    workspace_ctx.metadata["question"] = query or ""
    workspace_ctx.metadata["project_id"] = project_id
    _write_task_json_fields(
        workspace_ctx,
        {
            "question": query or "",
            "project_id": project_id,
        },
    )
    logger.info(
        "AI analysis workspace query bound: task_id=%s query_len=%d project_id=%s",
        getattr(workspace_ctx, "task_id", "?"),
        len(query or ""),
        project_id if project_id is not None else "-",
    )


def _safe_project_card(repo) -> Optional[str]:
    """Return a serializable non-empty card from an ORM row/test double."""
    value = getattr(repo, "project_card", None)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


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
    if not isinstance(meta, dict):
        logger.info("_inject_repo_info: metadata.json is not an object")
        return

    meta_keys = _metadata_debug_keys(meta)
    explicit_repo_fields = _extract_repo_fields_from_metadata(meta)
    logger.info(
        "_inject_repo_info: metadata path=%s keys=%s explicit_repo_source=%s "
        "branch_source=%s commit_source=%s",
        meta_path.relative_to(logs_dir),
        meta_keys,
        explicit_repo_fields.get("repo_source") or "-",
        explicit_repo_fields.get("branch_source") or "-",
        explicit_repo_fields.get("commit_source") or "-",
    )

    if explicit_repo_fields.get("repo_url"):
        effective_token = settings.code_repo_git_token or ""
        repo_url = explicit_repo_fields["repo_url"]
        clone_url = build_clone_url(repo_url, effective_token or None)

        # The explicit repo URL is authoritative for cloning, but we still want a
        # project_code so project-level Skills and the project-level system prompt
        # are scoped correctly. Prefer a registered ProjectRepo match; otherwise
        # fall back to the first metadata candidate so on-disk project assets keyed
        # by that code still load.
        scope_candidates = _project_code_candidates_from_metadata(meta)
        scoped_repo, scoped_code = _match_project_repo_by_candidates(session, scope_candidates)
        scoped_project_code = scoped_repo.project_code if scoped_repo else (scope_candidates[0] if scope_candidates else None)
        scoped_project_name = scoped_repo.project_name if scoped_repo else None
        scoped_project_card = _safe_project_card(scoped_repo) if scoped_repo else None

        repo_info = {
            "project_code": scoped_project_code,
            "project_name": scoped_project_name,
            "project_card": scoped_project_card,
            "repo_url": _mask_repo_url(repo_url),
            "clone_url": clone_url,
            "default_branch": explicit_repo_fields.get("default_branch") or "main",
            "auth_required": bool(effective_token),
            "matched_via": explicit_repo_fields.get("repo_source"),
            "source": "metadata.json",
        }
        if explicit_repo_fields.get("branch_name"):
            repo_info["branch_name"] = explicit_repo_fields["branch_name"]
        if explicit_repo_fields.get("branch_raw"):
            repo_info["branch_raw"] = explicit_repo_fields["branch_raw"]
            repo_info["branch_source"] = explicit_repo_fields.get("branch_source")
        if explicit_repo_fields.get("commit_id"):
            repo_info["commit_id"] = explicit_repo_fields["commit_id"]
            repo_info["commit_source"] = explicit_repo_fields.get("commit_source")

        _write_task_json_fields(workspace_ctx, {"repo_info": repo_info})
        logger.info(
            "_inject_repo_info: injected explicit repo_info source=%s repo_url=%s "
            "branch=%s commit_present=%s auth=%s project_code=%s",
            explicit_repo_fields.get("repo_source"),
            _mask_repo_url(repo_url),
            repo_info.get("default_branch"),
            bool(repo_info.get("commit_id")),
            bool(effective_token),
            scoped_project_code or "-",
        )
        return

    # 优先使用 LogRecord 上绑定的 project_id 直接定位项目
    bound_project_id = (
        getattr(workspace_ctx, "metadata", {}).get("project_id")
        if getattr(workspace_ctx, "metadata", None)
        else None
    )
    repo = None
    matched_code: Optional[str] = None
    if bound_project_id:
        repo = (
            session.query(ProjectRepo)
            .filter(ProjectRepo.id == bound_project_id, ProjectRepo.enabled.is_(True))
            .first()
        )
        if repo and _project_repo_supports_agent(session, repo, "log_analysis"):
            matched_code = "project_id"
        else:
            repo = None

    if repo is None:
        candidates = _project_code_candidates_from_metadata(meta)

        if not candidates:
            logger.info("_inject_repo_info: no project identity (project_id/metadata)")
            return

        repo, matched_code = _match_project_repo_by_candidates(session, candidates)

    if not repo:
        registered_codes = [
            row[0]
            for row in session.query(ProjectRepo.project_code)
            .filter(ProjectRepo.enabled.is_(True))
            .order_by(ProjectRepo.project_code)
            .limit(20)
            .all()
        ]
        logger.info(
            "_inject_repo_info: no project_repo match candidates=%s enabled_repo_sample=%s",
            candidates,
            registered_codes,
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
        "project_card": _safe_project_card(repo),
        "repo_url": repo.repo_url,
        "clone_url": clone_url,
        "default_branch": repo.default_branch,
        "auth_required": bool(effective_token),
        "matched_via": matched_code,
    }
    if explicit_repo_fields.get("branch_name"):
        task_data["repo_info"]["branch_name"] = explicit_repo_fields["branch_name"]
        task_data["repo_info"]["branch_source"] = explicit_repo_fields.get("branch_source")
    if explicit_repo_fields.get("branch_raw"):
        task_data["repo_info"]["branch_raw"] = explicit_repo_fields["branch_raw"]
    if explicit_repo_fields.get("commit_id"):
        task_data["repo_info"]["commit_id"] = explicit_repo_fields["commit_id"]
        task_data["repo_info"]["commit_source"] = explicit_repo_fields.get("commit_source")
    task_json_path.write_text(
        json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "_inject_repo_info: injected repo_info project_code=%s matched_via=%s auth=%s",
        repo.project_code,
        matched_code,
        bool(effective_token),
    )


def _error_result(
    error_kind: str,
    message: str = "",
    *,
    trace_events: Optional[list] = None,
    trace_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
        "trace_events": list(trace_events or []),
        "trace_summary": trace_summary or {
            "thought_duration_seconds": 0.0,
            "tool_call_count": 0,
            "thinking_chars": 0,
        },
        "raw": "",
        "duration_seconds": 0.0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
    }


def _build_trace_emitter(task_id: Optional[str], collected: list):
    """Build a synchronous emitter for the Agent.

    Side effects per event:
      - append to ``collected`` (in-memory accumulator) so the Celery task
        can still persist the trace if the Agent run raises;
      - push into the Redis ``TraceBuffer`` so the FastAPI SSE endpoint can
        replay running-task progress to subscribers.

    Failures inside the Redis write are swallowed by ``TraceBuffer.write``
    itself; we still log here defensively if the emitter call raises so a
    bug in this glue never kills the Agent loop.
    """
    buffer = get_trace_buffer()

    def _emit(event: Dict[str, Any]) -> None:
        try:
            collected.append(event)
            if task_id:
                buffer.write(task_id, event)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ai_analysis trace emitter failed task_id=%s err=%s",
                task_id,
                exc,
            )

    return _emit


_timeout = settings.anthropic_request_timeout_seconds
_soft_limit = _timeout + 60
_hard_limit = _soft_limit + 60


def _inject_repo_info_from_project_id(session, workspace_ctx, project_repo_id: int) -> bool:
    """Resolve project_repo by primary key and write repo_info into task.json.

    Used when the user explicitly selects a project from the registry instead
    of relying on metadata.json. Returns True on success, False if no
    enabled record matches.
    """
    from app.agents.log_analysis.mcp_tools import build_clone_url
    from app.models.project_repo import ProjectRepo

    repo = (
        session.query(ProjectRepo)
        .filter(ProjectRepo.id == project_repo_id, ProjectRepo.enabled.is_(True))
        .first()
    )
    if not repo:
        logger.info(
            "_inject_repo_info_from_project_id: project_repo_id=%s not found or disabled",
            project_repo_id,
        )
        return False
    if not _project_repo_supports_agent(session, repo, "log_analysis"):
        logger.info(
            "_inject_repo_info_from_project_id: project_repo_id=%s does not enable log_analysis",
            project_repo_id,
        )
        return False

    effective_token = repo.git_token or settings.code_repo_git_token or ""
    clone_url = build_clone_url(repo.repo_url, effective_token or None)
    repo_info = {
        "project_code": repo.project_code,
        "project_name": repo.project_name,
        "project_card": _safe_project_card(repo),
        "repo_url": repo.repo_url,
        "clone_url": clone_url,
        "default_branch": repo.default_branch,
        "auth_required": bool(effective_token),
        "matched_via": "user_selection",
        "source": "user_selected_project_repo",
    }
    _write_task_json_fields(workspace_ctx, {"repo_info": repo_info})
    logger.info(
        "_inject_repo_info_from_project_id: injected repo_info project_code=%s id=%s auth=%s",
        repo.project_code,
        repo.id,
        bool(effective_token),
    )
    return True


def _maybe_dispatch_bug_fix(
    session,
    *,
    analysis_result: Dict[str, Any],
    log_record: LogRecord,
    analysis_task_id: Optional[str],
    project_repo_id: Optional[int],
) -> None:
    """Best-effort: 当分析判定需要代码修复时创建 Bug 修复任务并异步派发。

    完全包在 try/except 中，任何失败只记日志，绝不影响分析结果的持久化。
    派发条件由结构化信号严格把关（见 ``bug_fix_service.should_dispatch``），
    且需解析出一个已注册的 project_repo 才会派发。
    """
    try:
        if not settings.bug_fix_auto_dispatch:
            return
        from app.services import bug_fix_service

        if not bug_fix_service.should_dispatch(analysis_result):
            return

        # log_record.project_id 与显式 project_repo_id 都是 project_repo.id。
        repo_id = project_repo_id or getattr(log_record, "project_id", None)
        if not repo_id:
            logger.info(
                "bug_fix dispatch skipped: no registered project_repo for log_id=%s",
                getattr(log_record, "id", "?"),
            )
            return

        task = bug_fix_service.create_task_from_analysis(
            session,
            project_repo_id=int(repo_id),
            analysis_result=analysis_result,
            source_log_id=str(getattr(log_record, "id", None)) if getattr(log_record, "id", None) else None,
            source_analysis_task_id=str(analysis_task_id) if analysis_task_id else None,
        )
        session.commit()

        from app.tasks.bug_fix import run_bug_fix_task

        run_bug_fix_task.delay(task.id)
        logger.info(
            "bug_fix dispatched: task=%s repo=%s log_id=%s",
            task.id, repo_id, getattr(log_record, "id", "?"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("bug_fix dispatch failed (non-fatal): %s", exc)
        try:
            session.rollback()
        except Exception:
            pass


@celery_app.task(
    bind=True,
    name="app.tasks.ai_analysis.run_ai_analysis_task",
    max_retries=settings.max_retry_attempts,
    soft_time_limit=_soft_limit,
    time_limit=_hard_limit,
)
def run_ai_analysis_task(
    self,
    log_id: str,
    query: str,
    project_repo_id: Optional[int] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Celery 任务：调用 Claude Agent SDK LogAnalysisAgent 完成日志分析。

    ``locale`` is the active locale resolved at enqueue time (there is no
    request inside the worker); it drives per-language prompt selection and the
    response-language directive. ``None`` falls back to the system default.
    """
    session = SessionLocal()
    log_record: Optional[LogRecord] = None
    task_id = getattr(current_task.request, "id", None)
    start_time = datetime.utcnow()
    workspace_ctx = None
    # Accumulates every AgentTraceEvent emitted during this run so the trace
    # survives even if the Agent run raises before returning a result dict.
    collected_trace_events: list = []

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

        # Prepare workspace (extract archive). When the caller already
        # supplied an explicit project_repo_id, metadata.json is optional —
        # the project identity comes from the user's selection, not from
        # the archive.
        try:
            workspace_ctx = prepare(
                log_record,
                require_metadata=project_repo_id is None,
            )
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

        _bind_query_to_workspace(
            workspace_ctx,
            query=query,
            project_id=getattr(log_record, "project_id", None),
        )

        # Carry the enqueue-time locale into the run so prompt selection and the
        # response-language directive honour the requester's language.
        from app.i18n import normalize as _normalize_locale

        workspace_ctx.locale = _normalize_locale(locale)

        # Pre-resolve project_repo so the agent can clone via plain Bash.
        # Two paths:
        #   1) explicit project_repo_id from API caller → lookup by id;
        #   2) otherwise → infer from metadata.json (legacy behaviour).
        # Required for providers (e.g. deepseek) that can't invoke the MCP
        # lookup tool.
        try:
            injected_from_selection = False
            if project_repo_id is not None:
                injected_from_selection = _inject_repo_info_from_project_id(
                    session, workspace_ctx, project_repo_id
                )
            if not injected_from_selection:
                _inject_repo_info(session, workspace_ctx)
        except Exception as exc:
            logger.warning("repo_info injection failed (non-fatal): %s", exc)

        _update_ai_task_metadata(
            session, log_record, status="running", progress=20.0, task_id=task_id,
        )

        trace_emitter = _build_trace_emitter(task_id, collected_trace_events)
        try:
            analysis_result = LogAnalysisAgent().run_sync(
                workspace_ctx,
                None,
                trace_emitter,
            )
        finally:
            cleanup(workspace_ctx)

        # Defense-in-depth: if the Agent did not populate trace fields
        # (e.g. timeout-fallback dict in run_sync), backfill from the
        # accumulator so the persisted result always carries the trace.
        if not analysis_result.get("trace_events"):
            analysis_result["trace_events"] = list(collected_trace_events)
        if not analysis_result.get("trace_summary"):
            analysis_result["trace_summary"] = summarize_trace(collected_trace_events)

        # Celery PROGRESS meta carries only the summary — broadcasting the
        # full event list through the broker can balloon memory and is
        # already available via the SSE endpoint (Redis).
        try:
            current_task.update_state(
                state="PROGRESS",
                meta={
                    "log_id": log_id,
                    "trace_summary": analysis_result.get("trace_summary"),
                },
            )
        except Exception:  # noqa: BLE001
            # update_state is best-effort progress reporting; never let it
            # break the task.
            pass

        _update_ai_task_metadata(
            session, log_record,
            status="completed", progress=100.0,
            result=analysis_result, finished_at=datetime.utcnow(), task_id=task_id,
        )

        # Best-effort AI usage metrics for the standalone (Celery) analysis path.
        # This is a system task with no authenticated user; idempotent on task/log id.
        try:
            from app.services import metrics_service

            metrics_project_repo_id = project_repo_id or getattr(log_record, "project_id", None)
            metrics_service.record_agent_run_usage_sync(
                source="log_analysis_agent",
                agent_kind="log_analysis",
                result=analysis_result,
                provider=settings.anthropic_provider,
                task_id=str(task_id) if task_id else None,
                log_id=str(log_id),
                project_repo_id=(
                    str(metrics_project_repo_id)
                    if metrics_project_repo_id is not None
                    else None
                ),
                owner_scope="system:ai_analysis",
                idempotency_key=f"ai_usage:log_task:{task_id or log_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "ai_analysis: metrics record skipped log_id=%s: %s", log_id, exc
            )

        # Best-effort: 分析判定需要代码修复时自动派发 Bug 修复任务。
        # 分析结果已在上方提交，派发失败绝不影响其持久化。
        _maybe_dispatch_bug_fix(
            session,
            analysis_result=analysis_result,
            log_record=log_record,
            analysis_task_id=task_id,
            project_repo_id=project_repo_id,
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
                # Build a synthetic error result that still carries whatever
                # trace events the Agent emitted before crashing — keeps the
                # UI replay consistent on unexpected failures.
                trace_summary = summarize_trace(collected_trace_events)
                result = _error_result(
                    "task_exception",
                    str(exc),
                    trace_events=collected_trace_events,
                    trace_summary=trace_summary,
                )
                _update_ai_task_metadata(
                    session, log_record,
                    status="failed", progress=100.0,
                    error=str(exc), result=result,
                    finished_at=datetime.utcnow(), task_id=task_id,
                )
        except Exception:
            pass
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass
