"""Bug 修复 Celery 任务（Claude Agent SDK 写入型 Agent）。

``run_bug_fix_task`` 由日志分析成功且判定需要代码修复时派发（见
``ai_analysis._maybe_dispatch_bug_fix``）。它在独立队列上运行，避免与分析任务争抢。

终态：全部成功 → ``succeeded``；部分成功 → ``partial``；无产出/全部失败 → ``failed``。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from celery import current_task

from app.agents.bug_fix.agent import BugFixCodingAgent
from app.agents.bug_fix.workspace import BugFixWorkspaceError, cleanup, prepare
from app.celery_app import celery_app
from app.config import settings
from app.models.bug_fix import BugFixTask
from app.models.project_repo import ProjectRepo
from app.services import bug_fix_service
from app.tasks.ai_analysis import SessionLocal  # 复用同步引擎/会话工厂

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.bug_fix.run_bug_fix_task")
def run_bug_fix_task(self, bug_fix_task_id: str) -> Dict[str, Any]:
    """执行一个 Bug 修复任务。"""
    celery_id = getattr(self.request, "id", None)
    session = SessionLocal()
    ctx = None
    try:
        task: Optional[BugFixTask] = session.get(BugFixTask, bug_fix_task_id)
        if task is None:
            logger.warning("run_bug_fix_task: task %s not found", bug_fix_task_id)
            return {"status": "missing", "task_id": bug_fix_task_id}

        repo: Optional[ProjectRepo] = session.get(ProjectRepo, task.project_repo_id)
        if repo is None:
            bug_fix_service.finalize(
                session, bug_fix_task_id, merge_request_count=0,
                error="project_repo_not_found",
            )
            session.commit()
            return {"status": "failed", "task_id": bug_fix_task_id}

        bug_fix_service.mark_running(session, bug_fix_task_id, celery_task_id=celery_id)
        session.commit()

        proposed_fixes = []
        if task.proposed_fixes_json:
            try:
                proposed_fixes = json.loads(task.proposed_fixes_json) or []
            except json.JSONDecodeError:
                proposed_fixes = []

        git_token = repo.git_token or settings.code_repo_git_token

        try:
            ctx = prepare(
                bug_fix_task_id=bug_fix_task_id,
                repo_url=repo.repo_url,
                default_branch=repo.default_branch or "main",
                git_token=git_token,
                title=task.title,
                summary=task.summary,
                proposed_fixes=proposed_fixes,
                source_log_id=task.source_log_id,
                source_analysis_task_id=task.source_analysis_task_id,
            )
        except BugFixWorkspaceError as exc:
            bug_fix_service.finalize(
                session, bug_fix_task_id, merge_request_count=0, error=str(exc),
            )
            session.commit()
            return {"status": "failed", "task_id": bug_fix_task_id}

        try:
            result = BugFixCodingAgent().run_sync(ctx)
        finally:
            cleanup(ctx)

        merge_requests = result.get("merge_requests") or []
        for mr in merge_requests:
            try:
                bug_fix_service.record_merge_request(session, bug_fix_task_id, mr)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "run_bug_fix_task: failed to record MR for task=%s: %s",
                    bug_fix_task_id, exc,
                )

        # partial/failed 时把 agent 的 error_kind 透传，便于详情展示。
        agent_status = result.get("status")
        error = None
        if agent_status in ("partial", "failed"):
            error = result.get("error_kind") or result.get("error")

        bug_fix_service.finalize(
            session,
            bug_fix_task_id,
            merge_request_count=len(merge_requests),
            error=error,
        )
        session.commit()

        logger.info(
            "run_bug_fix_task complete: task=%s agent_status=%s mrs=%d",
            bug_fix_task_id, agent_status, len(merge_requests),
        )
        return {
            "status": "completed",
            "task_id": bug_fix_task_id,
            "merge_request_count": len(merge_requests),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "run_bug_fix_task failed: task=%s error=%s",
            bug_fix_task_id, exc, exc_info=True,
        )
        if ctx is not None:
            try:
                cleanup(ctx)
            except Exception:
                pass
        try:
            session.rollback()
            bug_fix_service.finalize(
                session, bug_fix_task_id, merge_request_count=0,
                error=f"task_exception: {exc}",
            )
            session.commit()
        except Exception:
            pass
        return {"status": "error", "task_id": bug_fix_task_id}
    finally:
        session.close()
