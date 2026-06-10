"""In-process MCP server for the Package Search Agent.

Registers the 7 tools called out in the design doc against the
``RavenPackageService`` singleton. Each tool performs structured queries
against the package metadata file; **no vector search, no file reads,
no external service calls**.

The server is built per run via :func:`get_mcp_server` so every tool
closure captures the session's ``project_code`` and enforces the project
scope server-side — a model cannot query packages outside the selected
project regardless of what arguments it passes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _text_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}


def _service():
    """Return the shared RavenPackageService instance.

    Imported lazily to avoid pulling FastAPI / heavy deps at module load
    when these helpers are exercised in unit tests.
    """
    from app.services.raven_package_service import raven_package_service

    return raven_package_service


def get_mcp_server(project_code: Optional[str] = None):
    """Build the package_search in-process MCP server bound to one project.

    ``project_code`` scopes every tool to the selected project; the filter is
    applied server-side inside each tool closure. ``None`` (unscoped) exists
    only as a migration crutch for the legacy agent loop and is removed once
    the rebuilt agent always supplies the session's project.
    """
    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError as exc:  # pragma: no cover - sdk is a hard dep
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    @tool(
        "list_packages",
        "List packages of the selected project with optional structured "
        "filters and sorting. Returns PackageBrief items (no sha256/path). "
        "Use this when the user asks for packages by tag / component / patch "
        "flag, or wants to browse the catalog. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "is_patch": {"type": "boolean"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "component": {"type": "string"},
                    },
                },
                "sort": {
                    "type": "object",
                    "properties": {
                        "by": {"type": "string", "enum": ["createdAt", "version", "name"]},
                        "order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                },
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
        },
    )
    async def _list_packages(args):
        return _text_result(_call_list_packages(args, project_code=project_code))

    @tool(
        "get_package_by_id",
        "Fetch the full metadata for a single package of the selected project "
        "by ID. Returns the complete record (including sha256, components, "
        "description). If the ID does not exist in this project returns "
        "{error: 'not_found', id}.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )
    async def _get_package_by_id(args):
        return _text_result(_call_get_package_by_id(args, project_code=project_code))

    @tool(
        "search_packages_by_text",
        "Literal substring search over chosen package fields (NOT embedding). "
        "fields ⊆ {name, version, description, tags, components}; defaults to all. "
        "Each returned item includes a matched_fields list. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["name", "version", "description", "tags", "components"],
                    },
                },
                "limit": {"type": "integer"},
            },
            "required": ["text"],
        },
    )
    async def _search_packages_by_text(args):
        return _text_result(_call_search_packages_by_text(args, project_code=project_code))

    @tool(
        "filter_packages_by_version",
        "SemVer-aware version range filter. min/max are inclusive. "
        "include_prerelease defaults to false so 'rc1' / 'beta' are skipped. "
        "Results sorted version desc. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "version_min": {"type": "string"},
                "version_max": {"type": "string"},
                "include_prerelease": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        },
    )
    async def _filter_packages_by_version(args):
        return _text_result(_call_filter_packages_by_version(args, project_code=project_code))

    @tool(
        "list_components",
        "List distinct components across the selected project's packages with "
        "per-component usage counts. Use this when you need to discover the "
        "canonical component names before querying find_packages_by_component.",
        {
            "type": "object",
            "properties": {},
        },
    )
    async def _list_components(args):
        return _text_result(_call_list_components(args, project_code=project_code))

    @tool(
        "find_packages_by_component",
        "Find packages whose components include the given name (and optional version). "
        "Returns PackageBrief items. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "component_name": {"type": "string"},
                "version": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["component_name"],
        },
    )
    async def _find_packages_by_component(args):
        return _text_result(_call_find_packages_by_component(args, project_code=project_code))

    @tool(
        "package_stats",
        "Aggregate counts of the selected project's packages grouped by one "
        "of: version_major, tag, isPatch. Returns groups sorted by count desc.",
        {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["version_major", "tag", "isPatch"],
                },
            },
            "required": ["group_by"],
        },
    )
    async def _package_stats(args):
        return _text_result(_call_package_stats(args, project_code=project_code))

    return create_sdk_mcp_server(
        name="package_search",
        version="2.0.0",
        tools=[
            _list_packages,
            _get_package_by_id,
            _search_packages_by_text,
            _filter_packages_by_version,
            _list_components,
            _find_packages_by_component,
            _package_stats,
        ],
    )


# ──────────── Internal pure-Python helpers used in unit tests ────────────
#
# The @tool-decorated coroutines above are MCP wrappers — invoking them
# requires an MCP runtime. For unit-testing the *logic* (input validation,
# limit clamping, semantic version comparison, project scoping, not_found
# branches) it is more straightforward to call the underlying service
# methods directly. These helpers expose that same pure-Python surface area
# so callers can verify behaviour without standing up the MCP loop.


def _call_list_packages(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    items, total = _service().query_packages(
        filters=args.get("filters") or {},
        sort=args.get("sort") or {},
        limit=args.get("limit"),
        offset=int(args.get("offset") or 0),
        project_code=project_code,
    )
    return {"total": total, "items": items}


def _call_get_package_by_id(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    pkg_id = str(args.get("id") or "").strip()
    if not pkg_id:
        return {"error": "invalid_input", "message": "id is required"}
    pkg = _service().get_package(pkg_id)
    if pkg is None or (project_code is not None and pkg.get("projectCode") != project_code):
        # Cross-project IDs are indistinguishable from missing ones on purpose.
        return {"error": "not_found", "id": pkg_id}
    return pkg


def _call_search_packages_by_text(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    items, total = _service().text_search(
        text=str(args.get("text") or ""),
        fields=args.get("fields"),
        limit=args.get("limit"),
        project_code=project_code,
    )
    return {"total": total, "items": items}


def _call_filter_packages_by_version(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    items, total = _service().version_filter(
        version_min=args.get("version_min"),
        version_max=args.get("version_max"),
        include_prerelease=bool(args.get("include_prerelease") or False),
        limit=args.get("limit"),
        project_code=project_code,
    )
    return {"total": total, "items": items}


def _call_list_components(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    components = _service().list_components(project_code=project_code)
    return {"components": components}


def _call_find_packages_by_component(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    items, total = _service().find_by_component(
        component_name=str(args.get("component_name") or ""),
        version=args.get("version"),
        limit=args.get("limit"),
        project_code=project_code,
    )
    return {"total": total, "items": items}


def _call_package_stats(args: dict[str, Any], project_code: Optional[str] = None) -> dict[str, Any]:
    group_by = str(args.get("group_by") or "")
    try:
        groups = _service().stats_by(group_by, project_code=project_code)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}
    return {"groups": groups}


TOOL_CALLS = {
    "list_packages": _call_list_packages,
    "get_package_by_id": _call_get_package_by_id,
    "search_packages_by_text": _call_search_packages_by_text,
    "filter_packages_by_version": _call_filter_packages_by_version,
    "list_components": _call_list_components,
    "find_packages_by_component": _call_find_packages_by_component,
    "package_stats": _call_package_stats,
}


def text_result(payload: Any) -> dict[str, Any]:
    """Public alias for the MCP-style ``{content: [{type: text, text: ...}]}`` envelope."""
    return _text_result(payload)
