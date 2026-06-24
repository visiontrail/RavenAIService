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


def has_repo(repo: Optional[ProjectRepo]) -> bool:
    """项目是否关联了代码仓库。

    repo_url 为空（NULL 或纯空白）表示「未关联代码仓库」的项目。
    此类项目仅对项目专家（Project Expert）可见，对日志分析、包检索等
    其它 Agent 不可见。
    """
    if repo is None:
        return False
    url = getattr(repo, "repo_url", None)
    return bool(url and url.strip())


# ─────────────────────── Read ──────────────────────────────────────

async def list_repos(
    db: AsyncSession,
    include_disabled: bool = False,
    offset: int = 0,
    limit: int = 50,
    with_repo: Optional[bool] = None,
) -> List[ProjectRepo]:
    """列出项目。

    Args:
        with_repo: ``None`` 返回全部；``True`` 仅返回已关联代码仓库的项目；
            ``False`` 仅返回未关联代码仓库的项目。
    """
    stmt = select(ProjectRepo).order_by(ProjectRepo.id)
    if not include_disabled:
        stmt = stmt.where(ProjectRepo.enabled.is_(True))
    result = await db.execute(stmt)
    repos = list(result.scalars().all())
    if with_repo is not None:
        repos = [r for r in repos if has_repo(r) is with_repo]
    return repos[offset : offset + limit]


async def get_by_id(db: AsyncSession, repo_id: int) -> Optional[ProjectRepo]:
    result = await db.execute(select(ProjectRepo).where(ProjectRepo.id == repo_id))
    return result.scalar_one_or_none()


async def get_by_project_code(
    db: AsyncSession, code: str, *, require_repo: bool = False
) -> Optional[ProjectRepo]:
    """查询已启用的项目，project_code 大小写不敏感且自动去除空白。

    Args:
        require_repo: 为 ``True`` 时，未关联代码仓库（repo_url 为空）的项目视为
            不存在，返回 ``None``。日志分析、包检索等非项目专家的 Agent 应传
            ``True``，从而对「未关联代码仓库」的项目不可见。
    """
    normalized = _normalize_code(code)
    result = await db.execute(
        select(ProjectRepo).where(
            ProjectRepo.project_code == normalized,
            ProjectRepo.enabled.is_(True),
        )
    )
    repo = result.scalar_one_or_none()
    if require_repo and not has_repo(repo):
        return None
    return repo


# ─────────────────────── Write ─────────────────────────────────────

async def create(
    db: AsyncSession,
    *,
    project_code: str,
    project_name: str,
    repo_url: Optional[str] = None,
    default_branch: str = "main",
    git_token: Optional[str] = None,
    description: Optional[str] = None,
    enabled: bool = True,
) -> ProjectRepo:
    now = datetime.utcnow()
    # repo_url 允许为空：表示「未关联代码仓库」的项目（仅对项目专家可见）。
    # 未关联仓库时不应保存 git_token。
    normalized_url = (repo_url or "").strip()
    repo = ProjectRepo(
        project_code=_normalize_code(project_code),
        project_name=project_name.strip(),
        repo_url=normalized_url,
        default_branch=default_branch.strip() or "main",
        git_token=(git_token or None) if normalized_url else None,
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
    if not has_repo(repo):
        return {"success": False, "message": "该项目未关联代码仓库", "auth_method": "none"}
    return test_repo_connection(url=repo.repo_url, token=repo.git_token)
