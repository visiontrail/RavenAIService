"""AI分析异步任务"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

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


def _perform_ai_analysis(
    log_record: LogRecord,
    query: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """执行AI分析逻辑，复用API中的结构化/降级逻辑"""
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
