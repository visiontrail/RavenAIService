"""Bug 修复任务只读 API。

供已登录用户查看其所属项目的 Bug 修复任务列表与详情。可见范围严格按
项目成员资格过滤；``role == "admin"`` 的用户可见全部任务。任何字段都不含
git token —— ``mr_url`` 仅为可点击的平台地址（不含凭据）。

读取型分页/详情查询走独立的 async 实现（不在面向 Celery 的同步
``bug_fix_service`` 中）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.users import get_current_user, get_request_locale
from app.i18n.messages import t
from app.models.bug_fix import BugFixMergeRequest, BugFixTask
from app.models.database import get_db
from app.models.project_repo import ProjectRepo
from app.services import project_repo_member_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bug-fixes", tags=["Bug 修复"])


# --------------------------------------------------------------------------- #
# 响应模型
# --------------------------------------------------------------------------- #
class BugFixTaskSummary(BaseModel):
    id: str
    title: str
    project_code: Optional[str] = None
    project_name: Optional[str] = None
    status: str
    merge_request_count: int = 0
    source_log_id: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None


class BugFixTaskListResponse(BaseModel):
    success: bool = True
    data: List[BugFixTaskSummary]
    total: int
    page: int
    page_size: int
    message: str = "ok"


class BugFixMergeRequestData(BaseModel):
    id: str
    title: str
    status: str
    branch_name: str
    base_branch: str
    mr_url: Optional[str] = None
    mr_iid: Optional[str] = None
    commit_sha: Optional[str] = None
    changed_files: Optional[Any] = None
    diff_stat: Optional[Any] = None


class BugFixTaskDetail(BugFixTaskSummary):
    summary: Optional[str] = None
    source_analysis_task_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    proposed_fixes: List[Any] = []
    fix_outcomes: List[Any] = []
    merge_requests: List[BugFixMergeRequestData] = []


class BugFixTaskDetailResponse(BaseModel):
    success: bool = True
    data: BugFixTaskDetail
    message: str = "ok"


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _status_value(value) -> str:
    """状态可能是枚举或字符串，统一取其字符串值。"""
    return getattr(value, "value", value)


def _parse_json(raw: Optional[str], default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def _is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


# --------------------------------------------------------------------------- #
# 端点
# --------------------------------------------------------------------------- #
@router.get("", response_model=BugFixTaskListResponse)
async def list_bug_fixes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> BugFixTaskListResponse:
    """分页列出当前用户可见的 Bug 修复任务。

    非管理员仅可见其作为成员的项目；管理员可见全部。
    """
    admin = _is_admin(current_user)

    # 非管理员先取其成员项目；无项目则直接空结果。
    allowed_project_ids: Optional[List[int]] = None
    if not admin:
        allowed_project_ids = await project_repo_member_service.list_user_projects(
            db, current_user.id
        )
        if not allowed_project_ids:
            return BugFixTaskListResponse(
                data=[], total=0, page=page, page_size=page_size
            )

    base_filter = []
    if allowed_project_ids is not None:
        base_filter.append(BugFixTask.project_repo_id.in_(allowed_project_ids))

    # 总数
    count_stmt = select(func.count(BugFixTask.id))
    for f in base_filter:
        count_stmt = count_stmt.where(f)
    total = int((await db.execute(count_stmt)).scalar() or 0)

    # 分页数据 + 项目信息
    stmt = (
        select(BugFixTask, ProjectRepo.project_code, ProjectRepo.project_name)
        .join(ProjectRepo, ProjectRepo.id == BugFixTask.project_repo_id)
    )
    for f in base_filter:
        stmt = stmt.where(f)
    stmt = (
        stmt.order_by(BugFixTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    task_ids = [row[0].id for row in rows]
    mr_counts = await _merge_request_counts(db, task_ids)

    items = [
        BugFixTaskSummary(
            id=task.id,
            title=task.title,
            project_code=project_code,
            project_name=project_name,
            status=_status_value(task.status),
            merge_request_count=mr_counts.get(task.id, 0),
            source_log_id=task.source_log_id,
            created_at=_iso(task.created_at),
            finished_at=_iso(task.finished_at),
        )
        for task, project_code, project_name in rows
    ]
    return BugFixTaskListResponse(
        data=items, total=total, page=page, page_size=page_size
    )


@router.get("/{task_id}", response_model=BugFixTaskDetailResponse)
async def get_bug_fix(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    locale: str = Depends(get_request_locale),
) -> BugFixTaskDetailResponse:
    """读取单个 Bug 修复任务详情及其 Merge Request 子记录。

    非成员且非管理员一律返回 404（不泄露任务是否存在）。
    """
    stmt = (
        select(BugFixTask, ProjectRepo.project_code, ProjectRepo.project_name)
        .join(ProjectRepo, ProjectRepo.id == BugFixTask.project_repo_id)
        .where(BugFixTask.id == task_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=t("task.not_found", locale)
        )

    task, project_code, project_name = row

    if not _is_admin(current_user):
        member = await project_repo_member_service.is_member(
            db, task.project_repo_id, current_user.id
        )
        if not member:
            # 不泄露存在性
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=t("task.not_found", locale),
            )

    mr_stmt = (
        select(BugFixMergeRequest)
        .where(BugFixMergeRequest.task_id == task_id)
        .order_by(BugFixMergeRequest.created_at.asc())
    )
    mrs = (await db.execute(mr_stmt)).scalars().all()

    merge_requests = [
        BugFixMergeRequestData(
            id=mr.id,
            title=mr.title,
            status=_status_value(mr.status),
            branch_name=mr.branch_name,
            base_branch=mr.base_branch,
            mr_url=mr.mr_url,
            mr_iid=mr.mr_iid,
            commit_sha=mr.commit_sha,
            changed_files=_parse_json(mr.changed_files_json, None),
            diff_stat=_parse_json(mr.diff_stat_json, None),
        )
        for mr in mrs
    ]

    detail = BugFixTaskDetail(
        id=task.id,
        title=task.title,
        project_code=project_code,
        project_name=project_name,
        status=_status_value(task.status),
        merge_request_count=len(merge_requests),
        source_log_id=task.source_log_id,
        source_analysis_task_id=task.source_analysis_task_id,
        created_at=_iso(task.created_at),
        finished_at=_iso(task.finished_at),
        started_at=_iso(task.started_at),
        summary=task.summary,
        error=task.error,
        proposed_fixes=_parse_json(task.proposed_fixes_json, []),
        fix_outcomes=_parse_json(task.fix_outcomes_json, []),
        merge_requests=merge_requests,
    )
    return BugFixTaskDetailResponse(data=detail)


async def _merge_request_counts(
    db: AsyncSession, task_ids: List[str]
) -> dict[str, int]:
    """批量统计每个任务的 MR 数量。"""
    if not task_ids:
        return {}
    stmt = (
        select(BugFixMergeRequest.task_id, func.count(BugFixMergeRequest.id))
        .where(BugFixMergeRequest.task_id.in_(task_ids))
        .group_by(BugFixMergeRequest.task_id)
    )
    result = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}
