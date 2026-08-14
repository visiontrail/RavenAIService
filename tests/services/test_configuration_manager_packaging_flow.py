"""Configuration Manager gate -> signed build -> repository publication flow."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import zipfile
from pathlib import Path

import pytest

from app.agents.package_search.workspace import prepare
from app.services.full_package_service import sha256_file
from app.services.package_search_chat_service import AgentJob, PackageSearchChatService


def _protocol_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for component in ("cucp", "cuup", "du"):
            archive.writestr(
                f"gnb_{component}-1.2.39.13-202604200921.arm64.deb",
                f"payload-{component}".encode(),
            )
        archive.writestr("version_info", b"1.2.39.13")
    return path


@pytest.mark.asyncio
async def test_mandatory_gate_precedes_build_and_publishes_downloadable_artifact(
    tmp_path, monkeypatch
):
    from app.config import settings
    from app.services.chat_run_service import chat_run_service
    from app.services.raven_package_service import raven_package_service

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "disk_reserve_bytes", 0)
    monkeypatch.setattr(settings, "upload_max_size_mb", 50)
    raven_package_service.data_dir = tmp_path / "raven"
    raven_package_service.uploads_dir = tmp_path / "raven" / "uploads"
    raven_package_service.metadata_file = tmp_path / "raven" / "package-metadata.json"

    service = PackageSearchChatService()
    service.registry_dir = tmp_path / "registry"
    service.registry_dir.mkdir()
    ctx = prepare(
        project_repo=None,
        question="请制作整包",
        session_id="session-package",
    )
    source = _protocol_zip(
        Path(ctx.temp_dir) / "inputs" / "S-GNB-V1.2.39.13-202604200921.zip"
    )
    manifest = {
        "schema_version": 1,
        "inputs": [
            {
                "upload_id": "protocol-stack",
                "original_name": source.name,
                "path": str(source),
                "relative_path": f"LX10-V1.0.0.3/协议栈/{source.name}",
                "size": source.stat().st_size,
                "sha256": sha256_file(source),
                "detected_type": "zip",
            }
        ],
    }
    task_path = Path(ctx.task_json_path)
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["packaging_requested"] = True
    task["inputs_manifest"] = manifest
    task_path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")

    context_meta = {
        "session_id": "session-package",
        "task_id": ctx.task_id,
        "temp_dir": ctx.temp_dir,
        "repo_dir": ctx.repo_dir,
        "task_json_path": ctx.task_json_path,
        "project_repo_id": None,
        "project_code": None,
        "project_name": None,
    }
    job = AgentJob(
        session_id="session-package",
        task_id=ctx.task_id,
        context_meta=context_meta,
        question="请制作整包",
        user_id="user-1",
        remember=False,
        started_at=time.monotonic(),
        run_id="run-package",
        owner_scope="user:user-1",
        input_manifest=manifest,
        # This simulates a user with ordinary clarification disabled: the
        # mandatory service gate does not read job.clarification at all.
        clarification=None,
        project_catalog=[
            {
                "id": 10,
                "project_code": "lingxi-10",
                "project_name": "Lingxi 10",
                "enabled_agent_keys": ["package_search"],
            }
        ],
    )
    service._jobs[job.session_id] = job
    trace: list[dict] = []

    preflight = asyncio.create_task(
        service._prepare_and_confirm_packaging(job, ctx, trace.append)
    )
    for _ in range(200):
        request = next(
            (event for event in trace if event.get("type") == "clarification_request"),
            None,
        )
        if request is not None:
            break
        await asyncio.sleep(0.005)
    else:
        raise AssertionError("mandatory clarification was not emitted")

    # Absolutely no repository side effect is allowed before the answers.
    assert not raven_package_service.metadata_file.exists()
    assert not raven_package_service.uploads_dir.exists()
    questions = request["questions"]
    assert len(questions) == 4  # project + version + mode + the one input
    assert request["mandatory"] is True
    assert request["purpose"] == "package_build_confirmation"
    assert questions[-1]["question_key"] == "input:protocol-stack"
    assert source.name in questions[-1]["question"]

    answers = []
    for index, question in enumerate(questions):
        if question["question_key"] == "mode":
            label = "全量包"
        else:
            label = question["options"][0]["label"]
        answers.append(
            {
                "question_index": index,
                "selected_labels": [label],
                "custom_text": None,
            }
        )
    broker = chat_run_service.get_broker_by_run_id(job.run_id)
    assert broker is not None
    assert broker.resolve(request["request_id"], {"answers": answers}) is True
    signed = await asyncio.wait_for(preflight, timeout=10)

    assert signed["project_code"] == "lingxi-10"
    assert signed["inputs"][0]["selected_components"] == ["cucp", "cuup", "du"]
    assert signed["confirmation_token"]
    assert not raven_package_service.metadata_file.exists()

    job.confirmed_plan = signed
    build, package, artifact = await service._build_and_publish_package(job, ctx)

    assert build["status"] == "built"
    assert [item["component_key"] for item in build["components"]] == [
        "cucp",
        "cuup",
        "du",
    ]
    stored_path = raven_package_service.package_file(package)
    assert stored_path.is_file()
    assert hashlib.sha256(stored_path.read_bytes()).hexdigest() == artifact["sha256"]
    assert artifact["download_url"] == f"/raven/api/download/{package['id']}"
    assert raven_package_service.get_package(package["id"]) is not None


@pytest.mark.asyncio
async def test_cancelling_while_mandatory_confirmation_is_open_is_immediate_and_safe(
    tmp_path, monkeypatch
):
    from app.config import settings
    from app.services.raven_package_service import raven_package_service

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "disk_reserve_bytes", 0)
    monkeypatch.setattr(settings, "upload_max_size_mb", 50)
    monkeypatch.setattr(raven_package_service, "data_dir", tmp_path / "raven")
    monkeypatch.setattr(
        raven_package_service, "uploads_dir", tmp_path / "raven" / "uploads"
    )
    monkeypatch.setattr(
        raven_package_service,
        "metadata_file",
        tmp_path / "raven" / "package-metadata.json",
    )

    service = PackageSearchChatService()
    service.registry_dir = tmp_path / "registry"
    service.registry_dir.mkdir()
    ctx = prepare(
        project_repo=None,
        question="请制作整包",
        session_id="session-cancel-package",
    )
    source = _protocol_zip(
        Path(ctx.temp_dir) / "inputs" / "S-GNB-V1.2.39.13-cancel.zip"
    )
    manifest = {
        "schema_version": 1,
        "inputs": [
            {
                "upload_id": "protocol-stack",
                "original_name": source.name,
                "path": str(source),
                "relative_path": f"LX10-V1.0.0.3/协议栈/{source.name}",
                "size": source.stat().st_size,
                "sha256": sha256_file(source),
                "detected_type": "zip",
            }
        ],
    }
    task_path = Path(ctx.task_json_path)
    task_data = json.loads(task_path.read_text(encoding="utf-8"))
    task_data.update({"packaging_requested": True, "inputs_manifest": manifest})
    task_path.write_text(json.dumps(task_data, ensure_ascii=False), encoding="utf-8")

    job = AgentJob(
        session_id="session-cancel-package",
        task_id=ctx.task_id,
        context_meta={
            "session_id": "session-cancel-package",
            "task_id": ctx.task_id,
            "temp_dir": ctx.temp_dir,
            "repo_dir": ctx.repo_dir,
            "task_json_path": ctx.task_json_path,
        },
        question="请制作整包",
        user_id="user-1",
        remember=False,
        started_at=time.monotonic(),
        run_id="run-cancel-package",
        owner_scope="user:user-1",
        input_manifest=manifest,
        clarification=None,
        project_catalog=[
            {
                "id": 10,
                "project_code": "lingxi-10",
                "project_name": "Lingxi 10",
                "enabled_agent_keys": ["package_search"],
            }
        ],
    )
    service._jobs[job.session_id] = job
    runner = asyncio.create_task(service._run_job_async(job, ctx))
    for _ in range(200):
        if any(
            event.get("type") == "clarification_request" for event in job.trace_events
        ):
            break
        await asyncio.sleep(0.005)
    else:
        raise AssertionError("mandatory clarification was not emitted")

    cancelled_at = time.monotonic()
    assert service.cancel(job.session_id) is True
    await asyncio.wait_for(runner, timeout=1)

    assert time.monotonic() - cancelled_at < 0.5
    assert job.done is True
    assert job.error is None
    assert job.result and job.result["status"] == "cancelled"
    assert not raven_package_service.metadata_file.exists()
    assert not raven_package_service.uploads_dir.exists()
    assert any(
        event.get("type") == "clarification_resolved"
        and event.get("outcome") == "cancelled"
        for event in job.trace_events
    )
