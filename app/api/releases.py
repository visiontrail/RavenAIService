"""
App Release 管理端点
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from starlette.responses import Response
from pydantic import BaseModel

from app.api.admin import require_admin
from app.api.users import get_request_locale
from app.config import settings
from app.i18n.messages import t

BASE_DIR = Path(settings.base_dir)
RELEASES_DIR = BASE_DIR / "data" / "releases"
RELEASES_META_FILE = BASE_DIR / "data" / "releases.json"


def _ensure_releases_dir() -> None:
    RELEASES_DIR.mkdir(parents=True, exist_ok=True)

VALID_PLATFORMS = ("linux", "macos", "windows")

admin_router = APIRouter(prefix="/admin/releases", tags=["Admin"])
public_router = APIRouter(prefix="/api/v1/releases", tags=["Releases"])


class ReleaseItem(BaseModel):
    id: str
    platform: str
    version: str
    filename: str
    file_size: int
    description: Optional[str] = None
    download_count: int = 0
    created_at: str


class ReleaseListResponse(BaseModel):
    success: bool = True
    data: List[ReleaseItem]
    message: str = "ok"


class ReleaseResponse(BaseModel):
    success: bool = True
    data: ReleaseItem
    message: str = "ok"


def _load_releases() -> List[dict]:
    if not RELEASES_META_FILE.exists():
        return []
    try:
        with open(RELEASES_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_releases(releases: List[dict]) -> None:
    RELEASES_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RELEASES_META_FILE, "w", encoding="utf-8") as f:
        json.dump(releases, f, ensure_ascii=False, indent=2)


def _to_item(r: dict) -> ReleaseItem:
    return ReleaseItem(
        id=r["id"],
        platform=r["platform"],
        version=r["version"],
        filename=r["filename"],
        file_size=r.get("file_size", 0),
        description=r.get("description"),
        download_count=r.get("download_count", 0),
        created_at=r.get("created_at", ""),
    )


# 兼容旧前端(/upload)与新语义化路径(POST /admin/releases)两种上传地址
@admin_router.post("", response_model=ReleaseResponse)
@admin_router.post("/upload", response_model=ReleaseResponse)
async def upload_release(
    platform: str = Form(...),
    version: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    _username: str = Depends(require_admin),
    locale: str = Depends(get_request_locale),
) -> ReleaseResponse:
    if platform not in VALID_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t(
                "release.invalid_platform",
                locale,
                platforms=", ".join(VALID_PLATFORMS),
            ),
        )
    if not version.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("release.version_empty", locale),
        )

    _ensure_releases_dir()

    release_id = str(uuid.uuid4())
    safe_filename = file.filename or f"release-{release_id}"
    dest_path = RELEASES_DIR / f"{release_id}_{safe_filename}"

    try:
        content = await file.read()
        with open(dest_path, "wb") as f_out:
            f_out.write(content)
        file_size = dest_path.stat().st_size
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=t("release.save_failed", locale, error=exc),
        )

    release: dict = {
        "id": release_id,
        "platform": platform,
        "version": version.strip(),
        "filename": safe_filename,
        "file_path": str(dest_path),
        "file_size": file_size,
        "description": description.strip() or None,
        "download_count": 0,
        "created_at": datetime.utcnow().isoformat(),
    }

    releases = _load_releases()
    releases.append(release)
    _save_releases(releases)

    return ReleaseResponse(
        data=_to_item(release), message=t("release.upload_success", locale)
    )


@admin_router.options("")
@admin_router.options("/upload")
async def upload_release_options() -> Response:
    # 某些代理场景下 OPTIONS 可能绕过 CORS 处理中间件，这里显式兜底避免 405
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("", response_model=ReleaseListResponse)
async def list_releases_admin(
    _username: str = Depends(require_admin),
) -> ReleaseListResponse:
    releases = _load_releases()
    items = sorted(
        [_to_item(r) for r in releases],
        key=lambda x: x.created_at,
        reverse=True,
    )
    return ReleaseListResponse(data=items)


@admin_router.delete("/{release_id}")
async def delete_release(
    release_id: str,
    _username: str = Depends(require_admin),
    locale: str = Depends(get_request_locale),
) -> dict:
    releases = _load_releases()
    target = next((r for r in releases if r["id"] == release_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("release.not_found", locale),
        )

    file_path = Path(target["file_path"])
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass

    releases = [r for r in releases if r["id"] != release_id]
    _save_releases(releases)
    return {"success": True, "message": t("release.deleted", locale)}


@public_router.get("", response_model=ReleaseListResponse)
async def list_releases_public() -> ReleaseListResponse:
    releases = _load_releases()
    items = sorted(
        [_to_item(r) for r in releases],
        key=lambda x: x.created_at,
        reverse=True,
    )
    return ReleaseListResponse(data=items)


@public_router.get("/{release_id}/download")
async def download_release(
    release_id: str,
    locale: str = Depends(get_request_locale),
) -> FileResponse:
    releases = _load_releases()
    target = next((r for r in releases if r["id"] == release_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("release.not_found", locale),
        )

    file_path = Path(target["file_path"])
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("release.file_missing", locale),
        )

    for r in releases:
        if r["id"] == release_id:
            r["download_count"] = r.get("download_count", 0) + 1
            break
    _save_releases(releases)

    return FileResponse(
        path=str(file_path),
        filename=target["filename"],
        media_type="application/octet-stream",
    )
