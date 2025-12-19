"""
Admin endpoints for prompt configuration management.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.security.admin_auth import ADMIN_TOKEN_HEADER, ADMIN_TOKEN_PREFIX, auth_manager
from app.services.prompts_config_service import (
    load_prompts_config,
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

