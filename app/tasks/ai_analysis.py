"""AI分析异步任务"""

import json
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from celery import current_task
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.log_agent import LogAnalysisAgent
from app.celery_app import celery_app
from app.config import settings
from app.models.log import LogRecord

logger = logging.getLogger(__name__)


def _get_sync_database_url() -> str:
    """将异步数据库URL转换为同步版本，便于Celery任务使用"""
    database_url = settings.get_database_url()
    if "sqlite+aiosqlite" in database_url:
        return database_url.replace("sqlite+aiosqlite", "sqlite")
    if "postgresql+asyncpg" in database_url:
        return database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return database_url.replace("+asyncpg", "").replace("+aiosqlite", "")


# 为AI分析任务创建独立的同步数据库会话
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
    """更新日志记录中的AI分析元数据"""
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


def _load_log_metadata_dict(log_record: LogRecord) -> Dict[str, Any]:
    if not log_record.metadata_json:
        return {}
    try:
        parsed = json.loads(log_record.metadata_json)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _looks_like_repo_url(value: str, key: str = "") -> bool:
    v = value.strip()
    if not v:
        return False

    key_lower = key.lower()
    if key_lower and ("repo" in key_lower or "git" in key_lower or "repository" in key_lower):
        return v.startswith(("http://", "https://", "git@", "ssh://"))

    if v.startswith(("git@", "ssh://")):
        return True
    if v.startswith(("http://", "https://")):
        low = v.lower()
        return any(s in low for s in (".git", "github", "gitlab", "bitbucket", "gitee"))
    return False


def _extract_commit_id(text: str) -> Optional[str]:
    if not isinstance(text, str):
        return None
    m = re.search(r"\b[0-9a-fA-F]{7,40}\b", text.strip())
    return m.group(0) if m else None


def _search_repo_context(obj: Any, path: str = "") -> Tuple[Optional[str], Optional[str], str, str]:
    repo_url: Optional[str] = None
    commit_id: Optional[str] = None
    repo_source = ""
    commit_source = ""

    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{path}.{k}" if path else str(k)

            if isinstance(v, str):
                if repo_url is None and _looks_like_repo_url(v, str(k)):
                    repo_url = v.strip()
                    repo_source = kp

                if commit_id is None:
                    key_lower = str(k).lower()
                    if any(x in key_lower for x in ("commit", "sha", "revision", "git")):
                        extracted = _extract_commit_id(v)
                        if extracted:
                            commit_id = extracted
                            commit_source = kp

            nested_repo, nested_commit, nested_repo_src, nested_commit_src = _search_repo_context(v, kp)
            if repo_url is None and nested_repo:
                repo_url = nested_repo
                repo_source = nested_repo_src
            if commit_id is None and nested_commit:
                commit_id = nested_commit
                commit_source = nested_commit_src

            if repo_url and commit_id:
                break

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            kp = f"{path}[{idx}]"
            nested_repo, nested_commit, nested_repo_src, nested_commit_src = _search_repo_context(item, kp)
            if repo_url is None and nested_repo:
                repo_url = nested_repo
                repo_source = nested_repo_src
            if commit_id is None and nested_commit:
                commit_id = nested_commit
                commit_source = nested_commit_src
            if repo_url and commit_id:
                break

    return repo_url, commit_id, repo_source, commit_source


def _extract_repo_metadata(log_record: LogRecord) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    metadata_dict = _load_log_metadata_dict(log_record)
    repo_url, commit_id, repo_source, commit_source = _search_repo_context(metadata_dict)

    info = {
        "repo_source": repo_source,
        "commit_source": commit_source,
        "has_metadata": bool(metadata_dict),
    }
    return repo_url, commit_id, info


def _clone_repository(repo_url: str, commit_id: Optional[str] = None) -> str:
    workspace_dir = tempfile.mkdtemp(prefix="raven-ai-workspace-")

    def _run_git(cmd: list, timeout: int = 600) -> None:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(
                f"Git命令失败: {' '.join(cmd)}\n"
                f"stdout={result.stdout[-500:]}\n"
                f"stderr={result.stderr[-500:]}"
            )

    try:
        _run_git(["git", "clone", "--quiet", repo_url, workspace_dir], timeout=900)

        if commit_id:
            try:
                _run_git(["git", "-C", workspace_dir, "checkout", "--quiet", commit_id], timeout=180)
            except Exception:
                _run_git(["git", "-C", workspace_dir, "fetch", "--all", "--tags", "--quiet"], timeout=300)
                _run_git(["git", "-C", workspace_dir, "checkout", "--quiet", commit_id], timeout=180)

        return workspace_dir
    except Exception:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        raise


def _perform_legacy_ai_analysis(
    log_record: LogRecord,
    query: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """原有单体 LogAnalysisAgent 逻辑，作为无代码仓库元数据时的降级路径。"""
    from app.agents.log_agent import compress_outputs

    hints = {
        "archive_path": log_record.file_path,
        "path": log_record.file_path,
        "log_id": log_record.id,
        "filename": log_record.original_filename or log_record.filename,
        "log_type": getattr(log_record, "log_type", None),
    }

    agent = LogAnalysisAgent()

    if progress_callback:
        progress_callback(15.0)

    try:
        structured_result = agent.run_structured(query, hints=hints)
        if progress_callback:
            progress_callback(90.0)
        analysis_data = structured_result
    except Exception as structured_error:
        logger.error("Structured analysis failed for %s: %s", log_record.id, structured_error)
        logger.info("Falling back to legacy analysis method for log %s", log_record.id)

        # 执行分析 - 先生成计划
        plan_xml = agent.plan(query, hints=hints)

        # 解析计划步骤
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        steps = [s.strip() for s in steps]

        reasoning_process = []
        completed_steps = []

        for idx, step in enumerate(steps):
            if progress_callback:
                progress_callback(15.0 + (idx + 1) * (60.0 / max(len(steps), 1)))
            try:
                step_output = agent._execute_step(step, query, hints=hints)
                try:
                    step_thought = compress_outputs([step_output], log_type=hints.get("log_type"))
                except Exception:
                    step_thought = f"步骤 {idx + 1} 执行完成"

                reasoning_process.append(
                    {
                        "step_number": idx + 1,
                        "step_description": step,
                        "thought": step_thought,
                        "output": step_output,
                    }
                )
                completed_steps.append(step)
            except Exception as step_error:
                logger.warning("AI analysis step %s failed: %s", idx + 1, step_error)
                reasoning_process.append(
                    {
                        "step_number": idx + 1,
                        "step_description": step,
                        "thought": f"步骤执行失败: {step_error}",
                        "output": "",
                        "error": str(step_error),
                    }
                )

        try:
            final_result_xml = agent.run(query, hints=hints)
        except Exception as run_error:
            logger.warning("Full agent run failed, using partial results: %s", run_error)
            final_result_xml = (
                f"<document><partial_result>{''.join([r.get('output', '') for r in reasoning_process])}"
                f"</partial_result></document>"
            )

        summary = f"完成分析，执行了 {len(completed_steps)}/{len(steps)} 个步骤"

        analysis_data = {
            "log_id": log_record.id,
            "query": query,
            "plan": {
                "steps": steps,
                "completed_steps": completed_steps,
                "total_steps": len(steps),
                "completed_count": len(completed_steps),
            },
            "reasoning": reasoning_process,
            "result": final_result_xml,
            "summary": summary,
            "status": "completed" if len(completed_steps) == len(steps) else "partial",
        }

    if progress_callback:
        progress_callback(95.0)

    if isinstance(analysis_data, dict) and "log_id" not in analysis_data:
        analysis_data["log_id"] = log_record.id

    return analysis_data


def _resolve_log_type_str(log_record: LogRecord) -> str:
    raw = getattr(log_record, "log_type", None)
    return raw.value if hasattr(raw, "value") else str(raw or "unknown")


def _preconfigured_repo_url(log_type_str: str) -> Optional[str]:
    """根据日志类型返回全局预配置的代码仓库 URL（由管理员在 .env 中配置）。"""
    lt = log_type_str.lower()
    if lt in ("oam_antenna", "oam"):
        return settings.code_repo_oam_url or None
    if lt in ("stack", "full"):
        return settings.code_repo_stack_url or None
    return None


def _perform_ai_analysis(
    log_record: LogRecord,
    query: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """优先执行四维多智能体 CodeAnalysisGraph；无任何仓库来源时降级到旧 LogAnalysisAgent。

    触发新流程的两种条件（满足任一即可）：
      1. 日志记录的 metadata_json 中内嵌了 git 仓库 URL（随日志上传携带）。
      2. 管理员在 .env 中为当前日志类型预配置了仓库 URL
         （CODE_REPO_OAM_URL / CODE_REPO_STACK_URL）。

    条件 1 会在本层预先克隆并把 workspace_dir 传给 graph；
    条件 2 不在本层克隆，而是把空 workspace_dir 传给 graph，
    由 agent 在推理过程中自行调用 CloneRepoTool 完成克隆。
    """
    repo_url, commit_id, repo_meta = _extract_repo_metadata(log_record)
    log_type_str = _resolve_log_type_str(log_record)

    # 条件 2：检查是否有针对本日志类型的全局预配置仓库
    preconfigured_url = _preconfigured_repo_url(log_type_str)

    if not repo_url and not preconfigured_url:
        logger.info(
            "No repository source available for log %s (type=%s), fallback to legacy LogAnalysisAgent",
            log_record.id,
            log_type_str,
        )
        legacy_result = _perform_legacy_ai_analysis(log_record, query, progress_callback=progress_callback)
        if isinstance(legacy_result, dict):
            legacy_result.setdefault("mode", "legacy_log_analysis")
            legacy_result.setdefault("degrade_reason", "missing_repo_source")
        return legacy_result

    workspace_dir: Optional[str] = None
    clone_mode: str = "none"

    try:
        if progress_callback:
            progress_callback(20.0)

        if repo_url:
            # 条件 1：日志元数据携带了特定 URL，在本层预先克隆
            workspace_dir = _clone_repository(repo_url, commit_id)
            clone_mode = "metadata_url"
            logger.info(
                "Repository cloned from log metadata: log_id=%s repo=%s commit=%s workspace=%s",
                log_record.id, repo_url, commit_id, workspace_dir,
            )
        else:
            # 条件 2：预配置 URL，workspace 留空，由 agent 的 CloneRepoTool 负责克隆
            workspace_dir = ""
            clone_mode = "agent_clone_tool"
            logger.info(
                "Pre-configured repo detected for log_type=%s (url=%s); "
                "workspace left empty, agent will invoke CloneRepoTool",
                log_type_str, preconfigured_url,
            )

        if progress_callback:
            progress_callback(40.0)

        from app.agents.code_analysis_graph import CodeAnalysisGraph

        graph = CodeAnalysisGraph(token_limit=8000, max_iterations=10)
        analysis_data = graph.run(
            query=query,
            workspace_dir=workspace_dir,
            log_file_path=log_record.file_path,
            log_type=log_type_str,
        )

        if progress_callback:
            progress_callback(92.0)

        if isinstance(analysis_data, dict):
            analysis_data.setdefault("log_id", log_record.id)
            analysis_data.setdefault("mode", "4_agent_code_analysis")
            analysis_data["repo_context"] = {
                "repo_url": repo_url or preconfigured_url,
                "commit_id": commit_id,
                "clone_mode": clone_mode,
                "metadata_source": repo_meta,
            }
        return analysis_data

    except Exception as graph_error:
        logger.error(
            "4-agent code analysis failed for log %s (clone_mode=%s), fallback to legacy mode: %s",
            log_record.id, clone_mode, graph_error,
            exc_info=True,
        )
        legacy_result = _perform_legacy_ai_analysis(log_record, query, progress_callback=progress_callback)
        if isinstance(legacy_result, dict):
            legacy_result.setdefault("mode", "legacy_log_analysis")
            legacy_result["degrade_reason"] = "code_graph_failed"
            legacy_result["degrade_error"] = str(graph_error)
            legacy_result["repo_context"] = {
                "repo_url": repo_url or preconfigured_url,
                "commit_id": commit_id,
                "clone_mode": clone_mode,
                "metadata_source": repo_meta,
            }
        return legacy_result

    finally:
        if workspace_dir:
            try:
                shutil.rmtree(workspace_dir, ignore_errors=True)
                logger.info("Workspace cleaned for log %s: %s", log_record.id, workspace_dir)
            except Exception as cleanup_error:
                logger.warning("Failed to cleanup workspace %s: %s", workspace_dir, cleanup_error)


@celery_app.task(
    bind=True,
    name="app.tasks.ai_analysis.run_ai_analysis_task",
    max_retries=settings.max_retry_attempts,
)
def run_ai_analysis_task(self, log_id: str, query: str) -> Dict[str, Any]:
    """Celery任务：异步运行日志AI分析"""
    session = SessionLocal()
    log_record: Optional[LogRecord] = None
    task_id = getattr(current_task.request, "id", None)
    start_time = datetime.utcnow()

    try:
        log_record = session.query(LogRecord).filter(LogRecord.id == log_id).first()
        if not log_record or getattr(log_record, "is_deleted", False):
            raise FileNotFoundError(f"Log with id {log_id} not found")

        file_path = Path(log_record.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Log file not found at {log_record.file_path}")

        logger.info("AI analysis task started: log_id=%s task_id=%s query='%s'", log_id, task_id, query)

        _update_ai_task_metadata(
            session,
            log_record,
            status="running",
            progress=5.0,
            query=query,
            started_at=start_time,
            task_id=task_id,
        )

        analysis_data = _perform_ai_analysis(
            log_record,
            query,
            progress_callback=lambda p: _update_ai_task_metadata(
                session,
                log_record,
                status="running",
                progress=p,
                task_id=task_id,
                query=query,
            ),
        )

        # 持久化最终结果
        _update_ai_task_metadata(
            session,
            log_record,
            status="completed",
            progress=100.0,
            result=analysis_data,
            finished_at=datetime.utcnow(),
            task_id=task_id,
        )

        logger.info("AI analysis task completed: log_id=%s task_id=%s", log_id, task_id)
        return {"status": "completed", "task_id": task_id, "log_id": log_id}

    except Exception as exc:
        logger.error("AI analysis task failed for log %s: %s", log_id, exc, exc_info=True)
        try:
            if log_record:
                _update_ai_task_metadata(
                    session,
                    log_record,
                    status="failed",
                    progress=100.0,
                    error=str(exc),
                    finished_at=datetime.utcnow(),
                    task_id=task_id,
                )
        except Exception as update_error:
            logger.error("Failed to update AI analysis task metadata after error: %s", update_error)
        raise
    finally:
        try:
            session.close()
        except Exception:
            pass
