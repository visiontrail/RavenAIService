"""
项目仓库注册表服务。

提供 CRUD 操作与 project_code 查询接口，供日志分析 Agent 与 admin API 使用。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_repo import ProjectRepo
from app.services.repo_settings_service import test_repo_connection

logger = logging.getLogger(__name__)

_TOKEN_MASK = "••••••••"


def _normalize_code(code: str) -> str:
    return code.strip().lower()


# ─────────────────────── Read ──────────────────────────────────────

async def list_repos(
    db: AsyncSession,
    include_disabled: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> List[ProjectRepo]:
    stmt = select(ProjectRepo).order_by(ProjectRepo.id)
    if not include_disabled:
        stmt = stmt.where(ProjectRepo.enabled.is_(True))
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, repo_id: int) -> Optional[ProjectRepo]:
    result = await db.execute(select(ProjectRepo).where(ProjectRepo.id == repo_id))
    return result.scalar_one_or_none()


async def get_by_project_code(db: AsyncSession, code: str) -> Optional[ProjectRepo]:
    """查询已启用的项目仓库，project_code 大小写不敏感且自动去除空白。"""
    normalized = _normalize_code(code)
    result = await db.execute(
        select(ProjectRepo).where(
            ProjectRepo.project_code == normalized,
            ProjectRepo.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none()


# ─────────────────────── Write ─────────────────────────────────────

async def create(
    db: AsyncSession,
    *,
    project_code: str,
    project_name: str,
    repo_url: str,
    default_branch: str = "main",
    git_token: Optional[str] = None,
    description: Optional[str] = None,
    enabled: bool = True,
) -> ProjectRepo:
    now = datetime.utcnow()
    repo = ProjectRepo(
        project_code=_normalize_code(project_code),
        project_name=project_name.strip(),
        repo_url=repo_url.strip(),
        default_branch=default_branch.strip() or "main",
        git_token=git_token or None,
        description=description,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )
    db.add(repo)
    await db.flush()
    await db.refresh(repo)
    logger.info("Created project_repo id=%d code=%s", repo.id, repo.project_code)
    return repo


async def update(
    db: AsyncSession,
    repo: ProjectRepo,
    *,
    project_name: Optional[str] = None,
    repo_url: Optional[str] = None,
    default_branch: Optional[str] = None,
    git_token: Optional[str] = None,
    description: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> ProjectRepo:
    if project_name is not None:
        repo.project_name = project_name.strip()
    if repo_url is not None:
        repo.repo_url = repo_url.strip()
    if default_branch is not None:
        repo.default_branch = default_branch.strip() or "main"
    if git_token is not None:
        if git_token != _TOKEN_MASK:
            repo.git_token = git_token or None
        # if git_token == _TOKEN_MASK, leave unchanged
    if description is not None:
        repo.description = description
    if enabled is not None:
        repo.enabled = enabled
    repo.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(repo)
    logger.info("Updated project_repo id=%d", repo.id)
    return repo


async def delete(db: AsyncSession, repo: ProjectRepo) -> None:
    await db.delete(repo)
    await db.flush()
    logger.info("Deleted project_repo id=%d code=%s", repo.id, repo.project_code)


# ─────────────────────── Connection Test ───────────────────────────

async def test_connection(db: AsyncSession, repo_id: int) -> dict:
    """测试仓库连通性，复用 repo_settings_service.test_repo_connection。"""
    repo = await get_by_id(db, repo_id)
    if not repo:
        return {"success": False, "message": "仓库记录不存在", "auth_method": "none"}
    return test_repo_connection(url=repo.repo_url, token=repo.git_token)
