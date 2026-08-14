"""Confirmed-plan-only in-process MCP for deterministic whole-package builds.

The tool intentionally accepts no source paths, project overrides, component
mappings, or output directory from the model.  Every value is loaded from the
Configuration Manager workspace, verified against the server HMAC token and
the staged input manifest, then passed to :mod:`full_package_service`.

Repository publication is outside this module.  The returned artifact remains
under ``<workspace>/output`` for the chat service's deterministic publisher or
fallback path to consume.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from app.services.full_package_service import (
    DEFAULT_CATALOG_PATH,
    BuildResult,
    PlanValidationError,
    build_full_package,
    load_catalog,
    sha256_file,
    validate_confirmed_plan,
)
from app.services.package_confirmation_service import verify_confirmed_plan


SERVER_NAME = "package_builder"
TOOL_NAME = "BuildConfirmedFullPackage"
SDK_TOOL_NAME = f"mcp__{SERVER_NAME}__{TOOL_NAME}"


class PackageBuilderContextError(PlanValidationError):
    """The workspace does not contain a complete signed build authority."""


def _workspace_paths(ctx: Any) -> tuple[Path, Path]:
    if isinstance(ctx, (str, os.PathLike)):
        candidate = Path(ctx).expanduser().resolve()
        if candidate.name == "task.json":
            return candidate.parent, candidate
        return candidate, candidate / "task.json"
    task_value = getattr(ctx, "task_json_path", None)
    workspace_value = getattr(ctx, "temp_dir", None)
    if task_value:
        task_path = Path(str(task_value)).expanduser().resolve()
        workspace = (
            Path(str(workspace_value)).expanduser().resolve()
            if workspace_value
            else task_path.parent
        )
        return workspace, task_path
    raise PackageBuilderContextError("package builder has no workspace context")


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackageBuilderContextError(f"cannot read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PackageBuilderContextError(f"{label} is not valid JSON: {exc}") from exc


def _resolve_workspace_path(workspace: Path, raw_path: Any, label: str) -> Path:
    if not raw_path:
        raise PackageBuilderContextError(f"{label} path is missing")
    path = Path(str(raw_path))
    path = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    root = workspace.resolve()
    if path != root and root not in path.parents:
        raise PackageBuilderContextError(f"{label} escapes the package workspace")
    return path


def _load_embedded_or_path(
    value: Any,
    *,
    workspace: Path,
    label: str,
) -> Any:
    if isinstance(value, Mapping) or isinstance(value, list):
        return copy.deepcopy(value)
    if isinstance(value, str) and value.strip():
        return _read_json(_resolve_workspace_path(workspace, value, label), label)
    raise PackageBuilderContextError(f"task.json is missing {label}")


def _find_confirmed_plan(task: Mapping[str, Any], workspace: Path) -> dict[str, Any]:
    value = task.get("confirmed_plan")
    if value is None:
        value = task.get("confirmed_plan_path")
    package_plan = task.get("package_plan")
    if value is None and isinstance(package_plan, Mapping):
        value = package_plan.get("confirmed") or package_plan.get("confirmed_plan")
        if value is None:
            value = package_plan.get("confirmed_path")
    loaded = _load_embedded_or_path(value, workspace=workspace, label="confirmed plan")
    if not isinstance(loaded, Mapping):
        raise PackageBuilderContextError("confirmed plan must be a JSON object")
    return copy.deepcopy(dict(loaded))


def _catalog_source(task: Mapping[str, Any], workspace: Path) -> Any:
    for key in ("package_catalog", "catalog", "package_catalog_path", "catalog_path"):
        value = task.get(key)
        if isinstance(value, Mapping):
            return copy.deepcopy(value)
        if isinstance(value, str) and value.strip():
            return _resolve_workspace_path(workspace, value, "package catalog")

    # Skills are materialised into .claude/skills.  Prefer the active override
    # for this run and use the source-tree built-in only when no override exists.
    materialised_candidates = (
        workspace / ".claude" / "skills" / "full-package-build" / "references" / "package-projects.json",
        workspace / "skills" / "full-package-build" / "references" / "package-projects.json",
    )
    for candidate in materialised_candidates:
        if candidate.is_file():
            return candidate
    return DEFAULT_CATALOG_PATH


def _manifest_entries(task: Mapping[str, Any], workspace: Path) -> list[dict[str, Any]]:
    value = task.get("inputs_manifest")
    if value is None:
        value = task.get("package_inputs_manifest")
    if value is None:
        value = task.get("inputs_manifest_path") or task.get("package_inputs_manifest_path")
    manifest = _load_embedded_or_path(value, workspace=workspace, label="input manifest")
    if isinstance(manifest, Mapping):
        entries = manifest.get("inputs")
        if entries is None:
            entries = manifest.get("files")
        if entries is None:
            entries = manifest.get("attachments")
    else:
        entries = manifest
    if not isinstance(entries, list) or not entries:
        raise PackageBuilderContextError("input manifest contains no files")
    normalised: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise PackageBuilderContextError(f"input manifest entry {index + 1} is invalid")
        entry = copy.deepcopy(dict(raw))
        raw_path = entry.get("path") or entry.get("stored_path") or entry.get("file_path")
        path = _resolve_workspace_path(workspace, raw_path, f"input {index + 1}")
        if not path.is_file() or path.is_symlink():
            raise PackageBuilderContextError(f"staged input is missing or unsafe: {path}")
        entry["path"] = str(path)
        normalised.append(entry)
    return normalised


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _cached_result(output_dir: Path, confirmation_hash: str) -> Optional[BuildResult]:
    result_path = output_dir / "build-result.json"
    if not result_path.is_file():
        return None
    payload = _read_json(result_path, "build result")
    if not isinstance(payload, Mapping) or payload.get("confirmation_hash") != confirmation_hash:
        return None
    artifact_path = Path(str(payload.get("artifact_path") or "")).resolve()
    root = output_dir.resolve()
    if root not in artifact_path.parents or not artifact_path.is_file():
        return None
    if artifact_path.stat().st_size != int(payload.get("size") or -1):
        return None
    if sha256_file(artifact_path) != payload.get("sha256"):
        return None
    return BuildResult(copy.deepcopy(dict(payload)))


def build_confirmed_full_package(
    ctx: Any,
    *,
    expected_run_id: Optional[str] = None,
    expected_session_id: Optional[str] = None,
    expected_user_id: Optional[str] = None,
) -> BuildResult:
    """Synchronous, idempotent helper used by both MCP and chat fallback.

    The HMAC verification is deliberately the first trust operation after the
    plan is loaded.  No catalog, archive, or output file is touched before the
    plan's server signature and expected run/session/user scope pass.
    """

    workspace, task_path = _workspace_paths(ctx)
    task = _read_json(task_path, "task.json")
    if not isinstance(task, Mapping):
        raise PackageBuilderContextError("task.json must be an object")
    plan = _find_confirmed_plan(task, workspace)

    run_id = expected_run_id if expected_run_id is not None else task.get("run_id")
    session_id = (
        expected_session_id if expected_session_id is not None else task.get("session_id")
    )
    user_id = expected_user_id if expected_user_id is not None else task.get("user_id")
    verify_confirmed_plan(
        plan,
        expected_run_id=str(run_id) if run_id is not None else None,
        expected_session_id=str(session_id) if session_id is not None else None,
        expected_user_id=str(user_id) if user_id is not None else None,
    )

    catalog = load_catalog(_catalog_source(task, workspace))
    manifest = _manifest_entries(task, workspace)
    # This second layer binds the HMAC-authorised plan to the exact catalog and
    # current bytes on disk.  A signed but stale manifest is still rejected.
    validated = validate_confirmed_plan(
        plan,
        catalog,
        inputs=manifest,
        session_id=str(session_id) if session_id is not None else None,
        user_id=str(user_id) if user_id is not None else None,
        verify_files=True,
    )
    output_dir = workspace / "output"
    cached = _cached_result(output_dir, str(validated["confirmation_hash"]))
    if cached is not None:
        return cached

    result = build_full_package(
        validated,
        workspace_dir=workspace,
        output_dir=output_dir,
        catalog=catalog,
    )
    authoritative_path = output_dir / "build-result.json"
    _write_json_atomic(authoritative_path, result.to_dict())

    # Keep task.json as a small pointer only; the result file remains the
    # authority and can be reopened by the deterministic fallback/publisher.
    updated_task = copy.deepcopy(dict(task))
    updated_task["build_result_path"] = authoritative_path.relative_to(workspace).as_posix()
    _write_json_atomic(task_path, updated_task)
    return result


def _tool_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "artifact_path": result.get("artifact_path"),
        "artifact_name": result.get("artifact_name"),
        "sha256": result.get("sha256"),
        "size": result.get("size"),
        "project_code": result.get("project_code"),
        "version": result.get("version"),
        "confirmation_hash": result.get("confirmation_hash"),
        "components": [
            {
                "component_key": component.get("component_key"),
                "file_attr": component.get("file_attr"),
                "version": component.get("version"),
                "output_name": component.get("output_name"),
                "sha256": component.get("sha256"),
            }
            for component in result.get("components", [])
        ],
    }


def get_mcp_server(
    ctx: Any,
    *,
    expected_run_id: Optional[str] = None,
    expected_session_id: Optional[str] = None,
    expected_user_id: Optional[str] = None,
) -> Any:
    """Create the run-bound in-process MCP exposing one argument-free tool."""

    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError("claude-agent-sdk is required for package_builder MCP") from exc

    @tool(
        TOOL_NAME,
        "Build the already human-confirmed whole package from this run's signed "
        "workspace plan. Accepts no paths or mapping overrides. Rejects missing, "
        "expired, stale, or changed confirmation state.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    async def _build(_args: Any) -> dict[str, Any]:
        try:
            result = build_confirmed_full_package(
                ctx,
                expected_run_id=expected_run_id,
                expected_session_id=expected_session_id,
                expected_user_id=expected_user_id,
            )
            payload: Any = _tool_payload(result)
        except Exception as exc:  # MCP returns a structured refusal to the model
            payload = {
                "status": "rejected",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ]
        }

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[_build],
    )


build_package_builder_mcp_server = get_mcp_server
run_confirmed_build = build_confirmed_full_package


__all__ = [
    "PackageBuilderContextError",
    "SDK_TOOL_NAME",
    "SERVER_NAME",
    "TOOL_NAME",
    "build_confirmed_full_package",
    "build_package_builder_mcp_server",
    "get_mcp_server",
    "run_confirmed_build",
]
