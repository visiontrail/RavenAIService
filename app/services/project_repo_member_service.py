"""
项目仓库成员服务。

提供项目 ↔ 注册用户成员关系的增删查，作为 Bug 修复列表可见性的鉴权依据。
``add_member`` 幂等：重复加入同一成员不会产生重复行。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_repo import ProjectRepoMember
from app.models.user import User

logger = logging.getLogger(__name__)


async def list_members(db: AsyncSession, project_repo_id: int) -> List[User]:
    """列出某项目的全部成员（User 实体），按用户名排序。"""
    stmt = (
        select(User)
        .join(ProjectRepoMember, ProjectRepoMember.user_id == User.id)
        .where(ProjectRepoMember.project_repo_id == project_repo_id)
        .order_by(User.username)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_user_projects(db: AsyncSession, user_id: str) -> List[int]:
    """列出某用户作为成员的全部 project_repo_id。"""
    stmt = select(ProjectRepoMember.project_repo_id).where(
        ProjectRepoMember.user_id == user_id
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def is_member(db: AsyncSession, project_repo_id: int, user_id: str) -> bool:
    """判断给定用户是否为给定项目的成员。"""
    stmt = select(ProjectRepoMember.id).where(
        ProjectRepoMember.project_repo_id == project_repo_id,
        ProjectRepoMember.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def count_members(db: AsyncSession, project_repo_id: int) -> int:
    """统计某项目的成员数量。"""
    from sqlalchemy import func

    stmt = select(func.count(ProjectRepoMember.id)).where(
        ProjectRepoMember.project_repo_id == project_repo_id
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def count_members_bulk(
    db: AsyncSession, project_repo_ids: List[int]
) -> dict[int, int]:
    """批量统计若干项目的成员数量，返回 {project_repo_id: count}。"""
    from sqlalchemy import func

    if not project_repo_ids:
        return {}
    stmt = (
        select(
            ProjectRepoMember.project_repo_id,
            func.count(ProjectRepoMember.id),
        )
        .where(ProjectRepoMember.project_repo_id.in_(project_repo_ids))
        .group_by(ProjectRepoMember.project_repo_id)
    )
    result = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


async def add_member(
    db: AsyncSession, project_repo_id: int, user_id: str
) -> Optional[ProjectRepoMember]:
    """加入成员（幂等）：已存在时直接返回既有行。"""
    existing = await db.execute(
        select(ProjectRepoMember).where(
            ProjectRepoMember.project_repo_id == project_repo_id,
            ProjectRepoMember.user_id == user_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    now = datetime.utcnow()
    member = ProjectRepoMember(
        project_repo_id=project_repo_id,
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    logger.info(
        "Added project_repo_member project=%d user=%s", project_repo_id, user_id
    )
    return member


async def remove_member(
    db: AsyncSession, project_repo_id: int, user_id: str
) -> bool:
    """移除成员，返回是否确有行被删除。"""
    result = await db.execute(
        sa_delete(ProjectRepoMember).where(
            ProjectRepoMember.project_repo_id == project_repo_id,
            ProjectRepoMember.user_id == user_id,
        )
    )
    await db.flush()
    removed = (result.rowcount or 0) > 0
    if removed:
        logger.info(
            "Removed project_repo_member project=%d user=%s",
            project_repo_id,
            user_id,
        )
    return removed
