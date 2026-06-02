"""
Admin endpoints for prompt configuration and repo settings management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.models.database import get_db
from app.security.admin_auth import ADMIN_TOKEN_HEADER, ADMIN_TOKEN_PREFIX, auth_manager
from app.services import project_repo_service, skills_service
from app.services.prompts_config_service import (
    load_prompts_config,
    update_prompt_entries,
    update_prompts_config,
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
    function_keys: list[str] = Field(default_factory=list)
    editable_prompt_count: int = 0


class PromptEntryData(BaseModel):
    id: str
    function_key: str
    function_name: str
    function_description: Optional[str] = None
    agent_key: str
    agent_name: str
    agent_description: Optional[str] = None
    prompt_key: str
    prompt_label: str
    prompt_type: str
    path: list[str]
    content: str


class PromptsConfigData(BaseModel):
    path: str
    content: str
    updated_at: datetime
    size: int
    checksum: str
    summary: PromptsSummary
    prompts: list[PromptEntryData] = Field(default_factory=list)


class PromptsConfigResponse(BaseModel):
    success: bool = True
    data: PromptsConfigData
    message: str = "ok"


class UpdatePromptsRequest(BaseModel):
    content: Optional[str] = None
    prompts: Optional[list[dict[str, str]]] = None
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
    if payload.prompts is not None:
        data = update_prompt_entries(
            prompt_updates=payload.prompts,
            expected_checksum=payload.expected_checksum,
            force=payload.force,
        )
    elif payload.content is not None:
        data = update_prompts_config(
            new_content=payload.content,
            expected_checksum=payload.expected_checksum,
            force=payload.force,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either prompts or content is required.",
        )
    return PromptsConfigResponse(
        data=PromptsConfigData(**data),
        message="保存成功",
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


class TestConnectionResponse(BaseModel):
    success: bool = True
    data: dict
    message: str = "ok"


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


# ─────────────────── Agent Skills Management ──────────────────────

class AgentInfo(BaseModel):
    key: str
    name: str
    framework: str
    description: Optional[str] = None


class AgentListResponse(BaseModel):
    success: bool = True
    data: List[AgentInfo]
    message: str = "ok"


class SkillData(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    source_filename: str = ""
    size_bytes: int = 0
    installed_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillListResponse(BaseModel):
    success: bool = True
    data: List[SkillData]
    message: str = "ok"


class SkillResponse(BaseModel):
    success: bool = True
    data: SkillData
    message: str = "ok"


class UpdateSkillRequest(BaseModel):
    enabled: bool


class SkillFilesResponse(BaseModel):
    success: bool = True
    data: Dict[str, Any]
    message: str = "ok"


class SkillFileContent(BaseModel):
    path: str
    size: int
    encoding: str
    content: Optional[str] = None
    truncated: bool = False


class SkillFileContentResponse(BaseModel):
    success: bool = True
    data: SkillFileContent
    message: str = "ok"


def _ensure_known_agent(agent_key: str) -> None:
    if agent_key not in skills_service.SUPPORTED_AGENTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown agent_key: {agent_key}",
        )


@router.get("/agents", response_model=AgentListResponse)
async def list_skill_agents(
    _username: str = Depends(require_admin),
) -> AgentListResponse:
    """列出支持加载 Skill 的 Agent。"""
    return AgentListResponse(
        data=[AgentInfo(**item) for item in skills_service.list_agents()]
    )


@router.get("/agents/{agent_key}/skills", response_model=SkillListResponse)
async def list_agent_skills(
    agent_key: str,
    _username: str = Depends(require_admin),
) -> SkillListResponse:
    _ensure_known_agent(agent_key)
    try:
        items = skills_service.list_skills(agent_key)
    except skills_service.UnknownAgentError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SkillListResponse(data=[SkillData(**item) for item in items])


@router.post(
    "/agents/{agent_key}/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_agent_skill(
    agent_key: str,
    file: UploadFile = File(..., description="Skill zip 包"),
    overwrite: bool = Query(default=False),
    _username: str = Depends(require_admin),
) -> SkillResponse:
    """上传 zip 格式的 Skill 包并安装到指定 Agent。"""
    _ensure_known_agent(agent_key)

    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传 .zip 格式的 Skill 包",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容为空")

    try:
        entry = skills_service.install_skill(
            agent_key,
            zip_bytes=payload,
            source_filename=filename,
            overwrite=overwrite,
        )
    except skills_service.SkillConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except skills_service.SkillError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SkillResponse(data=SkillData(**entry), message="上传成功")


@router.patch("/agents/{agent_key}/skills/{skill_id}", response_model=SkillResponse)
async def update_agent_skill(
    agent_key: str,
    skill_id: str,
    payload: UpdateSkillRequest,
    _username: str = Depends(require_admin),
) -> SkillResponse:
    _ensure_known_agent(agent_key)
    try:
        entry = skills_service.set_skill_enabled(
            agent_key, skill_id, enabled=payload.enabled
        )
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SkillResponse(data=SkillData(**entry), message="更新成功")


@router.get(
    "/agents/{agent_key}/skills/{skill_id}/files",
    response_model=SkillFilesResponse,
)
async def list_agent_skill_files(
    agent_key: str,
    skill_id: str,
    _username: str = Depends(require_admin),
) -> SkillFilesResponse:
    """列出某个 Skill 目录的文件树，用于左侧导航预览。"""
    _ensure_known_agent(agent_key)
    try:
        data = skills_service.list_skill_files(agent_key, skill_id)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return SkillFilesResponse(data=data)


@router.get(
    "/agents/{agent_key}/skills/{skill_id}/file",
    response_model=SkillFileContentResponse,
)
async def get_agent_skill_file(
    agent_key: str,
    skill_id: str,
    path: str = Query(..., description="Skill 目录下的相对路径"),
    _username: str = Depends(require_admin),
) -> SkillFileContentResponse:
    """读取 Skill 目录下指定文件的内容（文本类型才返回正文）。"""
    _ensure_known_agent(agent_key)
    try:
        data = skills_service.read_skill_file(agent_key, skill_id, path)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return SkillFileContentResponse(data=SkillFileContent(**data))


@router.delete(
    "/agents/{agent_key}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_agent_skill(
    agent_key: str,
    skill_id: str,
    _username: str = Depends(require_admin),
) -> None:
    _ensure_known_agent(agent_key)
    try:
        skills_service.delete_skill(agent_key, skill_id)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Project-level Skill endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/project-repos/{project_code}/skills",
    response_model=SkillListResponse,
)
async def list_project_skills(
    project_code: str,
    _username: str = Depends(require_admin),
) -> SkillListResponse:
    items = skills_service.list_project_skills(project_code)
    return SkillListResponse(data=[SkillData(**item) for item in items])


@router.post(
    "/project-repos/{project_code}/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_skill(
    project_code: str,
    file: UploadFile = File(..., description="Skill zip 包"),
    overwrite: bool = Query(default=False),
    _username: str = Depends(require_admin),
) -> SkillResponse:
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持上传 .zip 格式的 Skill 包",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容为空")

    try:
        entry = skills_service.install_project_skill(
            project_code,
            zip_bytes=payload,
            source_filename=filename,
            overwrite=overwrite,
        )
    except skills_service.SkillConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except skills_service.SkillError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return SkillResponse(data=SkillData(**entry), message="上传成功")


@router.patch(
    "/project-repos/{project_code}/skills/{skill_id}",
    response_model=SkillResponse,
)
async def update_project_skill(
    project_code: str,
    skill_id: str,
    payload: UpdateSkillRequest,
    _username: str = Depends(require_admin),
) -> SkillResponse:
    try:
        entry = skills_service.set_project_skill_enabled(
            project_code, skill_id, enabled=payload.enabled
        )
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SkillResponse(data=SkillData(**entry), message="更新成功")


@router.delete(
    "/project-repos/{project_code}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_skill(
    project_code: str,
    skill_id: str,
    _username: str = Depends(require_admin),
) -> None:
    try:
        skills_service.delete_project_skill(project_code, skill_id)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/project-repos/{project_code}/skills/{skill_id}/files",
    response_model=SkillFilesResponse,
)
async def list_project_skill_files(
    project_code: str,
    skill_id: str,
    _username: str = Depends(require_admin),
) -> SkillFilesResponse:
    try:
        data = skills_service.list_project_skill_files(project_code, skill_id)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return SkillFilesResponse(data=data)


@router.get(
    "/project-repos/{project_code}/skills/{skill_id}/file",
    response_model=SkillFileContentResponse,
)
async def get_project_skill_file(
    project_code: str,
    skill_id: str,
    path: str = Query(..., description="Skill 目录下的相对路径"),
    _username: str = Depends(require_admin),
) -> SkillFileContentResponse:
    try:
        data = skills_service.read_project_skill_file(project_code, skill_id, path)
    except skills_service.SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except skills_service.SkillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return SkillFileContentResponse(data=SkillFileContent(**data))
