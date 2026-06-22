"""
Bug 修复任务服务。

提供 Bug 修复任务的创建、状态流转与 Merge Request 子记录写入。这些函数面向
**同步** SQLAlchemy Session，因为它们在 Celery 任务（``run_ai_analysis_task`` 的
派发钩子、``run_bug_fix_task`` 的执行体）中调用。读取型分页查询（API 侧）走
独立的 async 实现，不在此文件。

派发条件（``should_dispatch``）严格基于结构化信号，可测试、可回放：
分析成功完成（``status`` ∈ {``ok``, ``completed``}）且 ``requires_code_fix``
且 ``proposed_fixes`` 非空。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.bug_fix import (
    BugFixMergeRequest,
    BugFixMergeRequestStatus,
    BugFixTask,
    BugFixTaskStatus,
)

logger = logging.getLogger(__name__)

# LogAnalysisAgent 成功时在结果里写 ``status="ok"``（见 prompts 的输出 schema 与
# ``LogAnalysisAgent._build_result``）；标准化/任务封装层历史上也用过 "completed"。
# 两者都代表“分析成功完成”，其余（error / schema_mismatch / cancelled）一律不派发。
_SUCCESS_STATUSES = frozenset({"ok", "completed"})


def should_dispatch(analysis_result: Dict[str, Any]) -> bool:
    """判定一次分析结果是否应当派发 Bug 修复任务。

    双条件把关：分析成功完成、且判定需要代码修复并给出了非空的拟修复项。
    任何缺失/异常一律安全降级为 ``False``，绝不误触发。
    """
    if not isinstance(analysis_result, dict):
        return False
    if analysis_result.get("status") not in _SUCCESS_STATUSES:
        return False
    if not analysis_result.get("requires_code_fix"):
        return False
    fixes = analysis_result.get("proposed_fixes")
    return isinstance(fixes, list) and len(fixes) > 0


def _derive_title(analysis_result: Dict[str, Any], proposed_fixes: List[Any]) -> str:
    """为任务推导一个简洁标题：优先首个修复项标题，退化到分析 summary。"""
    if proposed_fixes:
        first = proposed_fixes[0]
        if isinstance(first, dict) and first.get("title"):
            return str(first["title"])[:512]
    summary = analysis_result.get("summary") or analysis_result.get("answer") or ""
    title = str(summary).strip().splitlines()[0] if summary else "AI 自动修复任务"
    return title[:512] or "AI 自动修复任务"


def create_task_from_analysis(
    session,
    *,
    project_repo_id: int,
    analysis_result: Dict[str, Any],
    source_log_id: Optional[str] = None,
    source_analysis_task_id: Optional[str] = None,
) -> BugFixTask:
    """从一次分析结果创建一个 ``pending`` 的 Bug 修复任务（同步 Session）。

    调用方负责事务提交。``proposed_fixes`` 序列化进 ``proposed_fixes_json``。
    """
    proposed_fixes = analysis_result.get("proposed_fixes") or []
    if not isinstance(proposed_fixes, list):
        proposed_fixes = []

    task = BugFixTask(
        project_repo_id=project_repo_id,
        source_log_id=source_log_id,
        source_analysis_task_id=source_analysis_task_id,
        title=_derive_title(analysis_result, proposed_fixes),
        summary=analysis_result.get("summary") or analysis_result.get("answer"),
        proposed_fixes_json=json.dumps(proposed_fixes, ensure_ascii=False),
        status=BugFixTaskStatus.PENDING,
    )
    session.add(task)
    session.flush()  # 取得 task.id
    logger.info(
        "Created bug_fix_task id=%s repo=%s log=%s fixes=%d",
        task.id,
        project_repo_id,
        source_log_id,
        len(proposed_fixes),
    )
    return task


def mark_running(session, task_id: str, *, celery_task_id: Optional[str] = None) -> None:
    """置任务为 running，记录开始时间与 celery_task_id。"""
    task = session.get(BugFixTask, task_id)
    if task is None:
        return
    task.status = BugFixTaskStatus.RUNNING
    task.started_at = datetime.utcnow()
    if celery_task_id:
        task.celery_task_id = celery_task_id
    session.flush()


def record_merge_request(
    session,
    task_id: str,
    mr: Dict[str, Any],
) -> BugFixMergeRequest:
    """把 Agent 产出的单个 MR 结构落库为一行 ``bug_fix_merge_request``。

    ``mr`` 形如 Agent 输出契约的 merge_requests 数组元素。token 已在上游脱敏，
    这里仅持久化干净字段；``mr_url`` 不含凭据。
    """
    changed_files = mr.get("changed_files")
    diff_stat = mr.get("diff_stat")
    status_raw = (mr.get("status") or "").lower()
    try:
        status = BugFixMergeRequestStatus(status_raw)
    except ValueError:
        # 默认：成功拿到 mr_url 视为 created，否则 push_failed
        status = (
            BugFixMergeRequestStatus.CREATED
            if mr.get("mr_url")
            else BugFixMergeRequestStatus.PUSH_FAILED
        )

    row = BugFixMergeRequest(
        task_id=task_id,
        title=str(mr.get("title") or "Bug fix")[:512],
        description=mr.get("description"),
        branch_name=str(mr.get("branch_name") or "")[:256],
        base_branch=str(mr.get("base_branch") or "")[:256],
        mr_url=mr.get("mr_url"),
        mr_iid=str(mr["mr_iid"])[:64] if mr.get("mr_iid") is not None else None,
        commit_sha=str(mr["commit_sha"])[:64] if mr.get("commit_sha") else None,
        changed_files_json=(
            json.dumps(changed_files, ensure_ascii=False)
            if changed_files is not None
            else None
        ),
        diff_stat_json=(
            json.dumps(diff_stat, ensure_ascii=False) if diff_stat is not None else None
        ),
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def finalize(
    session,
    task_id: str,
    *,
    merge_request_count: int,
    error: Optional[str] = None,
) -> BugFixTaskStatus:
    """依产出与错误把任务置为终态。

    - 至少一个 MR 且无错误 → ``succeeded``
    - 有 MR 但伴随错误（部分失败）→ ``partial``
    - 无任何 MR → ``failed``
    """
    task = session.get(BugFixTask, task_id)
    if task is None:
        return BugFixTaskStatus.FAILED

    if merge_request_count > 0 and not error:
        status = BugFixTaskStatus.SUCCEEDED
    elif merge_request_count > 0 and error:
        status = BugFixTaskStatus.PARTIAL
    else:
        status = BugFixTaskStatus.FAILED

    task.status = status
    task.error = error
    task.finished_at = datetime.utcnow()
    session.flush()
    logger.info(
        "Finalized bug_fix_task id=%s status=%s mrs=%d error=%s",
        task_id,
        status.value,
        merge_request_count,
        bool(error),
    )
    return status
