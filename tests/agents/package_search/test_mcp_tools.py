"""Unit tests for the Package Search Agent MCP tool wrappers.

We exercise the pure-Python ``TOOL_CALLS`` dispatch table rather than the
MCP runtime: each tool call goes through the same service-layer path the
``@tool``-decorated coroutine takes, so behavioural invariants — input
validation, limit clamping, SemVer comparison, server-side project scoping,
not_found branches — are verified here without needing a live MCP server.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.package_search.mcp_tools import TOOL_CALLS
from app.services.raven_package_service import RavenPackageService


@pytest.fixture
def service(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "raven_data_dir", str(tmp_path / "raven"))
    monkeypatch.setattr(
        app_settings,
        "raven_metadata_file",
        str(tmp_path / "raven" / "package-metadata.json"),
    )
    monkeypatch.setattr(app_settings, "upload_dir", str(tmp_path / "raven" / "uploads"))
    monkeypatch.setattr(app_settings, "package_search_default_limit", 5)
    monkeypatch.setattr(app_settings, "package_search_max_limit", 10)

    svc = RavenPackageService()
    # Bypass file-existence pruning during tests (we don't actually place
    # .tgz files on disk for every seeded package).
    svc.get_all_packages = lambda prune_missing=False: svc.load_packages()  # type: ignore[assignment]

    # Make the singleton used by mcp_tools point at this isolated service.
    import app.agents.package_search.mcp_tools as mod

    monkeypatch.setattr(mod, "_service", lambda: svc)
    return svc


def _pkg(pid: str, name: str, version: str, project: str = "demo-proj", **meta: Any) -> dict:
    return {
        "id": pid,
        "name": name,
        "version": version,
        "projectCode": project,
        "path": f"/tmp/{name}",
        "size": 1024,
        "createdAt": meta.pop("createdAt", "2025-01-01T00:00:00Z"),
        "metadata": {
            "isPatch": meta.pop("is_patch", False),
            "components": [
                {"name": c, "version": version} for c in meta.pop("components", [])
            ],
            "tags": meta.pop("tags", []),
            "description": meta.pop("description", ""),
            "sha256": "deadbeef",
            "customFields": {},
        },
    }


def _seed(service: RavenPackageService, packages: list[dict]) -> None:
    service.save_packages(packages)


# ────────────────────── list_packages ──────────────────────


def test_list_packages_scoped_to_project(service):
    _seed(service, [
        _pkg("a", "katx-1.0.tgz", "1.0.0", "ka-tx"),
        _pkg("b", "katx-2.0.tgz", "2.0.0", "ka-tx"),
        _pkg("c", "lx10-1.0.tgz", "1.0.0", "lingxi-10"),
    ])
    result = TOOL_CALLS["list_packages"]({}, project_code="ka-tx")
    assert result["total"] == 2
    ids = {item["id"] for item in result["items"]}
    assert ids == {"a", "b"}
    # Brief shape — no sha256, no path, projectCode instead of packageType
    for item in result["items"]:
        assert "sha256" not in item
        assert "path" not in item
        assert {"id", "name", "version", "projectCode", "isPatch",
                "createdAt", "components", "tags", "size"}.issubset(item.keys())


def test_list_packages_clamps_limit_at_max(service):
    """Even if the agent requests limit=999 the service caps at max_limit (10)."""
    _seed(service, [_pkg(f"p{i}", f"pkg-{i}.tgz", f"1.{i}.0") for i in range(20)])
    result = TOOL_CALLS["list_packages"]({"limit": 999}, project_code="demo-proj")
    assert result["total"] == 20  # total reflects pre-paging count
    assert len(result["items"]) == 10  # clamped to package_search_max_limit


# ────────────────────── get_package_by_id ──────────────────────


def test_get_package_by_id_returns_full_record(service):
    _seed(service, [_pkg("p1", "katx.tgz", "1.0.0", "ka-tx", description="hello")])
    result = TOOL_CALLS["get_package_by_id"]({"id": "p1"}, project_code="ka-tx")
    assert result["id"] == "p1"
    # full record includes metadata.sha256
    assert result["metadata"]["sha256"] == "deadbeef"


def test_get_package_by_id_returns_not_found(service):
    _seed(service, [_pkg("p1", "x.tgz", "1.0.0")])
    result = TOOL_CALLS["get_package_by_id"]({"id": "does-not-exist"}, project_code="demo-proj")
    assert result == {"error": "not_found", "id": "does-not-exist"}


def test_get_package_by_id_blocks_cross_project_id(service):
    """A real package ID belonging to another project must look not_found."""
    _seed(service, [_pkg("p1", "x.tgz", "1.0.0", "other-proj")])
    result = TOOL_CALLS["get_package_by_id"]({"id": "p1"}, project_code="demo-proj")
    assert result == {"error": "not_found", "id": "p1"}


def test_get_package_by_id_rejects_empty_id(service):
    _seed(service, [_pkg("p1", "x.tgz", "1.0.0")])
    result = TOOL_CALLS["get_package_by_id"]({"id": ""}, project_code="demo-proj")
    assert result["error"] == "invalid_input"


# ────────────────────── search_packages_by_text ──────────────────────


def test_search_packages_by_text_matches_substring_within_project(service):
    _seed(service, [
        _pkg("a", "katx-lt.tgz", "1.0.0", "ka-tx"),
        _pkg("b", "karx-lt.tgz", "1.0.0", "ka-rx"),
        _pkg("c", "katx-other.tgz", "1.0.0", "ka-rx"),
    ])
    result = TOOL_CALLS["search_packages_by_text"]({"text": "katx"}, project_code="ka-tx")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "a"
    assert "name" in result["items"][0]["matched_fields"]


def test_search_packages_by_text_empty_returns_zero(service):
    _seed(service, [_pkg("a", "x.tgz", "1.0.0")])
    result = TOOL_CALLS["search_packages_by_text"]({"text": "   "}, project_code="demo-proj")
    assert result == {"total": 0, "items": []}


# ────────────────────── filter_packages_by_version ──────────────────────


def test_filter_packages_by_version_uses_semver(service):
    """1.10.0 must rank higher than 1.9.0 (numeric, not lexicographic)."""
    _seed(service, [
        _pkg("a", "lx10-1.9.tgz", "1.9.0", "lingxi-10"),
        _pkg("b", "lx10-1.10.tgz", "1.10.0", "lingxi-10"),
        _pkg("c", "lx10-2.0.tgz", "2.0.0", "lingxi-10"),
    ])
    result = TOOL_CALLS["filter_packages_by_version"](
        {"version_min": "1.10.0"}, project_code="lingxi-10"
    )
    ids = {item["id"] for item in result["items"]}
    assert ids == {"b", "c"}
    assert "a" not in ids


def test_filter_packages_by_version_scoped_to_project(service):
    _seed(service, [
        _pkg("a", "lx10-2.0.tgz", "2.0.0", "lingxi-10"),
        _pkg("b", "katx-2.0.tgz", "2.0.0", "ka-tx"),
    ])
    result = TOOL_CALLS["filter_packages_by_version"](
        {"version_min": "1.0.0"}, project_code="lingxi-10"
    )
    assert {item["id"] for item in result["items"]} == {"a"}


def test_filter_packages_by_version_skips_prerelease_by_default(service):
    _seed(service, [
        _pkg("rc", "lx10-2.0rc1.tgz", "2.0.0rc1", "lingxi-10"),
        _pkg("ga", "lx10-2.0.tgz", "2.0.0", "lingxi-10"),
    ])
    result = TOOL_CALLS["filter_packages_by_version"](
        {"version_min": "1.0.0"}, project_code="lingxi-10"
    )
    ids = {item["id"] for item in result["items"]}
    assert "rc" not in ids
    assert "ga" in ids


def test_filter_packages_by_version_include_prerelease(service):
    _seed(service, [
        _pkg("rc", "lx10-2.0rc1.tgz", "2.0.0rc1", "lingxi-10"),
        _pkg("ga", "lx10-2.0.tgz", "2.0.0", "lingxi-10"),
    ])
    result = TOOL_CALLS["filter_packages_by_version"](
        {"version_min": "1.0.0", "include_prerelease": True},
        project_code="lingxi-10",
    )
    ids = {item["id"] for item in result["items"]}
    assert {"rc", "ga"}.issubset(ids)


# ────────────────────── list_components ──────────────────────


def test_list_components_aggregates_and_counts_within_project(service):
    _seed(service, [
        _pkg("a", "p-a.tgz", "1.0.0", components=["cucp", "cuup"]),
        _pkg("b", "p-b.tgz", "1.0.0", components=["cucp", "du"]),
        _pkg("c", "p-c.tgz", "1.0.0", "other-proj", components=["cucp"]),
    ])
    result = TOOL_CALLS["list_components"]({}, project_code="demo-proj")
    by_name = {row["name"]: row for row in result["components"]}
    assert by_name["cucp"]["count"] == 2
    assert by_name["cuup"]["count"] == 1
    assert by_name["du"]["count"] == 1


# ────────────────────── find_packages_by_component ──────────────────────


def test_find_packages_by_component_returns_briefs(service):
    _seed(service, [
        _pkg("a", "a.tgz", "1.0.0", components=["cucp"]),
        _pkg("b", "b.tgz", "1.0.0", components=["du"]),
        _pkg("c", "c.tgz", "1.0.0", "other-proj", components=["cucp"]),
    ])
    result = TOOL_CALLS["find_packages_by_component"](
        {"component_name": "cucp"}, project_code="demo-proj"
    )
    assert result["total"] == 1
    assert result["items"][0]["id"] == "a"


def test_find_packages_by_component_empty_name(service):
    result = TOOL_CALLS["find_packages_by_component"](
        {"component_name": ""}, project_code="demo-proj"
    )
    assert result == {"total": 0, "items": []}


# ────────────────────── package_stats ──────────────────────


def test_package_stats_group_by_is_patch_within_project(service):
    _seed(service, [
        _pkg("a", "x.tgz", "1.0.0", is_patch=True),
        _pkg("b", "y.tgz", "1.0.0"),
        _pkg("c", "z.tgz", "1.0.0", "other-proj", is_patch=True),
    ])
    result = TOOL_CALLS["package_stats"]({"group_by": "isPatch"}, project_code="demo-proj")
    groups = {row["key"]: row["count"] for row in result["groups"]}
    assert groups == {"patch": 1, "full": 1}


def test_package_stats_type_dimension_removed(service):
    _seed(service, [_pkg("a", "x.tgz", "1.0.0")])
    result = TOOL_CALLS["package_stats"]({"group_by": "type"}, project_code="demo-proj")
    assert result["error"] == "invalid_input"


def test_package_stats_invalid_group_by(service):
    result = TOOL_CALLS["package_stats"]({"group_by": "nonsense"}, project_code="demo-proj")
    assert result["error"] == "invalid_input"
