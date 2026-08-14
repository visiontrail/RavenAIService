"""Focused regressions for Configuration Manager publication authority boundaries."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.package_search.agent import (
    PACKAGING_TASK_VALUE_KEYS,
    _has_confirmed_package_plan,
    _is_packaging_task,
)
from app.agents.package_search.workspace import prepare
from app.services.full_package_service import (
    CatalogValidationError,
    load_catalog,
    sha256_file,
)
from app.services.package_search_chat_service import (
    AgentJob,
    PackageSearchChatService,
)


def _project_definition(
    code: str,
    label: str,
    *,
    packet_attr: int,
    recognition_pattern: str,
) -> dict[str, Any]:
    project = copy.deepcopy(load_catalog()["projects"][0])
    project["project_code"] = code
    project["label"] = label
    project["packet_attr"] = packet_attr
    project["prebuilt_recognition"] = []
    project["recognition"] = [
        {
            "field": "filename",
            "pattern": recognition_pattern,
            "weight": 100,
            "reason": "focused project recognition",
        }
    ]
    component = copy.deepcopy(
        next(
            item
            for item in project["components"]
            if item["component_key"] == "oam"
        )
    )
    component["recognition"] = [
        {
            "field": "filename",
            "pattern": recognition_pattern,
            "weight": 100,
            "reason": "focused component recognition",
        }
    ]
    component["classification_threshold"] = 10
    project["components"] = [component]
    return project


def _catalog_payload(projects: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_catalog().to_dict()
    payload.pop("catalog_digest", None)
    payload["catalog_version"] = "hardening-regression"
    payload["projects"] = copy.deepcopy(projects)
    # Fail in the fixture rather than producing a misleading service failure.
    load_catalog(payload)
    return payload


def _manifest(ctx: Any, filename: str) -> dict[str, Any]:
    source = Path(ctx.temp_dir) / "inputs" / filename
    source.write_bytes(b"component-payload")
    return {
        "schema_version": 1,
        "inputs": [
            {
                "upload_id": "component-1",
                "original_name": source.name,
                "path": str(source),
                "relative_path": source.name,
                "size": source.stat().st_size,
                "sha256": sha256_file(source),
                "detected_type": "binary",
            }
        ],
    }


def _job(ctx: Any, manifest: dict[str, Any], *, project_code: str | None) -> AgentJob:
    return AgentJob(
        session_id="hardening-session",
        task_id=ctx.task_id,
        context_meta={"project_code": project_code},
        question="build a full package",
        user_id="user-1",
        remember=False,
        started_at=time.monotonic(),
        run_id="hardening-run",
        owner_scope="user:user-1",
        input_manifest=manifest,
        project_catalog=[
            {"id": 1, "project_code": "alpha", "project_name": "Alpha"},
            {"id": 2, "project_code": "beta", "project_name": "Beta"},
        ],
    )


async def _wait_for_request(trace: list[dict[str, Any]], count: int) -> dict[str, Any]:
    for _ in range(1_000):
        requests = [
            event
            for event in trace
            if event.get("type") == "clarification_request"
        ]
        if len(requests) >= count:
            return requests[count - 1]
        await asyncio.sleep(0.002)
    raise AssertionError(f"clarification request {count} was not emitted")


def _answers(request: dict[str, Any], *, project_label: str) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for index, question in enumerate(request["questions"]):
        key = question["question_key"]
        custom_text = None
        if key == "project":
            label = project_label
        elif key == "version":
            label = "手动输入版本"
            custom_text = "1.0.0.3"
        elif key == "mode":
            label = "全量包"
        else:
            label = next(
                option["label"]
                for option in question["options"]
                if option["label"] != "排除此文件"
            )
        answers.append(
            {
                "question_index": index,
                "selected_labels": [label],
                "custom_text": custom_text,
            }
        )
    return answers


def _seed_authority(ctx: Any) -> None:
    task = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
    task.update({key: {"authority": key} for key in PACKAGING_TASK_VALUE_KEYS})
    task.update({"packaging_requested": True, "package_mode": "packaging"})
    Path(ctx.task_json_path).write_text(json.dumps(task), encoding="utf-8")
    for run in ("hardening-run", "stale-run"):
        plan = Path(ctx.temp_dir) / "package_plan" / run / "confirmed-plan.json"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            json.dumps({"confirmation_token": f"signed-{run}"}),
            encoding="utf-8",
        )
    ctx.metadata["confirmed_plan"] = {"confirmation_token": "in-memory"}
    ctx.metadata["inputs_manifest"] = {"inputs": []}


@pytest.mark.asyncio
async def test_prebound_alpha_to_beta_uses_beta_project_skill_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming B must not retain B's lower-precedence definition from A's layer."""
    from app.config import settings
    from app.services import skills_service
    from app.services.chat_run_service import chat_run_service

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    alpha = _project_definition(
        "alpha", "Alpha Project", packet_attr=111, recognition_pattern="alpha-oam"
    )
    beta_global = _project_definition(
        "beta", "Beta Project", packet_attr=222, recognition_pattern="beta-oam"
    )
    beta_project = _project_definition(
        "beta", "Beta Project", packet_attr=999, recognition_pattern="beta-oam"
    )
    global_catalog = _catalog_payload([alpha, beta_global])
    beta_catalog = _catalog_payload([beta_project])

    def materialize(
        agent_key: str,
        target_dir: str | Path,
        *,
        skill_names: Any = None,
        project_code: str | None = None,
    ) -> list[str]:
        del agent_key, skill_names
        destination = (
            Path(target_dir)
            / ".claude"
            / "skills"
            / "full-package-build"
            / "references"
        )
        destination.mkdir(parents=True, exist_ok=True)
        payload = beta_catalog if project_code == "beta" else global_catalog
        (destination / "package-projects.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return ["full-package-build"]

    monkeypatch.setattr(skills_service, "materialize_enabled_skills", materialize)
    repo = SimpleNamespace(
        project_code="alpha",
        project_name="Alpha",
        repo_url="",
        default_branch="main",
    )
    ctx = prepare(
        project_repo=repo,
        question="build",
        session_id="hardening-session",
    )
    manifest = _manifest(ctx, "beta-oam-V1.0.0.3.bin")
    service = PackageSearchChatService()
    service.registry_dir = tmp_path / "registry"
    service.registry_dir.mkdir()
    job = _job(ctx, manifest, project_code="alpha")
    service._jobs[job.session_id] = job
    trace: list[dict[str, Any]] = []

    preflight = asyncio.create_task(
        service._prepare_and_confirm_packaging(job, ctx, trace.append)
    )
    first = await _wait_for_request(trace, 1)
    assert first["questions"][0]["options"][0]["label"] == "Beta Project"
    broker = chat_run_service.get_broker_by_run_id(job.run_id)
    assert broker is not None
    assert broker.resolve(
        first["request_id"],
        {"answers": _answers(first, project_label="Beta Project")},
    )

    # The model already proposed B, but B's project-level rules differ from the
    # B definition visible through pre-bound project A. This still requires a
    # fresh full confirmation based on B's effective catalog.
    second = await _wait_for_request(trace, 2)
    assert [item["question_key"] for item in second["questions"]] == [
        "project",
        "version",
        "mode",
        "input:component-1",
    ]
    broker = chat_run_service.get_broker_by_run_id(job.run_id)
    assert broker is not None
    assert broker.resolve(
        second["request_id"],
        {"answers": _answers(second, project_label="Beta Project")},
    )

    signed = await asyncio.wait_for(preflight, timeout=10)
    assert signed["project_code"] == "beta"
    assert signed["packet_attr"] == 999
    snapshot = json.loads(
        (
            Path(ctx.temp_dir)
            / "package_plan"
            / job.run_id
            / "package-projects.json"
        ).read_text(encoding="utf-8")
    )
    assert snapshot["projects"][0]["packet_attr"] == 999


@pytest.mark.asyncio
async def test_invalid_project_catalog_fails_closed_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.services import skills_service

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    alpha = _project_definition(
        "alpha", "Alpha Project", packet_attr=111, recognition_pattern="alpha-oam"
    )
    global_catalog = _catalog_payload([alpha])

    def materialize(
        agent_key: str,
        target_dir: str | Path,
        *,
        skill_names: Any = None,
        project_code: str | None = None,
    ) -> list[str]:
        del agent_key, skill_names
        destination = (
            Path(target_dir)
            / ".claude"
            / "skills"
            / "full-package-build"
            / "references"
        )
        destination.mkdir(parents=True, exist_ok=True)
        content = "{ invalid project override" if project_code else json.dumps(global_catalog)
        (destination / "package-projects.json").write_text(content, encoding="utf-8")
        return ["full-package-build"]

    monkeypatch.setattr(skills_service, "materialize_enabled_skills", materialize)
    ctx = prepare(
        project_repo=None,
        question="build",
        session_id="hardening-session",
    )
    manifest = _manifest(ctx, "alpha-oam.bin")
    service = PackageSearchChatService()
    service.registry_dir = tmp_path / "registry"
    service.registry_dir.mkdir()
    job = _job(ctx, manifest, project_code=None)
    job.project_catalog = [job.project_catalog[0]]
    trace: list[dict[str, Any]] = []

    with pytest.raises(CatalogValidationError):
        await service._prepare_and_confirm_packaging(job, ctx, trace.append)

    assert not any(
        event.get("type") == "clarification_request" for event in trace
    )
    assert any(event.get("catalog_invalid") is True for event in job.events)


def test_pure_search_revokes_all_packaging_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    ctx = prepare(
        project_repo=None,
        question="build",
        session_id="hardening-session",
    )
    service = PackageSearchChatService()
    _seed_authority(ctx)
    service._bind_question_and_hints(
        ctx,
        question="pure search",
        hints="",
        packaging_requested=False,
    )
    pure_search_task = json.loads(
        Path(ctx.task_json_path).read_text(encoding="utf-8")
    )
    assert not set(PACKAGING_TASK_VALUE_KEYS) & pure_search_task.keys()
    assert _is_packaging_task(pure_search_task) is False
    assert _has_confirmed_package_plan(pure_search_task) is False
    assert not (Path(ctx.temp_dir) / "package_plan").exists()


@pytest.mark.asyncio
async def test_packaging_run_finally_revokes_current_and_stale_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "code_repo_clone_base_dir", str(tmp_path / "work"))
    ctx = prepare(
        project_repo=None,
        question="build",
        session_id="hardening-session",
    )
    _seed_authority(ctx)
    service = PackageSearchChatService()
    job = AgentJob(
        session_id="hardening-session",
        task_id=ctx.task_id,
        context_meta={},
        question="build",
        user_id="user-1",
        remember=False,
        started_at=time.monotonic(),
        run_id="hardening-run",
        owner_scope="user:user-1",
        input_manifest={"inputs": [{"upload_id": "component-1"}]},
    )

    async def confirm(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {"plan_hash": "signed-plan", "confirmation_token": "secret"}

    async def build(*args: Any, **kwargs: Any) -> tuple[dict, dict, dict]:
        del args, kwargs
        return (
            {"components": []},
            {"id": "package-1"},
            {
                "name": "whole.tgz",
                "package_id": "package-1",
                "download_url": "/raven/api/download/package-1",
                "components": [],
            },
        )

    async def no_op(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    monkeypatch.setattr(service, "_prepare_and_confirm_packaging", confirm)
    monkeypatch.setattr(service, "_build_and_publish_package", build)
    monkeypatch.setattr(service, "_persist_job_result", no_op)
    monkeypatch.setattr(service, "_finalize_chat_run", no_op)

    await service._run_job_async(job, ctx)

    completed_task = json.loads(
        Path(ctx.task_json_path).read_text(encoding="utf-8")
    )
    assert job.done is True
    assert job.error is None
    assert not set(PACKAGING_TASK_VALUE_KEYS) & completed_task.keys()
    assert _is_packaging_task(completed_task) is False
    assert _has_confirmed_package_plan(completed_task) is False
    assert not (Path(ctx.temp_dir) / "package_plan").exists()
    assert "confirmed_plan" not in ctx.metadata
    assert "inputs_manifest" not in ctx.metadata
