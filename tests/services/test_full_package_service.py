from __future__ import annotations

import copy
import io
import json
import sys
import tarfile
import types
import zipfile
from pathlib import Path

import pytest

from app.agents.package_search.package_builder_mcp import (
    PackageBuilderContextError,
    build_confirmed_full_package,
)
from app.services.full_package_service import (
    ArchiveInspectionError,
    CatalogValidationError,
    PackageBuildError,
    PlanValidationError,
    build_full_package,
    classify_inputs,
    confirm_plan,
    inspect_archive,
    load_catalog,
    sha256_file,
    validate_confirmed_plan,
    validate_full_package_artifact,
)
from app.services.package_confirmation_service import sign_confirmed_plan


def _input(path: Path, upload_id: str, *, relative_path: str = "LX10-V1.0.0.3") -> dict:
    return {
        "upload_id": upload_id,
        "original_name": path.name,
        "path": str(path),
        "relative_path": f"{relative_path}/{path.name}",
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _protocol_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for component in ("cucp", "cuup", "du"):
            archive.writestr(
                f"gnb_{component}-1.2.39.13-202604200921.arm64.deb",
                f"payload-{component}".encode(),
            )
            archive.writestr(
                f"gnb_{component}-1.2.39.13-202604200921.arm64.deb.md5",
                b"not-the-payload",
            )
        archive.writestr("version_info", b"1.2.39.13")
    return path


def _tar_gz(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def _answers(draft: dict, mappings: dict[str, object]) -> dict[str, object]:
    answers: dict[str, object] = {
        "project": "lingxi-10",
        "version": "1.0.0.3",
        "mode": "full",
    }
    answers.update({f"input:{upload_id}": value for upload_id, value in mappings.items()})
    return answers


def _confirmed_protocol(tmp_path: Path):
    catalog = load_catalog()
    protocol = _protocol_zip(tmp_path / "S-GNB-V1.2.39.13-202604200921.zip")
    manifest = [_input(protocol, "protocol", relative_path="LX10-V1.0.0.3/协议栈")]
    draft = classify_inputs(catalog, manifest)
    confirmed = confirm_plan(
        draft,
        _answers(draft, {"protocol": ["cucp", "cuup", "du"]}),
        session_id="session-1",
        user_id="user-1",
        run_id="run-1",
        catalog=catalog,
        inputs=manifest,
        confirmed_at="2026-08-14T00:00:00+00:00",
    )
    return catalog, manifest, draft, confirmed


def test_builtin_catalog_is_valid_versioned_and_hash_stable():
    first = load_catalog()
    second = load_catalog(first.to_dict())

    assert first["schema_version"] == "1.0"
    assert first.digest == second.digest
    assert len(first.digest) == 64
    project = first["projects"][0]
    attrs = {component["file_attr"] for component in project["components"]}
    assert {301, 302, 303, 307, 308, 313, 315, 401, 403, 404, 405, 406, 801} <= attrs
    recognition_only = {
        component["component_key"]
        for component in project["components"]
        if component["recognition_only"]
    }
    assert recognition_only == {"sct_sf2", "bpo_sf2", "sct_m3"}


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda data: data["projects"][0].update(project_code="../escape"), "project_code"),
        (
            lambda data: data["projects"][0]["components"][1].update(file_attr=301),
            "duplicate file_attr",
        ),
        (
            lambda data: data["projects"][0]["components"][0].update(output_name="../oam"),
            "flat filename",
        ),
        (
            lambda data: data["projects"][0]["components"][0]["materialization"].update(
                patterns=["("]
            ),
            "valid regex",
        ),
    ],
)
def test_catalog_rejects_duplicate_and_unsafe_configuration(mutation, message):
    raw = load_catalog().to_dict()
    mutation(raw)
    with pytest.raises(CatalogValidationError, match=message):
        load_catalog(raw)


def test_archive_inspection_lists_members_and_rejects_traversal(tmp_path):
    safe = _protocol_zip(tmp_path / "safe.zip")
    inspected = inspect_archive(safe, strict=True)
    assert inspected["archive_type"] == "zip"
    assert "gnb_cucp-1.2.39.13-202604200921.arm64.deb" in inspected["members"]

    unsafe = tmp_path / "unsafe.tar.gz"
    _tar_gz(unsafe, {"../../outside": b"bad"})
    best_effort = inspect_archive(unsafe)
    assert best_effort["members"] == []
    assert "unsafe archive member" in best_effort["errors"][0]
    with pytest.raises(ArchiveInspectionError, match="unsafe archive member"):
        inspect_archive(unsafe, strict=True)


def test_tar_allows_internal_relative_links_but_rejects_escaping_links(tmp_path):
    safe = tmp_path / "safe-link.tgz"
    with tarfile.open(safe, "w:gz") as archive:
        target = tarfile.TarInfo("lib/libdemo.so.1")
        target.size = 4
        archive.addfile(target, io.BytesIO(b"demo"))
        link = tarfile.TarInfo("lib/libdemo.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "libdemo.so.1"
        archive.addfile(link)
    assert inspect_archive(safe, strict=True)["members"] == ["lib/libdemo.so.1"]

    unsafe = tmp_path / "unsafe-link.tgz"
    with tarfile.open(unsafe, "w:gz") as archive:
        link = tarfile.TarInfo("lib/libdemo.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    with pytest.raises(ArchiveInspectionError, match="unsafe link"):
        inspect_archive(unsafe, strict=True)


def test_large_sparse_file_detection_uses_only_bounded_reads(tmp_path, monkeypatch):
    sparse = tmp_path / "SF2_SCT.bin"
    with sparse.open("wb") as handle:
        handle.write(b"NOT-AN-ARCHIVE")
        handle.seek(1024 * 1024 * 1024 - 1)
        handle.write(b"\0")

    def forbidden_read_bytes(_self):
        raise AssertionError("format detection must not materialize the complete file")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    inspected = inspect_archive(sparse, strict=True)
    assert inspected["is_archive"] is False
    draft = classify_inputs(
        load_catalog(),
        [
            {
                "upload_id": "sparse",
                "original_name": sparse.name,
                "path": str(sparse),
                "relative_path": "LX10-V1.0.0.3/m3/SF2_SCT.bin",
                "size": sparse.stat().st_size,
                "sha256": "0" * 64,
            }
        ],
        verify_hashes=False,
    )
    assert draft["inputs"][0]["candidates"][0]["component_key"] == "sct_m3"


def test_7z_builder_backend_streams_to_disk_via_extractall(tmp_path, monkeypatch):
    from app.services import full_package_service as service_module

    calls = []

    class FakeSevenZipFile:
        def __init__(self, source, mode):
            calls.append(("open", Path(source).name, mode))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extractall(self, path):
            calls.append(("extractall", str(path)))
            (Path(path) / "payload.bin").write_bytes(b"payload")

        def read(self, *_args, **_kwargs):
            raise AssertionError("the builder must never use py7zr.read()")

    monkeypatch.setitem(
        sys.modules,
        "py7zr",
        types.SimpleNamespace(SevenZipFile=FakeSevenZipFile),
    )
    source = tmp_path / "input.7z"
    source.write_bytes(b"7z\xbc\xaf\x27\x1c")
    destination = tmp_path / "extracted"
    destination.mkdir()
    service_module._extract_7z_streaming(source, destination)
    assert (destination / "payload.bin").read_bytes() == b"payload"
    assert [call[0] for call in calls] == ["open", "extractall"]


def test_safe_extract_checks_aggregate_disk_budget_before_backend(tmp_path, monkeypatch):
    from app.services import full_package_service as service_module

    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("payload.bin", b"x" * 100)
    destination_parent = tmp_path / "extracts"
    destination_parent.mkdir()
    reserve = int(getattr(service_module.settings, "disk_reserve_bytes", 0) or 0)
    monkeypatch.setattr(
        service_module.shutil,
        "disk_usage",
        lambda _path: types.SimpleNamespace(total=reserve + 50, used=0, free=reserve + 50),
    )
    with pytest.raises(PackageBuildError, match="not enough workspace disk"):
        service_module._safe_extract_archive(
            archive_path,
            destination_parent / "payload",
            max_members=10,
            max_bytes=1024,
        )
    assert not (destination_parent / "payload").exists()


def test_protocol_archive_classifies_as_three_components_and_questions_every_file(tmp_path):
    catalog, _manifest, draft, _confirmed = _confirmed_protocol(tmp_path)
    item = draft["inputs"][0]

    assert draft["packaging_requested"] is True
    assert draft["catalog_digest"] == catalog.digest
    assert draft["project_code"] == "lingxi-10"
    assert draft["version"] == "1.0.0.3"
    assert item["selected_component"] == ["cucp", "cuup", "du"]
    assert {candidate["component_key"] for candidate in item["candidates"]} == {
        "cucp",
        "cuup",
        "du",
    }
    assert {candidate["version"] for candidate in item["candidates"]} == {
        "V1.2.39.13.202604200921"
    }
    keys = [question["question_key"] for question in draft["questions"]]
    assert keys == ["project", "version", "mode", "input:protocol"]
    file_question = draft["questions"][-1]
    assert file_question["multiSelect"] is True
    assert all(2 <= len(question["options"]) <= 4 for question in draft["questions"])
    assert file_question["options"][0]["value"] == ["cucp", "cuup", "du"]
    assert file_question["options"][-1]["value"] == "exclude"


def test_real_resolve_labels_map_to_values_and_combined_components(tmp_path):
    catalog, manifest, draft, _ = _confirmed_protocol(tmp_path)
    questions = draft["questions"]
    answers = [
        {
            "question_index": 0,
            "selected_labels": [questions[0]["options"][0]["label"]],
            "custom_text": "must-not-overwrite-the-project",
        },
        {
            "question_index": 1,
            "selected_labels": [questions[1]["options"][0]["label"]],
        },
        {
            "question_index": 2,
            "selected_labels": ["全量包"],
        },
        {
            "question_index": 3,
            "selected_labels": ["CUCP 协议栈 + CUUP 协议栈 + DU 协议栈"],
        },
    ]

    confirmed = confirm_plan(
        draft,
        answers,
        session_id="s",
        user_id="u",
        catalog=catalog,
        inputs=manifest,
    )

    assert confirmed["project_code"] == "lingxi-10"
    assert confirmed["mode"] == "full"
    assert confirmed["inputs"][0]["selected_components"] == ["cucp", "cuup", "du"]


def test_real_resolve_oam_label_and_exclusion_are_distinct(tmp_path):
    protocol = _protocol_zip(tmp_path / "S-GNB.zip")
    oam = _tar_gz(tmp_path / "gnb-oam-lx10_v1000.tgz", {"gnb-oam-lx10": b"oam"})
    manifest = [_input(oam, "oam"), _input(protocol, "protocol")]
    catalog = load_catalog()
    draft = classify_inputs(catalog, manifest)
    by_key = {question["question_key"]: question for question in draft["questions"]}
    answers = []
    for key in ("project", "version", "mode"):
        question = by_key[key]
        answers.append(
            {
                "question_key": key,
                "selected_labels": [question["options"][0]["label"]],
            }
        )
    answers.extend(
        [
            {"question_key": "input:oam", "selected_labels": ["OAM"]},
            {"question_key": "input:protocol", "selected_labels": ["排除此文件"]},
        ]
    )
    confirmed = confirm_plan(
        draft,
        answers,
        session_id="s",
        user_id="u",
        catalog=catalog,
        inputs=manifest,
    )
    assert confirmed["inputs"][0]["selected_component"] == "oam"
    assert confirmed["inputs"][1]["include"] is False
    assert confirmed["inputs"][1]["selected_components"] == []


def test_bpo_ambiguity_prebuilt_and_recognition_only_are_explicit(tmp_path):
    bpo = tmp_path / "bb_10_master_tb_to_notify_v03001006.zip"
    with zipfile.ZipFile(bpo, "w") as archive:
        archive.writestr("build/xy_gnb_bpo_top.bin", b"bpo")
    patch = _tar_gz(
        tmp_path / "Satellite_McpServer-2026Apr17-V1.0.0-Patch.tgz",
        {"Satellite_McpServer.tgz": b"nested", "si.ini": b"PacketAttr=1002;"},
    )
    sf2 = tmp_path / "lx10_sct_sf2_fabric.zip"
    with zipfile.ZipFile(sf2, "w") as archive:
        archive.writestr("x/SF2_TOP.job", b"job")
    catalog = load_catalog()
    draft = classify_inputs(
        catalog,
        [_input(bpo, "bpo"), _input(patch, "patch"), _input(sf2, "sf2")],
    )
    items = {item["upload_id"]: item for item in draft["inputs"]}

    bpo_candidates = {candidate["component_key"] for candidate in items["bpo"]["candidates"]}
    assert {"bpoka100", "bpodvb_fpga"} <= bpo_candidates
    assert items["bpo"]["ambiguity"] == ["bpo-master-313-or-315"]
    assert items["bpo"]["selected_component"] == []
    assert items["patch"]["prebuilt"] is True
    assert all(not candidate["publishable"] for candidate in items["patch"]["candidates"])
    sf2_candidate = next(
        candidate for candidate in items["sf2"]["candidates"] if candidate["component_key"] == "sct_sf2"
    )
    assert sf2_candidate["recognition_only"] is True
    assert sf2_candidate["publishable"] is False
    assert {question["question_key"] for question in draft["questions"]} >= {
        "input:bpo",
        "input:patch",
        "input:sf2",
    }


def test_confirmation_rejects_missing_unknown_unpublishable_and_changed_input(tmp_path):
    catalog, manifest, draft, confirmed = _confirmed_protocol(tmp_path)
    with pytest.raises(PlanValidationError, match="missing mandatory"):
        confirm_plan(
            draft,
            {"project": "lingxi-10", "version": "1.0.0.3", "mode": "full"},
            session_id="s",
            user_id="u",
            catalog=catalog,
        )
    with pytest.raises(PlanValidationError, match="unknown component"):
        confirm_plan(
            draft,
            _answers(draft, {"protocol": "made_up"}),
            session_id="s",
            user_id="u",
            catalog=catalog,
        )

    tampered = copy.deepcopy(confirmed)
    tampered["version"] = "9.9.9.9"
    with pytest.raises(PlanValidationError, match="plan hash"):
        validate_confirmed_plan(tampered, catalog)

    Path(manifest[0]["path"]).write_bytes(b"changed after confirmation")
    with pytest.raises(PlanValidationError, match="size changed|hash changed"):
        validate_confirmed_plan(confirmed, catalog)


def test_deterministic_build_extracts_one_source_once_and_reopens(tmp_path, monkeypatch):
    catalog, _manifest, _draft, confirmed = _confirmed_protocol(tmp_path)
    from app.services import full_package_service as service_module

    original = service_module._safe_extract_archive
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(service_module, "_safe_extract_archive", counted)
    first = build_full_package(
        confirmed,
        workspace_dir=tmp_path / "work",
        output_dir=tmp_path / "work" / "output",
        catalog=catalog,
    )
    second = build_full_package(
        confirmed,
        workspace_dir=tmp_path / "work",
        output_dir=tmp_path / "work" / "output",
        catalog=catalog,
    )

    assert len(calls) == 2  # once per build, not once per each of the 3 components
    assert first["sha256"] == second["sha256"]
    assert first["artifact_name"] == second["artifact_name"]
    assert [component["file_attr"] for component in first["components"]] == [302, 307, 308]
    report = validate_full_package_artifact(
        first["artifact_path"], expected_manifest=first["manifest"]
    )
    assert report["valid"] is True
    assert "FileNumInPacket=3;" in report["si_ini"]
    assert "FileAttr_1=302;" in report["si_ini"]
    assert first["manifest"]["inputs"][0]["sha256"] == confirmed["inputs"][0]["sha256"]


def test_artifact_validation_never_unbounded_reads_component_payloads(tmp_path, monkeypatch):
    catalog, _manifest, _draft, confirmed = _confirmed_protocol(tmp_path)
    result = build_full_package(confirmed, workspace_dir=tmp_path / "work", catalog=catalog)
    original_read = tarfile.ExFileObject.read
    read_sizes = []

    def bounded_read(self, size=-1):
        read_sizes.append(size)
        if size is None or size < 0:
            raise AssertionError("artifact validation attempted an unbounded payload read")
        return original_read(self, size)

    monkeypatch.setattr(tarfile.ExFileObject, "read", bounded_read)
    report = validate_full_package_artifact(
        result["artifact_path"], expected_manifest=result["manifest"]
    )
    assert report["valid"] is True
    assert read_sizes
    assert max(read_sizes) <= 16 * 1024 * 1024 + 1


def test_direct_include_preserves_original_archive_bytes(tmp_path):
    core = _tar_gz(
        tmp_path / "yh5gc_V0.2.7.9.tar.gz",
        {"bin/open5gs-amfd": b"amf", "etc/open5gs/amf.yaml": b"config"},
    )
    catalog = load_catalog()
    manifest = [_input(core, "core")]
    draft = classify_inputs(catalog, manifest)
    confirmed = confirm_plan(
        draft,
        _answers(draft, {"core": "galaxy_core_network"}),
        session_id="s",
        user_id="u",
        catalog=catalog,
        inputs=manifest,
    )
    result = build_full_package(confirmed, workspace_dir=tmp_path / "work", catalog=catalog)

    with tarfile.open(result["artifact_path"], "r:gz") as archive:
        embedded = archive.extractfile("galaxy_core_network.tgz")
        assert embedded is not None
        assert embedded.read() == core.read_bytes()


def test_build_rejects_unconfirmed_and_traversal_direct_include(tmp_path):
    catalog, _manifest, _draft, confirmed = _confirmed_protocol(tmp_path)
    unconfirmed = copy.deepcopy(confirmed)
    unconfirmed["status"] = "draft"
    with pytest.raises(PlanValidationError, match="not confirmed"):
        build_full_package(unconfirmed, workspace_dir=tmp_path / "work", catalog=catalog)

    unsafe = _tar_gz(tmp_path / "yh5gc_V0.2.7.9.tar.gz", {"../escape": b"bad"})
    manifest = [_input(unsafe, "unsafe")]
    draft = classify_inputs(catalog, manifest)
    plan = confirm_plan(
        draft,
        _answers(draft, {"unsafe": "galaxy_core_network"}),
        session_id="s",
        user_id="u",
        catalog=catalog,
        inputs=manifest,
    )
    with pytest.raises(PackageBuildError, match="unsafe archive member"):
        build_full_package(plan, workspace_dir=tmp_path / "unsafe-work", catalog=catalog)
    assert not (tmp_path / "escape").exists()


def test_package_builder_helper_requires_signature_and_is_idempotent(tmp_path):
    workspace = tmp_path / "workspace"
    inputs_dir = workspace / "inputs"
    inputs_dir.mkdir(parents=True)
    protocol = _protocol_zip(inputs_dir / "S-GNB-V1.2.39.13-202604200921.zip")
    manifest = [_input(protocol, "protocol")]
    catalog = load_catalog()
    draft = classify_inputs(catalog, manifest)
    plan = confirm_plan(
        draft,
        _answers(draft, {"protocol": ["cucp", "cuup", "du"]}),
        session_id="session-1",
        user_id="user-1",
        run_id="run-1",
        catalog=catalog,
        inputs=manifest,
        confirmed_at="2026-08-14T00:00:00+00:00",
    )
    task = {
        "run_id": "run-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "package_catalog": catalog.to_dict(),
        "inputs_manifest": {"inputs": manifest},
        "confirmed_plan": plan.to_dict(),
    }
    (workspace / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(Exception, match="确认签名|token|签名"):
        build_confirmed_full_package(
            workspace,
            expected_run_id="run-1",
            expected_session_id="session-1",
            expected_user_id="user-1",
        )
    assert not (workspace / "output").exists()

    task["confirmed_plan"] = sign_confirmed_plan(plan.to_dict(), ttl_seconds=60)
    (workspace / "task.json").write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
    first = build_confirmed_full_package(
        workspace,
        expected_run_id="run-1",
        expected_session_id="session-1",
        expected_user_id="user-1",
    )
    second = build_confirmed_full_package(
        workspace,
        expected_run_id="run-1",
        expected_session_id="session-1",
        expected_user_id="user-1",
    )
    assert first["sha256"] == second["sha256"]
    assert Path(first["artifact_path"]).is_file()
    assert (workspace / "output" / "build-result.json").is_file()


def test_package_builder_rejects_manifest_outside_workspace_before_build(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _protocol_zip(tmp_path / "outside.zip")
    catalog = load_catalog()
    manifest = [_input(outside, "outside")]
    draft = classify_inputs(catalog, manifest)
    plan = confirm_plan(
        draft,
        _answers(draft, {"outside": ["cucp", "cuup", "du"]}),
        session_id="s",
        user_id="u",
        run_id="r",
        catalog=catalog,
        inputs=manifest,
    )
    task = {
        "run_id": "r",
        "session_id": "s",
        "user_id": "u",
        "package_catalog": catalog.to_dict(),
        "inputs_manifest": manifest,
        "confirmed_plan": sign_confirmed_plan(plan.to_dict(), ttl_seconds=60),
    }
    (workspace / "task.json").write_text(json.dumps(task), encoding="utf-8")
    with pytest.raises(PackageBuilderContextError, match="escapes"):
        build_confirmed_full_package(workspace)


def test_lx10_real_fixture_classifies_every_file_and_builds_complete_tgz(tmp_path):
    """Slow integration coverage for the user-provided 380 MiB LX10 fixture."""

    fixture_root = Path(__file__).resolve().parents[3] / "Temp" / "LX10-V1.0.0.3"
    if not fixture_root.is_dir():
        pytest.skip("Temp/LX10-V1.0.0.3 fixture is not available")
    paths = sorted(
        path
        for path in fixture_root.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    )
    assert len(paths) == 13
    manifest = [
        _input(
            path,
            f"lx10-{index:02d}",
            relative_path=path.relative_to(fixture_root.parent).parent.as_posix(),
        )
        for index, path in enumerate(paths, start=1)
    ]
    catalog = load_catalog()
    draft = classify_inputs(catalog, manifest)
    by_name = {item["original_name"]: item for item in draft["inputs"]}
    ids_by_name = {item["original_name"]: item["upload_id"] for item in manifest}

    assert draft["project_code"] == "lingxi-10"
    assert draft["version"] == "1.0.0.3"
    input_question_ids = {
        question["question_key"].removeprefix("input:")
        for question in draft["questions"]
        if question["question_key"].startswith("input:")
    }
    assert input_question_ids == {item["upload_id"] for item in manifest}

    protocol = by_name["S-GNB-V1.2.39.13-202604200921.zip"]
    assert protocol["selected_component"] == ["cucp", "cuup", "du"]
    protocol_question = next(
        question
        for question in draft["questions"]
        if question["question_key"] == f"input:{protocol['upload_id']}"
    )
    assert protocol_question["options"][0]["value"] == ["cucp", "cuup", "du"]
    patch = by_name["Satellite_McpServer-2026Apr17-1849-V1.0.0-Patch.tgz"]
    assert patch["prebuilt"] is True
    assert all(not candidate["publishable"] for candidate in patch["candidates"])
    assert next(
        candidate
        for candidate in by_name["bpo_sf2_20241011.zip"]["candidates"]
        if candidate["component_key"] == "bpo_sf2"
    )["recognition_only"]
    assert next(
        candidate
        for candidate in by_name["lx10_sct_sf2_fabric_can_hardrst_260331.zip"]["candidates"]
        if candidate["component_key"] == "sct_sf2"
    )["recognition_only"]
    assert next(
        candidate
        for candidate in by_name["SF2_SCT.bin"]["candidates"]
        if candidate["component_key"] == "sct_m3"
    )["recognition_only"]

    choices = {
        "bb_10_master_tb_to_notify_v03001006.zip": "bpoka100",
        "bpo_sf2_20241011.zip": "exclude",
        "lx10_sct_sf2_fabric_can_hardrst_260331.zip": "exclude",
        "sct_10_master_100to400_check_v00030008.zip": "sct_fpga",
        "Satellite_McpServer-2026Apr17-1849-V1.0.0-Patch.tgz": "exclude",
        "Satellite_McpServer_20260417_1908e3c.tgz": "satellite_mcp_server",
        "gnb-oam-lx10_v1000_1908e3c_20260417-1717.tgz": "oam",
        "SF2_SCT.bin": "exclude",
        "S-GNB-V1.2.39.13-202604200921.zip": ["cucp", "cuup", "du"],
        "yh5gc_V0.2.7.9.tar.gz": "galaxy_core_network",
        "S5GC-V1.13.tgz": "pengcheng_core_amf",
        "script.tgz": "pengcheng_core_scripts",
        "upf_bundle_20_134.tgz": "pengcheng_core_upf",
    }
    answers = {
        "project": "lingxi-10",
        "version": "1.0.0.3",
        "mode": "full",
        **{
            f"input:{ids_by_name[name]}": decision
            for name, decision in choices.items()
        },
    }
    confirmed = confirm_plan(
        draft,
        answers,
        session_id="fixture-session",
        user_id="fixture-user",
        run_id="fixture-run",
        catalog=catalog,
        inputs=manifest,
        confirmed_at="2026-08-14T00:00:00+00:00",
    )
    result = build_full_package(
        confirmed,
        workspace_dir=tmp_path / "lx10-build",
        catalog=catalog,
    )
    report = validate_full_package_artifact(
        result["artifact_path"], expected_manifest=result["manifest"]
    )

    assert report["valid"] is True
    assert report["component_count"] == 11
    assert {component["file_attr"] for component in result["components"]} == {
        301,
        302,
        303,
        307,
        308,
        313,
        401,
        404,
        405,
        406,
        801,
    }
    assert next(
        component
        for component in result["components"]
        if component["component_key"] == "pengcheng_core_amf"
    )["version"] == "V1.13.0.0"
    assert Path(result["artifact_path"]).stat().st_size == result["size"]
    assert sha256_file(result["artifact_path"]) == result["sha256"]
