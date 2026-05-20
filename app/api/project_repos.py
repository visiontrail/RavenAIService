"""公共只读项目仓库 API（供日志分析 UI 选择项目使用）。

与 ``app/api/admin.py`` 中的管理端 CRUD 不同，这里只暴露最少字段（不含
git_token、url 等敏感信息），且无管理员鉴权，方便普通用户在触发 AI 分析
时直接挑选已注册的项目。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.models.database import get_db
from app.services import project_repo_service

router = APIRouter(prefix="/api/v1/project-repos", tags=["项目仓库"])


class ProjectRepoOption(BaseModel):
    id: int
    project_code: str
    project_name: str
    default_branch: str
    description: Optional[str] = None


class ProjectRepoOptionListResponse(BaseModel):
    success: bool = True
    data: List[ProjectRepoOption]
    message: str = "ok"


@router.get("", response_model=ProjectRepoOptionListResponse)
async def list_enabled_project_repos(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    db=Depends(get_db),
) -> ProjectRepoOptionListResponse:
    """列出所有已启用的项目仓库（仅返回展示用字段）。"""
    repos = await project_repo_service.list_repos(
        db, include_disabled=False, offset=offset, limit=limit
    )
    items = [
        ProjectRepoOption(
            id=repo.id,
            project_code=repo.project_code,
            project_name=repo.project_name,
            default_branch=repo.default_branch,
            description=repo.description,
        )
        for repo in repos
    ]
    return ProjectRepoOptionListResponse(data=items)
