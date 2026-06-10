"""Tests for RavenPackageService Agent-search query API and project model.

Covers compare_versions (incl. SemVer 1.10 vs 1.9, prerelease), limit
clamping at max_limit, missing IDs, empty-text queries, the lazy
packageType→projectCode migration, and project-scoped filtering.
"""

from __future__ import annotations

import json

import pytest

from app.services.raven_package_service import (
    UNASSOCIATED_PROJECT,
    RavenPackageService,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    """Service instance with isolated data dir so tests don't touch real packages."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "raven_data_dir", str(tmp_path / "raven"))
    monkeypatch.setattr(app_settings, "raven_metadata_file", str(tmp_path / "raven" / "package-metadata.json"))
    monkeypatch.setattr(app_settings, "upload_dir", str(tmp_path / "raven" / "uploads"))
    monkeypatch.setattr(app_settings, "package_search_default_limit", 5)
    monkeypatch.setattr(app_settings, "package_search_max_limit", 10)
    return RavenPackageService()


def _pkg(pid: str, name: str, version: str, project: str = "demo-proj", *,
         is_patch: bool = False, components=None, tags=None, created: str = "2025-01-01T00:00:00Z"):
    return {
        "id": pid,
        "name": name,
        "version": version,
        "projectCode": project,
        "path": f"/tmp/{name}",
        "size": 1024,
        "createdAt": created,
        "metadata": {
            "isPatch": is_patch,
            "components": [{"name": c, "version": version} for c in (components or [])],
            "tags": tags or [],
            "description": "",
            "sha256": "deadbeef",
            "customFields": {},
        },
    }


def _legacy_pkg(pid: str, name: str, version: str, ptype: str):
    """A pre-migration record: has packageType, no projectCode."""
    pkg = _pkg(pid, name, version)
    del pkg["projectCode"]
    pkg["packageType"] = ptype
    return pkg


def _seed(service, packages):
    service.save_packages(packages)
    # Bypass file-existence pruning by patching get_all_packages-relevant check:
    # the file at the path doesn't exist, so monkeypatch package_file -> exists()
    service.get_all_packages = lambda prune_missing=False: service.load_packages()  # type: ignore[assignment]


# ────────────────────── lazy migration ──────────────────────


def test_legacy_record_gains_project_code_on_read(service):
    _seed(service, [_legacy_pkg("a", "lx10-1.0.tgz", "1.0.0", "lingxi-10")])
    pkg = service.load_packages()[0]
    assert pkg["projectCode"] == "lingxi-10"
    # rollback compatibility: the original key is preserved
    assert pkg["packageType"] == "lingxi-10"


def test_lazy_migration_is_idempotent(service):
    _seed(service, [_legacy_pkg("a", "lx10-1.0.tgz", "1.0.0", "lingxi-10")])
    first = service.load_packages()
    service.save_packages(first)
    second = service.load_packages()
    assert second[0]["projectCode"] == "lingxi-10"
    assert second[0]["packageType"] == "lingxi-10"
    assert first == second


def test_read_path_does_not_write_metadata_file(service, tmp_path):
    _seed(service, [_legacy_pkg("a", "lx10-1.0.tgz", "1.0.0", "lingxi-10")])
    raw_before = service.metadata_file.read_text(encoding="utf-8")
    service.load_packages()
    assert service.metadata_file.read_text(encoding="utf-8") == raw_before
    # the on-disk record stays in legacy form until the next regular write
    assert "projectCode" not in json.loads(raw_before)[0]


def test_legacy_record_without_package_type_becomes_unassociated(service):
    pkg = _pkg("a", "x.tgz", "1.0.0")
    del pkg["projectCode"]
    _seed(service, [pkg])
    assert service.load_packages()[0]["projectCode"] == ""


# ────────────────────── filter_packages (project dimension) ──────────────────────


def test_filter_packages_by_project_code(service):
    _seed(service, [
        _pkg("a", "x1.tgz", "1.0.0", "demo-proj"),
        _pkg("b", "x2.tgz", "1.0.0", "other-proj"),
        _pkg("c", "x3.tgz", "1.0.0", ""),
    ])
    items, pagination = service.filter_packages({"projectCode": "demo-proj"})
    assert [p["id"] for p in items] == ["a"]
    assert pagination["totalItems"] == 1


def test_filter_packages_unassociated_special_value(service):
    _seed(service, [
        _pkg("a", "x1.tgz", "1.0.0", "demo-proj"),
        _pkg("b", "x2.tgz", "1.0.0", ""),
    ])
    items, _ = service.filter_packages({"projectCode": UNASSOCIATED_PROJECT})
    assert [p["id"] for p in items] == ["b"]


# ────────────────────── version compare ──────────────────────


def test_compare_versions_semver_boundary():
    assert RavenPackageService.compare_versions("1.10.0", "1.9.0") == 1
    assert RavenPackageService.compare_versions("1.9.0", "1.10.0") == -1
    assert RavenPackageService.compare_versions("2.10.0", "2.10.0") == 0


def test_compare_versions_unparseable_falls_back_to_string():
    # "abc" / "abd" are not valid versions → string comparison
    assert RavenPackageService.compare_versions("abc", "abd") == -1


# ────────────────────── query methods (project scoping) ──────────────────────


def test_version_filter_excludes_prerelease_by_default(service):
    _seed(service, [
        _pkg("a", "lx10-2.10.0", "2.10.0", "lingxi-10"),
        _pkg("b", "lx10-2.9.9", "2.9.9", "lingxi-10"),
        _pkg("c", "lx10-3.0-rc1", "3.0.0rc1", "lingxi-10"),
    ])
    items, total = service.version_filter(project_code="lingxi-10", version_min="2.10.0")
    ids = [i["id"] for i in items]
    assert "a" in ids
    assert "b" not in ids
    assert "c" not in ids  # rc1 is a prerelease, filtered
    assert total == 1


def test_version_filter_include_prerelease(service):
    _seed(service, [
        _pkg("a", "lx10-2.10.0", "2.10.0", "lingxi-10"),
        _pkg("c", "lx10-3.0-rc1", "3.0.0rc1", "lingxi-10"),
    ])
    items, _ = service.version_filter(
        project_code="lingxi-10", version_min="2.10.0", include_prerelease=True
    )
    assert {i["id"] for i in items} == {"a", "c"}


def test_query_packages_clamps_limit_to_max(service):
    seeded = [_pkg(f"p{i}", f"pkg-{i}", "1.0.0") for i in range(20)]
    _seed(service, seeded)
    items, total = service.query_packages(limit=999)
    assert total == 20
    assert len(items) == 10  # max_limit


def test_query_packages_scoped_to_project(service):
    _seed(service, [
        _pkg("a", "x1.tgz", "1.0.0", "demo-proj"),
        _pkg("b", "x2.tgz", "1.0.0", "other-proj"),
    ])
    items, total = service.query_packages(project_code="demo-proj")
    assert total == 1
    assert items[0]["id"] == "a"


def test_text_search_empty_query_returns_empty(service):
    _seed(service, [_pkg("a", "katx-1.0.0", "1.0.0")])
    items, total = service.text_search("   ")
    assert items == []
    assert total == 0


def test_text_search_matches_name_substring_within_project(service):
    _seed(service, [
        _pkg("a", "katx-1.0.0", "1.0.0", "ka-tx"),
        _pkg("b", "katx-2.0.0", "2.0.0", "other-proj"),
    ])
    items, total = service.text_search("katx", fields=["name"], project_code="ka-tx")
    assert total == 1
    assert items[0]["id"] == "a"
    assert "name" in items[0]["matched_fields"]


def test_iter_brief_projects_project_code_and_excludes_sha256_and_path(service):
    pkg = _pkg("a", "katx-1.0.0", "1.0.0", "ka-tx", components=["cucp"], tags=["beta"])
    brief = service.iter_brief([pkg])[0]
    assert brief["projectCode"] == "ka-tx"
    assert brief["components"] == ["cucp"]
    assert brief["tags"] == ["beta"]
    assert "packageType" not in brief
    assert "sha256" not in brief
    assert "path" not in brief


def test_get_package_nonexistent_returns_none(service):
    _seed(service, [_pkg("a", "x", "1.0.0")])
    assert service.get_package("does-not-exist") is None


def test_stats_by_type_dimension_removed(service):
    _seed(service, [_pkg("a", "x1", "1.0.0")])
    with pytest.raises(ValueError):
        service.stats_by("type")


def test_stats_by_is_patch_scoped_to_project(service):
    _seed(service, [
        _pkg("a", "x1", "1.0.0", "demo-proj", is_patch=True),
        _pkg("b", "x2", "1.0.0", "demo-proj"),
        _pkg("c", "x3", "1.0.0", "other-proj", is_patch=True),
    ])
    stats = service.stats_by("isPatch", project_code="demo-proj")
    by = {s["key"]: s["count"] for s in stats}
    assert by == {"patch": 1, "full": 1}


def test_stats_by_invalid_group(service):
    with pytest.raises(ValueError):
        service.stats_by("bogus")


def test_find_by_component_matches_within_project(service):
    _seed(service, [
        _pkg("a", "x1", "1.0.0", "demo-proj", components=["cucp", "du"]),
        _pkg("b", "x2", "1.0.0", "demo-proj", components=["cuup"]),
        _pkg("c", "x3", "1.0.0", "other-proj", components=["cucp"]),
    ])
    items, total = service.find_by_component("cucp", project_code="demo-proj")
    assert total == 1
    assert items[0]["id"] == "a"


def test_list_components_aggregates_counts(service):
    _seed(service, [
        _pkg("a", "x1", "1.0.0", components=["cucp", "du"]),
        _pkg("b", "x2", "1.0.0", components=["cucp"]),
    ])
    rows = service.list_components()
    by = {r["name"]: r["count"] for r in rows}
    assert by["cucp"] == 2
    assert by["du"] == 1
    by_codes = {r["name"]: r["project_codes"] for r in rows}
    assert by_codes["cucp"] == ["demo-proj"]


# ────────────────────── scan / build (no filename guessing) ──────────────────────


def test_extract_package_metadata_leaves_project_unassociated(service, tmp_path):
    file_path = tmp_path / "lingxi-10-v1.2.3.tgz"
    file_path.write_bytes(b"dummy")
    meta = service.extract_package_metadata(file_path)
    # no filename-based project guessing — scanned files stay unassociated
    assert meta["projectCode"] == ""
    assert "packageType" not in meta


def test_scan_uploads_directory_registers_unassociated(service):
    service.uploads_dir.mkdir(parents=True, exist_ok=True)
    (service.uploads_dir / "katx-9.9.9.tgz").write_bytes(b"dummy")
    added = service.scan_uploads_directory()
    assert added == 1
    pkg = service.load_packages()[0]
    assert pkg["projectCode"] == ""


def test_build_package_info_uses_explicit_project_code(service, tmp_path):
    file_path = tmp_path / "demo-1.0.0.tgz"
    file_path.write_bytes(b"dummy")
    info = service.build_package_info(
        file_path, 5, "cafe", metadata_fields={"projectCode": "demo-proj"}
    )
    assert info["projectCode"] == "demo-proj"
