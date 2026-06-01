"""Unified Raven package API.

These endpoints replace the legacy Node package service while preserving the
same `/packages`, `/upload`, `/download`, and `/search` API shapes.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.api.users import get_optional_user
from app.services.raven_package_service import raven_package_service

logger = logging.getLogger(__name__)

# Hard limit for /packages/agent-search query length per spec.
PACKAGE_SEARCH_QUERY_MAX_LEN = 1000

router = APIRouter()


async def _record_package_search_metrics(result: Any, user: Any) -> None:
    """Best-effort AI usage recording for a package-search run. Never raises.

    ``result`` is the agent result dict (non-stream) or the synthetic dict built
    from the streaming ``final`` event; both expose ``model``/``usage`` and the
    recommended/relevant id lists used for the sanitized ``result_count``.
    """
    try:
        if not isinstance(result, dict):
            return
        from app.services import metrics_service

        recommended = result.get("recommended_package_ids")
        result_count = len(recommended) if isinstance(recommended, list) else 0
        session_id = result.get("session_id")
        anchor = session_id or uuid.uuid4().hex
        user_id = (
            str(user.id) if user is not None and getattr(user, "id", None) else None
        )
        await metrics_service.record_agent_run_usage(
            source="package_search_agent",
            agent_kind="package_search",
            result=result,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=f"ai_usage:package_search:{anchor}",
            extra_metadata={"result_count": result_count},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("packages: agent-search metrics record skipped: %s", exc)


async def _record_package_activity(
    *,
    action: str,
    package_type: Optional[str],
    status_value: str = "success",
    count: int = 1,
) -> None:
    """Best-effort package activity recording (upload/download/etc). Never raises.

    Persists a low-sensitivity ``package_activity`` event (action + package_type)
    and bumps the Prometheus ``raven_package_activity_total`` counter. No file
    contents, paths, or package ids are stored.
    """
    try:
        from app.services import metrics_service
        from app.utils import metrics as prom

        ptype = str(package_type or "unknown")
        await metrics_service.record_business_event(
            event_type="package_activity",
            source=f"package_{action}",
            idempotency_key=f"package_activity:{action}:{uuid.uuid4().hex}",
            status=status_value,
            metadata={"package_type": ptype, "result_count": count},
        )
        for _ in range(max(1, count)):
            prom.record_package_activity(
                action=action, package_type=ptype, status=status_value
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("packages: activity metrics record skipped: %s", exc)


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
        await _record_package_activity(
            action="upload", package_type=saved.get("packageType")
        )
        return _ok(message="包上传成功", package=saved)
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
            saved = raven_package_service.add_or_update_package(package)
            results.append(saved)
            await _record_package_activity(
                action="upload", package_type=saved.get("packageType")
            )
        except Exception as exc:
            errors.append({"filename": getattr(upload, "filename", ""), "error": str(exc)})

    return _ok(
        message=f"成功上传 {len(results)} 个包",
        packages=results,
        errors=errors or None,
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
    await _record_package_activity(
        action="download_batch", package_type=None, count=len(packages)
    )
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
    await _record_package_activity(
        action="download_type", package_type=package_type, count=len(packages)
    )
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
    response = _package_file_response(package)
    await _record_package_activity(
        action="download", package_type=package.get("packageType")
    )
    return response


def _package_file_response(package: dict[str, Any]) -> FileResponse:
    file_path = raven_package_service.package_file(package)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Package file not found")
    return FileResponse(
        str(file_path),
        filename=str(package.get("name") or Path(file_path).name),
        media_type="application/gzip",
    )


def _validate_search_query(raw: Any) -> str:
    """Coerce + validate the agent-search ``query`` field.

    Raises HTTPException 400 when:
    - missing or non-string;
    - empty / whitespace-only;
    - longer than ``PACKAGE_SEARCH_QUERY_MAX_LEN`` characters.
    """
    if not isinstance(raw, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query is required and must be a string",
        )
    text = raw.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query must not be empty",
        )
    if len(text) > PACKAGE_SEARCH_QUERY_MAX_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"query exceeds {PACKAGE_SEARCH_QUERY_MAX_LEN}-character limit",
        )
    return text


@router.post("/packages/agent-search")
async def agent_search_packages(request: Request, current_user=Depends(get_optional_user)):
    """Claude Agent SDK driven Raven package search.

    Body: ``{query: string, session_id?: string, stream?: bool}``.

    - ``stream=false`` (default): blocking JSON response with the structured
      recommendation, tool trace, model & usage.
    - ``stream=true``: ``text/event-stream`` SSE feed of
      ``AgentTraceEvent`` dicts (matching ``docs/agent_trace_protocol.md``)
      terminated by a synthetic ``final`` event whose ``data`` is the same
      payload as the non-stream response.
    """
    from app.agents.package_search.agent import PackageSearchAgent

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request body must be a JSON object",
        )
    query = _validate_search_query(body.get("query"))
    session_id = body.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id must be a string",
        )
    use_stream = bool(body.get("stream") or False)

    agent = PackageSearchAgent()

    if not use_stream:
        result = await agent.run(query, session_id=session_id)
        await _record_package_search_metrics(result, current_user)
        return {
            "answer": result["answer"],
            "recommended_package_ids": result["recommended_package_ids"],
            "relevant_package_ids": result["relevant_package_ids"],
            "notes": result.get("notes"),
            "tool_trace": result["tool_trace"],
            "model": result["model"],
            "usage": result["usage"],
        }

    async def _sse():
        final_event: Optional[dict] = None
        try:
            async for event in agent.stream(query, session_id=session_id):
                if isinstance(event, dict) and event.get("type") == "final":
                    final_event = event
                yield f"event: {event.get('type', 'message')}\n"
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = {
                "type": "error",
                "error_kind": type(exc).__name__,
                "message": str(exc),
            }
            yield f"event: error\n"
            yield f"data: {json.dumps(err, ensure_ascii=False, default=str)}\n\n"
        finally:
            # Record metrics once the stream terminates. The synthetic ``final``
            # event carries the same model/usage payload as the non-stream result.
            if isinstance(final_event, dict):
                synthetic = dict(final_event.get("data") or {})
                synthetic.setdefault(
                    "session_id", final_event.get("task_id") or session_id
                )
                await _record_package_search_metrics(synthetic, current_user)

    return StreamingResponse(_sse(), media_type="text/event-stream")
