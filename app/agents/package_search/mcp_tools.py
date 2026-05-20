"""In-process MCP server for the Package Search Agent.

Registers the 7 tools called out in the design doc against the
``RavenPackageService`` singleton. Each tool performs structured queries
against the package metadata file; **no vector search, no file reads,
no external service calls**.

The server is created lazily so the module is cheap to import in tests.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_server = None  # lazily created


def _text_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}


def _service():
    """Return the shared RavenPackageService instance.

    Imported lazily to avoid pulling FastAPI / heavy deps at module load
    when these helpers are exercised in unit tests.
    """
    from app.services.raven_package_service import raven_package_service

    return raven_package_service


def _get_server():
    global _server
    if _server is not None:
        return _server

    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError as exc:  # pragma: no cover - sdk is a hard dep
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    @tool(
        "list_packages",
        "List Raven packages with optional structured filters and sorting. "
        "Returns PackageBrief items (no sha256/path). Use this when the user "
        "asks for packages by type / tag / component / patch flag, or wants "
        "to browse the catalog. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "packageType to filter by"},
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
        items, total = _service().query_packages(
            filters=args.get("filters") or {},
            sort=args.get("sort") or {},
            limit=args.get("limit"),
            offset=int(args.get("offset") or 0),
        )
        return _text_result({"total": total, "items": items})

    @tool(
        "get_package_by_id",
        "Fetch the full metadata for a single Raven package by ID. "
        "Returns the complete record (including sha256, components, description). "
        "If the ID does not exist returns {error: 'not_found', id}.",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    )
    async def _get_package_by_id(args):
        pkg_id = str(args.get("id") or "").strip()
        if not pkg_id:
            return _text_result({"error": "invalid_input", "message": "id is required"})
        pkg = _service().get_package(pkg_id)
        if pkg is None:
            return _text_result({"error": "not_found", "id": pkg_id})
        return _text_result(pkg)

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
        items, total = _service().text_search(
            text=str(args.get("text") or ""),
            fields=args.get("fields"),
            limit=args.get("limit"),
        )
        return _text_result({"total": total, "items": items})

    @tool(
        "filter_packages_by_version",
        "SemVer-aware version range filter. min/max are inclusive. "
        "include_prerelease defaults to false so 'rc1' / 'beta' are skipped. "
        "Results sorted version desc. Default limit=5, max=50.",
        {
            "type": "object",
            "properties": {
                "package_type": {"type": "string"},
                "version_min": {"type": "string"},
                "version_max": {"type": "string"},
                "include_prerelease": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        },
    )
    async def _filter_packages_by_version(args):
        items, total = _service().version_filter(
            package_type=args.get("package_type"),
            version_min=args.get("version_min"),
            version_max=args.get("version_max"),
            include_prerelease=bool(args.get("include_prerelease") or False),
            limit=args.get("limit"),
        )
        return _text_result({"total": total, "items": items})

    @tool(
        "list_components",
        "List distinct components across packages with per-component usage counts. "
        "Use this when you need to discover the canonical component names before "
        "querying find_packages_by_component.",
        {
            "type": "object",
            "properties": {
                "package_type": {"type": "string"},
            },
        },
    )
    async def _list_components(args):
        components = _service().list_components(package_type=args.get("package_type"))
        return _text_result({"components": components})

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
        items, total = _service().find_by_component(
            component_name=str(args.get("component_name") or ""),
            version=args.get("version"),
            limit=args.get("limit"),
        )
        return _text_result({"total": total, "items": items})

    @tool(
        "package_stats",
        "Aggregate counts of packages grouped by one of: type, version_major, tag, isPatch. "
        "Returns groups sorted by count desc.",
        {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["type", "version_major", "tag", "isPatch"],
                },
            },
            "required": ["group_by"],
        },
    )
    async def _package_stats(args):
        group_by = str(args.get("group_by") or "")
        try:
            groups = _service().stats_by(group_by)
        except ValueError as exc:
            return _text_result({"error": "invalid_input", "message": str(exc)})
        return _text_result({"groups": groups})

    _server = create_sdk_mcp_server(
        name="package_search",
        version="1.0.0",
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
    return _server


def get_mcp_server():
    """Return the package_search in-process MCP server (creates on first call)."""
    return _get_server()


# ──────────── Internal pure-Python helpers used in unit tests ────────────
#
# The @tool-decorated coroutines above are MCP wrappers — invoking them
# requires an MCP runtime. For unit-testing the *logic* (input validation,
# limit clamping, semantic version comparison, not_found branches) it is
# more straightforward to call the underlying service methods directly.
# These helpers expose that same pure-Python surface area so callers can
# verify behaviour without standing up the MCP loop.


def _call_list_packages(args: dict[str, Any]) -> dict[str, Any]:
    items, total = _service().query_packages(
        filters=args.get("filters") or {},
        sort=args.get("sort") or {},
        limit=args.get("limit"),
        offset=int(args.get("offset") or 0),
    )
    return {"total": total, "items": items}


def _call_get_package_by_id(args: dict[str, Any]) -> dict[str, Any]:
    pkg_id = str(args.get("id") or "").strip()
    if not pkg_id:
        return {"error": "invalid_input", "message": "id is required"}
    pkg = _service().get_package(pkg_id)
    if pkg is None:
        return {"error": "not_found", "id": pkg_id}
    return pkg


def _call_search_packages_by_text(args: dict[str, Any]) -> dict[str, Any]:
    items, total = _service().text_search(
        text=str(args.get("text") or ""),
        fields=args.get("fields"),
        limit=args.get("limit"),
    )
    return {"total": total, "items": items}


def _call_filter_packages_by_version(args: dict[str, Any]) -> dict[str, Any]:
    items, total = _service().version_filter(
        package_type=args.get("package_type"),
        version_min=args.get("version_min"),
        version_max=args.get("version_max"),
        include_prerelease=bool(args.get("include_prerelease") or False),
        limit=args.get("limit"),
    )
    return {"total": total, "items": items}


def _call_list_components(args: dict[str, Any]) -> dict[str, Any]:
    components = _service().list_components(package_type=args.get("package_type"))
    return {"components": components}


def _call_find_packages_by_component(args: dict[str, Any]) -> dict[str, Any]:
    items, total = _service().find_by_component(
        component_name=str(args.get("component_name") or ""),
        version=args.get("version"),
        limit=args.get("limit"),
    )
    return {"total": total, "items": items}


def _call_package_stats(args: dict[str, Any]) -> dict[str, Any]:
    group_by = str(args.get("group_by") or "")
    try:
        groups = _service().stats_by(group_by)
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
