"""Unified Raven package API.

These endpoints replace the legacy Node package service while preserving the
same `/packages`, `/upload`, `/download`, and `/search` API shapes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services.raven_package_service import raven_package_service

router = APIRouter()


def _ok(data: Any = None, message: str = "ok", **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return payload


def _metadata_fields(
    version: Optional[str] = None,
    packageType: Optional[str] = None,
    description: Optional[str] = None,
    isPatch: Optional[str] = None,
    tags: Optional[str] = None,
    components: Optional[str] = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in {
        "version": version,
        "packageType": packageType,
        "description": description,
        "isPatch": isPatch,
        "tags": tags,
        "components": components,
    }.items():
        if value is not None:
            fields[key] = value
    return fields


def _parse_package_info(packageInfo: Optional[str]) -> Optional[dict[str, Any]]:
    if not packageInfo:
        return None
    try:
        parsed = json.loads(packageInfo)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"无效的 packageInfo JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="packageInfo 必须是 JSON object")
    return parsed


@router.get("/packages")
async def list_packages(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1),
    search: str = "",
    type: str = "",
    tags: str = "",
    version: str = "",
    isPatch: str = "",
    sortBy: str = "createdAt",
    sortOrder: str = "desc",
) -> dict[str, Any]:
    packages, pagination = raven_package_service.filter_packages(
        {
            "page": page,
            "limit": limit,
            "search": search,
            "type": type,
            "tags": tags,
            "version": version,
            "isPatch": isPatch,
            "sortBy": sortBy,
            "sortOrder": sortOrder,
        }
    )
    return _ok({"packages": packages, "pagination": pagination})


@router.get("/packages/stats/overview")
async def package_stats() -> dict[str, Any]:
    packages = raven_package_service.get_all_packages()
    by_type: dict[str, int] = {}
    for package in packages:
        package_type = str(package.get("packageType") or "unknown")
        by_type[package_type] = by_type.get(package_type, 0) + 1
    recent = sorted(packages, key=lambda pkg: str(pkg.get("createdAt") or ""), reverse=True)[:5]
    return _ok(
        {
            "totalPackages": len(packages),
            "packagesByType": by_type,
            "recentPackages": [
                {
                    "id": pkg.get("id"),
                    "name": pkg.get("name"),
                    "version": pkg.get("version"),
                    "createdAt": pkg.get("createdAt"),
                }
                for pkg in recent
            ],
        }
    )


@router.post("/packages/scan")
async def scan_packages() -> dict[str, Any]:
    added = raven_package_service.scan_uploads_directory()
    return _ok({"added": added}, message="扫描完成")


@router.get("/packages/{package_id}")
async def get_package(package_id: str) -> dict[str, Any]:
    package = raven_package_service.get_package(package_id)
    if not package:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="包不存在")
    return _ok(package)


@router.delete("/packages/{package_id}")
async def delete_package(package_id: str) -> dict[str, Any]:
    if not raven_package_service.delete_package(package_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="包不存在或删除失败")
    raven_package_service.rebuild_search_index()
    return _ok(message="包删除成功")


@router.post("/upload")
async def upload_package(
    file: UploadFile = File(...),
    packageInfo: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    packageType: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    isPatch: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    components: Optional[str] = Form(None),
) -> dict[str, Any]:
    file_path, size, sha256 = await raven_package_service.store_upload(file)
    try:
        package = raven_package_service.build_package_info(
            file_path=file_path,
            size=size,
            sha256=sha256,
            metadata_fields=_metadata_fields(version, packageType, description, isPatch, tags, components),
            package_info=_parse_package_info(packageInfo),
        )
        saved = raven_package_service.add_or_update_package(package)
        raven_package_service.rebuild_search_index()
        return _ok(message="包上传成功", package=saved, vectorIndexRebuild="completed")
    except Exception:
        raven_package_service.cleanup_file(file_path)
        raise


@router.post("/upload/batch")
async def upload_package_batch(request: Request) -> dict[str, Any]:
    form = await request.form()
    files = list(form.getlist("file")) or list(form.getlist("files"))
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有上传文件")

    fields = _metadata_fields(
        version=form.get("version"),
        packageType=form.get("packageType"),
        description=form.get("description"),
        isPatch=form.get("isPatch"),
        tags=form.get("tags"),
        components=form.get("components"),
    )
    results = []
    errors = []
    for upload in files:
        if not hasattr(upload, "filename") or not hasattr(upload, "read"):
            continue
        try:
            file_path, size, sha256 = await raven_package_service.store_upload(upload)
            package = raven_package_service.build_package_info(file_path, size, sha256, metadata_fields=fields)
            results.append(raven_package_service.add_or_update_package(package))
        except Exception as exc:
            errors.append({"filename": getattr(upload, "filename", ""), "error": str(exc)})

    if results:
        raven_package_service.rebuild_search_index()

    return _ok(
        message=f"成功上传 {len(results)} 个包",
        packages=results,
        errors=errors or None,
        vectorIndexRebuild="completed" if results else "skipped",
    )


@router.get("/upload/progress/{upload_id}")
async def upload_progress(upload_id: str) -> dict[str, Any]:
    return {"uploadId": upload_id, "progress": 100, "status": "completed"}


@router.get("/download/stats")
async def download_stats() -> dict[str, Any]:
    packages = raven_package_service.get_all_packages()
    by_type: dict[str, int] = {}
    for package in packages:
        package_type = str(package.get("packageType") or package.get("type") or "unknown")
        by_type[package_type] = by_type.get(package_type, 0) + 1
    return _ok({"totalDownloads": 0, "popularPackages": packages[:5], "downloadsByType": by_type})


@router.post("/download/batch")
async def download_batch(request: Request) -> FileResponse:
    body = await request.json()
    package_ids = body.get("packageIds")
    if not isinstance(package_ids, list) or not package_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Package IDs are required")
    packages = [pkg for pkg_id in package_ids if (pkg := raven_package_service.get_package(str(pkg_id)))]
    if not packages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No valid packages found")
    zip_path = raven_package_service.build_zip(packages)
    filename = f"packages-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return FileResponse(
        str(zip_path),
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(raven_package_service.cleanup_file, zip_path),
    )


@router.get("/download/type/{package_type}")
async def download_by_type(package_type: str, version: Optional[str] = None) -> FileResponse:
    packages = [
        pkg for pkg in raven_package_service.get_all_packages()
        if pkg.get("packageType") == package_type and (not version or pkg.get("version") == version)
    ]
    if not packages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No packages found for the specified criteria")
    if len(packages) == 1:
        return _package_file_response(packages[0])
    zip_path = raven_package_service.build_zip(packages, prefix=f"{package_type}-packages")
    filename = f"{package_type}-packages-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return FileResponse(
        str(zip_path),
        filename=filename,
        media_type="application/zip",
        background=BackgroundTask(raven_package_service.cleanup_file, zip_path),
    )


@router.get("/download/{package_id}")
async def download_package(package_id: str) -> FileResponse:
    package = raven_package_service.get_package(package_id)
    if not package:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package not found")
    return _package_file_response(package)


def _package_file_response(package: dict[str, Any]) -> FileResponse:
    file_path = raven_package_service.package_file(package)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package file not found")
    return FileResponse(
        str(file_path),
        filename=str(package.get("name") or Path(file_path).name),
        media_type="application/gzip",
    )


@router.get("/search/status")
async def search_status() -> dict[str, Any]:
    return _ok(raven_package_service.search_status())


@router.post("/search/rebuild-index")
async def rebuild_index() -> dict[str, Any]:
    meta = raven_package_service.rebuild_search_index()
    return _ok(meta, message=f"向量索引重建成功，共索引 {meta['totalPackages']} 个包")


@router.post("/search/similarity")
async def similarity_search(request: Request) -> dict[str, Any]:
    body = await request.json()
    query = str(body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="搜索查询不能为空")
    return _ok(raven_package_service.similarity_search(query, int(body.get("limit") or 5)))


@router.post("/search/intelligent")
async def intelligent_search(request: Request) -> dict[str, Any]:
    body = await request.json()
    query = str(body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="搜索查询不能为空")
    return _ok(raven_package_service.intelligent_search(query, int(body.get("limit") or 5)))


@router.post("/search/suggestions")
async def search_suggestions(request: Request) -> dict[str, Any]:
    body = await request.json()
    query = str(body.get("query") or "").strip()
    return _ok(raven_package_service.suggestions(query))
