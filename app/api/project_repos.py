"""公共只读项目仓库 API（供日志分析 UI 选择项目使用）。

与 ``app/api/admin.py`` 中的管理端 CRUD 不同，这里只暴露最少字段（不含
git_token、url 等敏感信息），且无管理员鉴权，方便普通用户在触发 AI 分析
时直接挑选已注册的项目。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.database import get_db
from app.services import project_repo_service

router = APIRouter(prefix="/api/v1/project-repos", tags=["项目仓库"])


class ProjectRepoOption(BaseModel):
    id: int
    project_code: str
    project_name: str
    default_branch: str
    has_repo: bool = False
    enabled_agent_keys: List[str] = Field(default_factory=list)
    project_card: str


class ProjectRepoOptionListResponse(BaseModel):
    success: bool = True
    data: List[ProjectRepoOption]
    message: str = "ok"


@router.get("", response_model=ProjectRepoOptionListResponse)
async def list_enabled_project_repos(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    with_repo: Optional[bool] = Query(
        default=None,
        description=(
            "为 true 仅返回已关联代码仓库的项目；为 false 仅返回未关联的项目；"
            "不传返回全部。未关联代码仓库的项目仅项目专家可见。"
        ),
    ),
    agent_key: Optional[str] = Query(
        default=None,
        description=(
            "可选：仅返回启用了指定 Agent 的项目，取值如 "
            "project_expert/log_analysis/package_search。"
        ),
    ),
    db=Depends(get_db),
) -> ProjectRepoOptionListResponse:
    """列出所有已启用的项目（仅返回展示用字段）。

    通过 ``with_repo`` 过滤是否关联代码仓库：日志分析、包检索等 Agent 应传
    ``with_repo=true``，从而对「未关联代码仓库」的项目不可见；项目专家则可
    看到全部项目。``has_repo`` 字段也会一并返回，便于前端按所选 Agent 过滤。
    """
    requested_agent = (agent_key or "").strip()
    if requested_agent and requested_agent not in project_repo_service.PROJECT_AGENT_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent_key: {requested_agent}",
        )

    repos = await project_repo_service.list_repos(
        db,
        include_disabled=False,
        offset=0 if requested_agent else offset,
        limit=10_000 if requested_agent else limit,
        with_repo=with_repo,
    )
    agent_keys_by_repo = await project_repo_service.list_agent_keys_bulk(db, repos)
    if requested_agent:
        repos = [
            repo
            for repo in repos
            if requested_agent in agent_keys_by_repo.get(repo.id, [])
        ][offset : offset + limit]
    items = [
        ProjectRepoOption(
            id=repo.id,
            project_code=repo.project_code,
            project_name=repo.project_name,
            default_branch=repo.default_branch,
            has_repo=project_repo_service.has_repo(repo),
            enabled_agent_keys=agent_keys_by_repo.get(repo.id, []),
            project_card=repo.project_card,
        )
        for repo in repos
    ]
    return ProjectRepoOptionListResponse(data=items)
