from __future__ import annotations

import copy
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.services.full_package_service import (
    CatalogValidationError,
    FullPackageError,
    PlanValidationError,
    build_full_package,
    canonical_hash,
    classify_inputs,
    compute_confirmed_plan_hash,
    confirm_plan,
    load_catalog,
    sha256_file,
    validate_confirmed_plan,
)


def _source(path: Path, upload_id: str = "oam") -> dict:
    return {"upload_id": upload_id, "original_name": path.name, "path": str(path),
            "relative_path": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)}


def _patch(path: Path, name: str, *, fields: dict | None = None, extra: str = "", duplicate: str = ""):
    payload = b"verified-oam-payload"
    metadata = {"Packet_Ver": "V1.0.0.2", "PacketAttr": "1002", "Publisher": "yinhe",
                "FileNumInPacket": "1", "FileName_1": name, "FileAttr_1": "301",
                "FileVer_1": "V1.0.0.2"}
    metadata.update(fields or {})
    text = "\n".join(f"{key}={value};" for key, value in metadata.items()) + "\n" + extra
    with tarfile.open(path, "w:gz") as archive:
        for member_name, content in [(name, payload), ("si.ini", text.encode())]:
            info = tarfile.TarInfo(member_name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if duplicate:
            info = tarfile.TarInfo(duplicate)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path, payload


def _confirm(catalog, inputs, project, mappings=None):
    draft = classify_inputs(catalog, inputs, project_hint=project)
    answers = {"project": project, "version": "1.1.0.0", "mode": "full"}
    answers.update(mappings or {"input:oam": "oam"})
    return draft, confirm_plan(draft, answers, session_id="s", user_id="u", catalog=catalog, inputs=inputs)


@pytest.mark.parametrize("project,name", [("lingxi-07a", "gnb-oam-lx07a"), ("lingxi-10", "gnb-oam-lx10")])
def test_oam_patch_and_protocol_produce_flat_source_identical_payloads(tmp_path, project, name):
    source, payload = _patch(tmp_path / f"{name}-Patch.tgz", name)
    protocol = tmp_path / "S-GNB-V1.2.30.12-202609170917.zip"
    with zipfile.ZipFile(protocol, "w") as archive:
        for key in ("cucp", "cuup", "du"):
            archive.writestr(f"gnb_{key}-1.2.30.12-202609170917.arm64.deb", key.encode())
            archive.writestr(f"gnb_{key}-1.2.30.12-202609170917.arm64.deb.md5", b"metadata")
    inputs = [_source(source), _source(protocol, "protocol")]
    catalog = load_catalog()
    draft, plan = _confirm(catalog, inputs, project,
                           {"input:oam": "oam", "input:protocol": ["cucp", "cuup", "du"]})
    oam_candidate = next(c for c in draft["inputs"][0]["candidates"] if c["project_code"] == project)
    assert oam_candidate["publishable"] and oam_candidate["prebuilt_extract"]
    assert oam_candidate["version"] == "V1.0.0.2"
    assert plan["inputs"][0]["component_versions"]["oam"] == "V1.0.0.2"
    result = build_full_package(plan, workspace_dir=tmp_path / "build", catalog=catalog)
    assert {c["file_attr"] for c in result["components"]} == {301, 302, 307, 308}
    assert result["manifest"]["packet_attr"] == 1001
    with tarfile.open(result["artifact_path"], "r:gz") as archive:
        assert set(archive.getnames()) == {name, "cucp.deb", "cuup.deb", "du.deb", "si.ini", "package-manifest.json"}
        assert archive.extractfile(name).read() == payload
        assert archive.extractfile("cucp.deb").read() == b"cucp"
    assert next(c["sha256"] for c in result["components"] if c["component_key"] == "oam") == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("fields,extra", [
    ({"PacketAttr": "2001"}, ""),
    ({"Publisher": "other"}, ""),
    ({"FileNumInPacket": "2"}, ""),
    ({"FileName_1": "gnb-oam-lx10"}, ""),
    ({"FileAttr_1": "302"}, ""),
    ({"FileVer_1": "unknown"}, ""),
    ({"FileSize_1": "999"}, ""),
    ({"FileMD5_1": "0" * 32}, ""),
    ({"FileSHA256_1": "0" * 64}, ""),
    ({"FileCRC32_1": "deadbeef"}, ""),
    ({"FileName_2": "extra"}, ""),
    ({}, "FileAttr_1=301;\n"),
    ({}, "malformed line\n"),
])
def test_invalid_prebuilt_manifest_is_unpublishable_and_cannot_be_confirmed(tmp_path, fields, extra):
    source, _ = _patch(tmp_path / "GalaxySpace-Lx07a-Patch.tgz", "gnb-oam-lx07a", fields=fields, extra=extra)
    catalog = load_catalog()
    inputs = [_source(source)]
    draft = classify_inputs(catalog, inputs, project_hint="lingxi-07a")
    candidates = [c for c in draft["inputs"][0]["candidates"] if c["project_code"] == "lingxi-07a"]
    assert candidates and not any(c["publishable"] for c in candidates)
    assert draft["inputs"][0]["classification_errors"]
    # A crafted manual answer cannot override the failed classification.
    with pytest.raises(FullPackageError):
        _confirm(catalog, inputs, "lingxi-07a")


@pytest.mark.parametrize("duplicate", ["gnb-oam-lx07a", "./gnb-oam-lx07a", "si.ini"])
def test_duplicate_normalized_prebuilt_members_remain_blocked(tmp_path, duplicate):
    source, _ = _patch(tmp_path / "GalaxySpace-Lx07a-Patch.tgz", "gnb-oam-lx07a", duplicate=duplicate)
    with pytest.raises(PlanValidationError, match="duplicate"):
        _confirm(load_catalog(), [_source(source)], "lingxi-07a")


def test_matching_optional_size_and_checksums_are_verified(tmp_path):
    payload = b"verified-oam-payload"
    fields = {"FileSize_1": str(len(payload)), "FileMD5_1": hashlib.md5(payload).hexdigest(),
              "FileSHA256_1": hashlib.sha256(payload).hexdigest()}
    source, _ = _patch(tmp_path / "GalaxySpace-Lx07a-Patch.tgz", "gnb-oam-lx07a", fields=fields)
    _draft, plan = _confirm(load_catalog(), [_source(source)], "lingxi-07a")
    assert validate_confirmed_plan(plan)["status"] == "confirmed"


def test_prebuilt_requires_opt_in_and_source_component_version(tmp_path):
    source, _ = _patch(tmp_path / "GalaxySpace-Lx07a-Patch.tgz", "gnb-oam-lx07a")
    inputs = [_source(source)]
    catalog = load_catalog()
    project = catalog.projects_by_code["lingxi-07a"]
    project["components"][0]["allow_prebuilt_extract"] = False
    catalog = load_catalog(catalog)
    with pytest.raises(PlanValidationError, match="not enabled"):
        _confirm(catalog, inputs, "lingxi-07a")
    catalog = load_catalog()
    draft = classify_inputs(catalog, inputs, project_hint="lingxi-07a")
    with pytest.raises(PlanValidationError, match="version must match"):
        confirm_plan(draft, [
            {"question_key": "project", "value": "lingxi-07a"},
            {"question_key": "version", "value": "1.1.0.0"},
            {"question_key": "mode", "value": "full"},
            {"question_key": "input:oam", "value": {
                "components": ["oam"], "component_versions": {"oam": "V9.0.0.0"}}},
        ], session_id="s", user_id="u", catalog=catalog, inputs=inputs)


def test_build_revalidates_prebuilt_even_if_plan_hashes_are_recomputed(tmp_path):
    source, _ = _patch(tmp_path / "GalaxySpace-Lx07a-Patch.tgz", "gnb-oam-lx07a")
    catalog = load_catalog()
    _draft, plan = _confirm(catalog, [_source(source)], "lingxi-07a")
    plan["inputs"][0]["component_versions"]["oam"] = "V9.0.0.0"
    plan["plan_hash"] = compute_confirmed_plan_hash(plan)
    plan["confirmation_hash"] = canonical_hash({"plan_hash": plan["plan_hash"], "confirmed_at": plan["confirmed_at"]})
    with pytest.raises(PlanValidationError, match="differs from FileVer"):
        build_full_package(plan, catalog=catalog, workspace_dir=tmp_path / "build")
    assert not list((tmp_path / "build").glob("**/*.tgz"))


@pytest.mark.parametrize("value", ["oam_lx07a", ["../escape"], ["oam_lx07a", "oam_lx07a"], ["oam_lx10"], ["lingxi-10"]])
def test_registry_mapping_is_explicit_and_unambiguous(value):
    catalog = load_catalog().to_dict()
    catalog["projects"][1]["registry_project_codes"] = value
    with pytest.raises(CatalogValidationError):
        load_catalog(catalog)


def test_registry_mapping_survives_catalog_normalization():
    catalog = load_catalog()
    assert catalog.projects_by_code["lingxi-07a"]["registry_project_codes"] == ["oam_lx07a"]
    assert catalog.projects_by_code["lingxi-10"]["registry_project_codes"] == ["oam_lx10"]
    assert load_catalog(catalog).digest == catalog.digest


def test_si_ini_forces_prebuilt_validation_without_recognition_rules(tmp_path):
    source, _ = _patch(tmp_path / "gnb-oam-lx07a.tgz", "gnb-oam-lx07a")
    payload = load_catalog().to_dict()
    payload["projects"][1]["prebuilt_recognition"] = []
    catalog = load_catalog(payload)
    draft, plan = _confirm(catalog, [_source(source)], "lingxi-07a")
    assert draft["inputs"][0]["prebuilt"] is True
    candidate = next(c for c in draft["inputs"][0]["candidates"] if c["project_code"] == "lingxi-07a")
    assert candidate["prebuilt_extract"] is True
    assert candidate["version"] == "V1.0.0.2"
    assert plan["inputs"][0]["component_versions"]["oam"] == "V1.0.0.2"


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(allow_prebuilt_extract="true"),
    lambda c: c.update(publishable=False),
    lambda c: c["materialization"].update(type="direct_include"),
])
def test_prebuilt_opt_in_requires_publishable_extraction(mutation):
    catalog = copy.deepcopy(load_catalog().to_dict())
    mutation(catalog["projects"][1]["components"][0])
    with pytest.raises(CatalogValidationError, match="allow_prebuilt_extract"):
        load_catalog(catalog)
