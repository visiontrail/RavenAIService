"""
项目仓库注册表服务。

提供 CRUD 操作与 project_code 查询接口，供日志分析 Agent 与 admin API 使用。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project_repo import ProjectRepo, ProjectRepoAgent
from app.services.repo_settings_service import test_repo_connection

logger = logging.getLogger(__name__)

_TOKEN_MASK = "••••••••"
PROJECT_CARD_MAX_LENGTH = 4000
PROJECT_DISCOVERY_MAX_ITEMS = 500


PROJECT_AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "project_expert": {
        "key": "project_expert",
        "name": "ProjectExpertAgent",
        "display_name": "项目专家",
        "framework": "Claude Agent SDK",
        "requires_repo": False,
        "description": "基于项目上下文、项目级提示词和可选代码仓库进行源码/项目答疑",
    },
    "log_analysis": {
        "key": "log_analysis",
        "name": "LogAnalysisAgent",
        "display_name": "日志分析",
        "framework": "Claude Agent SDK",
        "requires_repo": True,
        "description": "分析日志归档并结合项目代码仓库定位根因",
    },
    "package_search": {
        "key": "package_search",
        "name": "PackageSearchAgent",
        "display_name": "重构包配置管理员",
        "framework": "Claude Agent SDK",
        "requires_repo": True,
        "description": "在项目范围内检索重构包、版本资产与配置线索",
    },
}


def _normalize_code(code: str) -> str:
    return code.strip().lower()


def normalize_project_card(project_card: str) -> str:
    """Normalize and validate the project-matching card text."""
    if not isinstance(project_card, str):
        raise ValueError("项目卡片为必填文本")
    normalized = project_card.strip()
    if not normalized:
        raise ValueError("请填写项目卡片")
    if len(normalized) > PROJECT_CARD_MAX_LENGTH:
        raise ValueError(f"项目卡片不能超过 {PROJECT_CARD_MAX_LENGTH} 个字符")
    return normalized


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


def list_project_agents() -> List[Dict[str, Any]]:
    """列出可绑定到项目的 Agent。"""
    return [dict(item) for item in PROJECT_AGENT_REGISTRY.values()]


def _is_agent_compatible(repo: ProjectRepo, agent_key: str) -> bool:
    meta = PROJECT_AGENT_REGISTRY.get(agent_key)
    if not meta:
        return False
    return not bool(meta.get("requires_repo")) or has_repo(repo)


def default_agent_keys_for_repo(repo: ProjectRepo) -> List[str]:
    """旧项目/未显式配置时的兼容默认值。"""
    return [
        key
        for key in PROJECT_AGENT_REGISTRY
        if _is_agent_compatible(repo, key)
    ]


def normalize_agent_keys(
    agent_keys: Optional[Iterable[str]],
    repo: ProjectRepo,
    *,
    fallback_to_default: bool = True,
) -> List[str]:
    """规范化并校验项目 Agent key。

    ``None`` 表示使用与旧行为等价的默认值；显式空列表会被拒绝，避免创建后
    项目没有任何可用 Agent。
    """
    if agent_keys is None:
        return default_agent_keys_for_repo(repo) if fallback_to_default else []

    normalized: List[str] = []
    unknown: List[str] = []
    incompatible: List[str] = []
    for raw in agent_keys:
        key = str(raw or "").strip()
        if not key:
            continue
        if key not in PROJECT_AGENT_REGISTRY:
            unknown.append(key)
            continue
        if not _is_agent_compatible(repo, key):
            incompatible.append(key)
            continue
        if key not in normalized:
            normalized.append(key)

    if unknown:
        raise ValueError(f"未知 Agent: {', '.join(unknown)}")
    if incompatible:
        names = ", ".join(
            PROJECT_AGENT_REGISTRY[key].get("display_name", key)
            for key in incompatible
        )
        raise ValueError(f"当前项目未关联代码仓库，不能启用: {names}")
    if not normalized:
        raise ValueError("请至少选择一个可用 Agent")
    return normalized


def _effective_agent_keys(repo: ProjectRepo, stored_keys: Optional[Iterable[str]]) -> List[str]:
    if stored_keys is None:
        return default_agent_keys_for_repo(repo)
    effective = [
        key
        for key in stored_keys
        if key in PROJECT_AGENT_REGISTRY and _is_agent_compatible(repo, key)
    ]
    return effective or default_agent_keys_for_repo(repo)


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


async def list_agent_keys(db: AsyncSession, repo: ProjectRepo) -> List[str]:
    result = await db.execute(
        select(ProjectRepoAgent.agent_key)
        .where(ProjectRepoAgent.project_repo_id == repo.id)
        .order_by(ProjectRepoAgent.id)
    )
    stored = list(result.scalars().all())
    return _effective_agent_keys(repo, stored if stored else None)


async def list_agent_keys_bulk(
    db: AsyncSession, repos: Iterable[ProjectRepo]
) -> Dict[int, List[str]]:
    repo_list = list(repos)
    if not repo_list:
        return {}
    repo_by_id = {repo.id: repo for repo in repo_list}
    result = await db.execute(
        select(ProjectRepoAgent.project_repo_id, ProjectRepoAgent.agent_key)
        .where(ProjectRepoAgent.project_repo_id.in_(list(repo_by_id)))
        .order_by(ProjectRepoAgent.id)
    )
    stored: Dict[int, List[str]] = {repo.id: [] for repo in repo_list}
    for repo_id, agent_key in result.all():
        if repo_id in stored:
            stored[repo_id].append(agent_key)
    return {
        repo.id: _effective_agent_keys(repo, stored[repo.id] or None)
        for repo in repo_list
    }


async def discover_projects(
    db: AsyncSession,
    *,
    limit: int = PROJECT_DISCOVERY_MAX_ITEMS,
) -> Dict[str, Any]:
    """Return the bounded, credential-free enabled project catalog for Agents.

    This is the single serializer used by the MCP discovery tool.  Keep the
    allowlist explicit: repository URLs, tokens, auth state, and memberships
    must never enter an Agent catalog response.
    """
    bounded_limit = max(1, min(int(limit), PROJECT_DISCOVERY_MAX_ITEMS))
    repos = await list_repos(
        db,
        include_disabled=False,
        offset=0,
        limit=bounded_limit + 1,
    )
    truncated = len(repos) > bounded_limit
    visible_repos = repos[:bounded_limit]
    agent_keys_by_repo = await list_agent_keys_bulk(db, visible_repos)
    projects = [
        {
            "id": repo.id,
            "project_code": repo.project_code,
            "project_name": repo.project_name,
            "project_card": repo.project_card,
            "has_repo": has_repo(repo),
            "enabled_agent_keys": agent_keys_by_repo.get(repo.id, []),
        }
        for repo in visible_repos
    ]
    return {
        "projects": projects,
        "count": len(projects),
        "truncated": truncated,
    }


async def replace_agent_keys(
    db: AsyncSession,
    repo: ProjectRepo,
    agent_keys: Optional[Iterable[str]] = None,
) -> List[str]:
    normalized = normalize_agent_keys(agent_keys, repo)
    await db.execute(
        sa_delete(ProjectRepoAgent).where(ProjectRepoAgent.project_repo_id == repo.id)
    )
    now = datetime.utcnow()
    for key in normalized:
        db.add(
            ProjectRepoAgent(
                project_repo_id=repo.id,
                agent_key=key,
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()
    logger.info(
        "Updated project_repo agents id=%d agents=%s",
        repo.id,
        ",".join(normalized),
    )
    return normalized


async def reconcile_agent_keys(db: AsyncSession, repo: ProjectRepo) -> List[str]:
    """按当前 repo_url 清理不再兼容的 Agent，并保证至少一个有效 Agent。"""
    result = await db.execute(
        select(ProjectRepoAgent.agent_key)
        .where(ProjectRepoAgent.project_repo_id == repo.id)
        .order_by(ProjectRepoAgent.id)
    )
    stored = list(result.scalars().all())
    effective = _effective_agent_keys(repo, stored if stored else None)
    return await replace_agent_keys(db, repo, effective)


async def supports_agent(
    db: AsyncSession,
    repo: Optional[ProjectRepo],
    agent_key: str,
) -> bool:
    if repo is None or not getattr(repo, "enabled", True):
        return False
    if agent_key not in PROJECT_AGENT_REGISTRY or not _is_agent_compatible(repo, agent_key):
        return False
    keys = await list_agent_keys(db, repo)
    return agent_key in keys


# ─────────────────────── Write ─────────────────────────────────────

async def create(
    db: AsyncSession,
    *,
    project_code: str,
    project_name: str,
    repo_url: Optional[str] = None,
    default_branch: str = "main",
    git_token: Optional[str] = None,
    project_card: str,
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
        project_card=normalize_project_card(project_card),
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
    project_card: Optional[str] = None,
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
    if project_card is not None:
        repo.project_card = normalize_project_card(project_card)
    if enabled is not None:
        repo.enabled = enabled
    if not has_repo(repo):
        repo.git_token = None
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
