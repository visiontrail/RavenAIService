"""
Admin endpoints for prompt configuration and repo settings management.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.models.database import get_db
from app.security.admin_auth import ADMIN_TOKEN_HEADER, ADMIN_TOKEN_PREFIX, auth_manager
from app.services import project_repo_service
from app.services.prompts_config_service import (
    load_prompts_config,
    update_prompts_config,
)
from app.services.repo_settings_service import (
    load_repo_settings,
    save_repo_settings,
    test_repo_connection,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


class AdminAuthData(BaseModel):
    username: str
    token: str
    expires_at: datetime
    ttl_minutes: int


class AdminAuthResponse(BaseModel):
    success: bool = True
    data: AdminAuthData
    message: str = "登录成功"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class MeResponse(BaseModel):
    success: bool = True
    data: dict
    message: str = "ok"


class PromptsSummary(BaseModel):
    log_type_keys: list[str] = Field(default_factory=list)
    has_default_plan: bool = False
    has_default_summary: bool = False


class PromptsConfigData(BaseModel):
    path: str
    content: str
    updated_at: datetime
    size: int
    checksum: str
    summary: PromptsSummary


class PromptsConfigResponse(BaseModel):
    success: bool = True
    data: PromptsConfigData
    message: str = "ok"


class UpdatePromptsRequest(BaseModel):
    content: str
    expected_checksum: Optional[str] = None
    force: bool = False


bearer_scheme = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """Validate bearer token from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported auth scheme",
        )
    return auth_manager.validate_token(credentials.credentials)


@router.post("/auth/login", response_model=AdminAuthResponse)
async def admin_login(payload: LoginRequest) -> AdminAuthResponse:
    token, expires_at = auth_manager.verify_credentials(
        payload.username, payload.password
    )
    return AdminAuthResponse(
        data=AdminAuthData(
            username=payload.username,
            token=token,
            expires_at=datetime.fromtimestamp(expires_at),
            ttl_minutes=auth_manager.token_ttl_minutes(),
        )
    )


@router.post("/auth/logout", response_model=MeResponse)
async def admin_logout() -> MeResponse:
    # Client-side token drop; we remain stateless on the server
    return MeResponse(message="已退出登录", data={})


@router.get("/auth/me", response_model=MeResponse)
async def auth_me(username: str = Depends(require_admin)) -> MeResponse:
    return MeResponse(data={"username": username})


@router.get("/prompts/config", response_model=PromptsConfigResponse)
async def get_prompts_config(
    _username: str = Depends(require_admin),
) -> PromptsConfigResponse:
    data = load_prompts_config()
    return PromptsConfigResponse(
        data=PromptsConfigData(**data),
        message="读取成功",
    )


@router.put("/prompts/config", response_model=PromptsConfigResponse)
async def save_prompts_config(
    payload: UpdatePromptsRequest,
    _username: str = Depends(require_admin),
) -> PromptsConfigResponse:
    data = update_prompts_config(
        new_content=payload.content,
        expected_checksum=payload.expected_checksum,
        force=payload.force,
    )
    return PromptsConfigResponse(
        data=PromptsConfigData(**data),
        message="保存成功",
    )


# ─────────────────── Repo Settings ────────────────────────────────

class RepoSettingsData(BaseModel):
    oam_url: str = ""
    oam_url_deprecated: bool = True
    stack_url: str = ""
    stack_url_deprecated: bool = True
    git_token_set: bool = False
    clone_depth: int = 1
    updated_at: str = ""
    warnings: List[str] = Field(default_factory=list)


class RepoSettingsResponse(BaseModel):
    success: bool = True
    data: RepoSettingsData
    message: str = "ok"


class UpdateRepoSettingsRequest(BaseModel):
    oam_url: Optional[str] = None
    stack_url: Optional[str] = None
    git_token: Optional[str] = None
    clone_depth: int = Field(default=1, ge=1, le=100)
    clear_token: bool = False


class TestConnectionRequest(BaseModel):
    url: str
    token: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool = True
    data: dict
    message: str = "ok"


@router.get("/repo-settings", response_model=RepoSettingsResponse)
async def get_repo_settings(
    _username: str = Depends(require_admin),
) -> RepoSettingsResponse:
    """读取当前 Git 代码仓库配置（oam_url/stack_url 已弃用，请使用 /admin/project-repos）。"""
    cfg = load_repo_settings()
    return RepoSettingsResponse(
        data=RepoSettingsData(
            oam_url=cfg.oam_url,
            oam_url_deprecated=True,
            stack_url=cfg.stack_url,
            stack_url_deprecated=True,
            git_token_set=cfg.git_token_set,
            clone_depth=cfg.clone_depth,
            updated_at=cfg.updated_at,
            warnings=["oam_url and stack_url are deprecated; use /admin/project-repos"],
        ),
        message="读取成功",
    )


@router.put("/repo-settings", response_model=RepoSettingsResponse)
async def update_repo_settings(
    payload: UpdateRepoSettingsRequest,
    _username: str = Depends(require_admin),
) -> RepoSettingsResponse:
    """保存 Git 代码仓库配置（oam_url/stack_url 已弃用，写入被忽略）。"""
    try:
        cfg = save_repo_settings(
            oam_url     = None,   # deprecated: ignored
            stack_url   = None,   # deprecated: ignored
            git_token   = payload.git_token,
            clone_depth = payload.clone_depth,
            clear_token = payload.clear_token,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存失败: {exc}",
        ) from exc

    warnings = []
    if payload.oam_url is not None or payload.stack_url is not None:
        warnings.append("oam_url/stack_url ignored; use /admin/project-repos")

    return RepoSettingsResponse(
        data=RepoSettingsData(
            oam_url       = cfg.oam_url,
            stack_url     = cfg.stack_url,
            git_token_set = cfg.git_token_set,
            clone_depth   = cfg.clone_depth,
            updated_at    = cfg.updated_at,
            warnings      = warnings,
        ),
        message="保存成功，配置已立即生效",
    )


@router.post("/repo-settings/test-connection", response_model=TestConnectionResponse)
async def test_repo_connection_endpoint(
    payload: TestConnectionRequest,
    _username: str = Depends(require_admin),
) -> TestConnectionResponse:
    """测试指定 URL 的 Git 仓库连通性（支持 Token 认证）。"""
    if not payload.url or not payload.url.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="url 不能为空",
        )
    result = test_repo_connection(
        url   = payload.url.strip(),
        token = payload.token or None,
    )
    return TestConnectionResponse(
        success = result["success"],
        data    = result,
        message = result["message"],
    )


# ─────────────────── Project Repo Registry ────────────────────────

class ProjectRepoData(BaseModel):
    id: int
    project_code: str
    project_name: str
    repo_url: str
    default_branch: str
    git_token_set: bool
    description: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProjectRepoListResponse(BaseModel):
    success: bool = True
    data: List[ProjectRepoData]
    message: str = "ok"


class ProjectRepoResponse(BaseModel):
    success: bool = True
    data: ProjectRepoData
    message: str = "ok"


class CreateProjectRepoRequest(BaseModel):
    project_code: str = Field(..., min_length=1, max_length=128)
    project_name: str = Field(..., min_length=1, max_length=256)
    repo_url: str = Field(..., min_length=1)
    default_branch: str = Field(default="main", max_length=128)
    git_token: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True


class UpdateProjectRepoRequest(BaseModel):
    project_name: Optional[str] = None
    repo_url: Optional[str] = None
    default_branch: Optional[str] = None
    git_token: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


def _repo_to_data(repo) -> ProjectRepoData:
    return ProjectRepoData(
        id=repo.id,
        project_code=repo.project_code,
        project_name=repo.project_name,
        repo_url=repo.repo_url,
        default_branch=repo.default_branch,
        git_token_set=bool(repo.git_token),
        description=repo.description,
        enabled=repo.enabled,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
    )


@router.get("/project-repos", response_model=ProjectRepoListResponse)
async def list_project_repos(
    include_disabled: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> ProjectRepoListResponse:
    repos = await project_repo_service.list_repos(
        db, include_disabled=include_disabled, offset=offset, limit=limit
    )
    return ProjectRepoListResponse(data=[_repo_to_data(r) for r in repos])


@router.post("/project-repos", response_model=ProjectRepoResponse, status_code=status.HTTP_201_CREATED)
async def create_project_repo(
    payload: CreateProjectRepoRequest,
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> ProjectRepoResponse:
    try:
        repo = await project_repo_service.create(
            db,
            project_code=payload.project_code,
            project_name=payload.project_name,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            git_token=payload.git_token,
            description=payload.description,
            enabled=payload.enabled,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"创建失败: {exc}",
        ) from exc
    return ProjectRepoResponse(data=_repo_to_data(repo), message="创建成功")


@router.get("/project-repos/{repo_id}", response_model=ProjectRepoResponse)
async def get_project_repo(
    repo_id: int,
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> ProjectRepoResponse:
    repo = await project_repo_service.get_by_id(db, repo_id)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    return ProjectRepoResponse(data=_repo_to_data(repo))


@router.put("/project-repos/{repo_id}", response_model=ProjectRepoResponse)
async def update_project_repo(
    repo_id: int,
    payload: UpdateProjectRepoRequest,
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> ProjectRepoResponse:
    repo = await project_repo_service.get_by_id(db, repo_id)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    try:
        repo = await project_repo_service.update(
            db,
            repo,
            project_name=payload.project_name,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            git_token=payload.git_token,
            description=payload.description,
            enabled=payload.enabled,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"更新失败: {exc}",
        ) from exc
    return ProjectRepoResponse(data=_repo_to_data(repo), message="更新成功")


@router.delete("/project-repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_repo(
    repo_id: int,
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> None:
    repo = await project_repo_service.get_by_id(db, repo_id)
    if not repo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在")
    await project_repo_service.delete(db, repo)


@router.post("/project-repos/{repo_id}/test-connection", response_model=TestConnectionResponse)
async def test_project_repo_connection(
    repo_id: int,
    _username: str = Depends(require_admin),
    db=Depends(get_db),
) -> TestConnectionResponse:
    result = await project_repo_service.test_connection(db, repo_id)
    return TestConnectionResponse(
        success=result["success"],
        data=result,
        message=result["message"],
    )

