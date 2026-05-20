"""Tests for RavenPackageService Agent-search query API.

Covers compare_versions (incl. SemVer 1.10 vs 1.9, prerelease), limit
clamping at max_limit, missing IDs, and empty-text queries.
"""

from __future__ import annotations

import pytest

from app.services.raven_package_service import RavenPackageService


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


def _pkg(pid: str, name: str, version: str, ptype: str = "lingxi-10", *,
         is_patch: bool = False, components=None, tags=None, created: str = "2025-01-01T00:00:00Z"):
    return {
        "id": pid,
        "name": name,
        "version": version,
        "packageType": ptype,
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


def _seed(service, packages):
    service.save_packages(packages)
    # Bypass file-existence pruning by patching get_all_packages-relevant check:
    # the file at the path doesn't exist, so monkeypatch package_file -> exists()
    service.get_all_packages = lambda prune_missing=False: service.load_packages()  # type: ignore[assignment]


def test_compare_versions_semver_boundary():
    assert RavenPackageService.compare_versions("1.10.0", "1.9.0") == 1
    assert RavenPackageService.compare_versions("1.9.0", "1.10.0") == -1
    assert RavenPackageService.compare_versions("2.10.0", "2.10.0") == 0


def test_compare_versions_unparseable_falls_back_to_string():
    # "abc" / "abd" are not valid versions → string comparison
    assert RavenPackageService.compare_versions("abc", "abd") == -1


def test_version_filter_excludes_prerelease_by_default(service):
    _seed(service, [
        _pkg("a", "lx10-2.10.0", "2.10.0"),
        _pkg("b", "lx10-2.9.9", "2.9.9"),
        _pkg("c", "lx10-3.0-rc1", "3.0.0rc1"),
    ])
    items, total = service.version_filter(package_type="lingxi-10", version_min="2.10.0")
    ids = [i["id"] for i in items]
    assert "a" in ids
    assert "b" not in ids
    assert "c" not in ids  # rc1 is a prerelease, filtered
    assert total == 1


def test_version_filter_include_prerelease(service):
    _seed(service, [
        _pkg("a", "lx10-2.10.0", "2.10.0"),
        _pkg("c", "lx10-3.0-rc1", "3.0.0rc1"),
    ])
    items, _ = service.version_filter(
        package_type="lingxi-10", version_min="2.10.0", include_prerelease=True
    )
    assert {i["id"] for i in items} == {"a", "c"}


def test_query_packages_clamps_limit_to_max(service):
    seeded = [_pkg(f"p{i}", f"pkg-{i}", "1.0.0") for i in range(20)]
    _seed(service, seeded)
    items, total = service.query_packages(limit=999)
    assert total == 20
    assert len(items) == 10  # max_limit


def test_text_search_empty_query_returns_empty(service):
    _seed(service, [_pkg("a", "katx-1.0.0", "1.0.0")])
    items, total = service.text_search("   ")
    assert items == []
    assert total == 0


def test_text_search_matches_name_substring(service):
    _seed(service, [
        _pkg("a", "katx-1.0.0", "1.0.0"),
        _pkg("b", "karx-1.0.0", "1.0.0"),
    ])
    items, total = service.text_search("katx", fields=["name"])
    assert total == 1
    assert items[0]["id"] == "a"
    assert "name" in items[0]["matched_fields"]


def test_iter_brief_excludes_sha256_and_path(service):
    pkg = _pkg("a", "katx-1.0.0", "1.0.0", components=["cucp"], tags=["beta"])
    brief = service.iter_brief([pkg])[0]
    assert brief["components"] == ["cucp"]
    assert brief["tags"] == ["beta"]
    assert "sha256" not in brief
    assert "path" not in brief


def test_get_package_nonexistent_returns_none(service):
    _seed(service, [_pkg("a", "x", "1.0.0")])
    assert service.get_package("does-not-exist") is None


def test_stats_by_type(service):
    _seed(service, [
        _pkg("a", "x1", "1.0.0", ptype="lingxi-10"),
        _pkg("b", "x2", "1.0.0", ptype="lingxi-10"),
        _pkg("c", "x3", "1.0.0", ptype="ka-tx"),
    ])
    stats = service.stats_by("type")
    by = {s["key"]: s["count"] for s in stats}
    assert by == {"lingxi-10": 2, "ka-tx": 1}


def test_stats_by_invalid_group(service):
    with pytest.raises(ValueError):
        service.stats_by("bogus")


def test_find_by_component_matches(service):
    _seed(service, [
        _pkg("a", "x1", "1.0.0", components=["cucp", "du"]),
        _pkg("b", "x2", "1.0.0", components=["cuup"]),
    ])
    items, total = service.find_by_component("cucp")
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
