"""Agent-entry OCR-merge tests (openspec/changes/add-multimodal-image-input 6.4).

Verifies that image-bearing turns feed the OCR-merged text to the agent at the
representative multipart entry points (log analysis, project expert), that a
degraded OCR turn keeps the original text and emits an ``ocr_status`` frame, and
that image-free turns are unchanged.
"""

from __future__ import annotations

import base64
import json
import time

from app.models.chat import ImageAttachment
from app.services import ocr_service


def _decode_sse_event(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk[len("data: ") :].strip())


def _img() -> ImageAttachment:
    return ImageAttachment(media_type="image/png", data=base64.b64encode(b"hi").decode())


class _FakeResultAgent:
    def run_sync(self, _ctx, _cancel_event=None, _trace_emitter=None, _clarification_binding=None):
        return {
            "status": "ok",
            "model": "fake-model",
            "answer": "done",
            "summary": "done",
            "severity": "info",
            "root_cause_hypotheses": [],
            "recommended_actions": [],
            "related_keywords": [],
        }


def _patch_ocr_success(monkeypatch):
    monkeypatch.setattr(ocr_service, "is_configured", lambda: True)

    async def _fake_extract(images, **kwargs):
        return ocr_service.OcrResult(
            text="[图片 1]\nCODE 42", status="succeeded", image_count=len(images)
        )

    monkeypatch.setattr(ocr_service, "extract_text", _fake_extract)


def _patch_ocr_unconfigured(monkeypatch):
    monkeypatch.setattr(ocr_service, "is_configured", lambda: False)


# ─────────────────────── Log Analysis entry ───────────────────────


def _make_log_ctx(tmp_path):
    from app.agents.log_analysis.workspace import WorkspaceContext

    task_json = tmp_path / "task.json"
    task_json.write_text("{}", encoding="utf-8")
    logs_dir = tmp_path / "logs"
    repo_dir = tmp_path / "repo"
    logs_dir.mkdir()
    repo_dir.mkdir()
    return WorkspaceContext(
        task_id="task-1",
        temp_dir=str(tmp_path),
        logs_dir=str(logs_dir),
        repo_dir=str(repo_dir),
        task_json_path=str(task_json),
        metadata={"question": "why?"},
    )


def _patch_log_service(monkeypatch, service, ctx, captured):
    monkeypatch.setattr(service, "_load_context", lambda *_a, **_kw: (ctx, {"session_id": "s", "filename": None}))

    def _capture_bind(_ctx, *, question, hints):
        captured["question"] = question

    monkeypatch.setattr(service, "_bind_question_and_hints", _capture_bind)
    monkeypatch.setattr(service, "_touch_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_register_chat_run", _noop_async())
    monkeypatch.setattr(service, "_finalize_chat_run", _noop_async())
    monkeypatch.setattr(service, "_persist_job_result", _noop_async())

    async def _fake_history_hint(**_kwargs):
        return ""

    monkeypatch.setattr(service, "_build_history_hint", _fake_history_hint)
    monkeypatch.setattr(
        "app.services.log_analysis_chat_service.LogAnalysisAgent", _FakeResultAgent
    )


def _noop_async():
    async def _fn(*_a, **_kw):
        return None

    return _fn


async def _drain_until_done(stream):
    events = []
    async for chunk in stream:
        event = _decode_sse_event(chunk)
        events.append(event)
        if event.get("event") == "done":
            break
    return events


async def test_log_analysis_merges_images_into_agent_question(monkeypatch, tmp_path):
    from app.services.log_analysis_chat_service import LogAnalysisChatService

    service = LogAnalysisChatService()
    ctx = _make_log_ctx(tmp_path)
    captured: dict = {}
    _patch_log_service(monkeypatch, service, ctx, captured)
    _patch_ocr_success(monkeypatch)

    events = await _drain_until_done(
        service.stream(
            message="看看这个报错",
            session_id="s-img",
            history_json=None,
            file=None,
            images=[_img()],
            remember=False,
            db=None,
            user=None,
        )
    )

    assert "<user_image_ocr" in captured["question"]
    assert "CODE 42" in captured["question"]
    # Success path emits no degradation frame.
    assert not any(e.get("event") == "ocr_status" for e in events)
    assert any(
        e.get("event") == "ocr_result"
        and e.get("image_count") == 1
        and "CODE 42" in e.get("text", "")
        for e in events
    )


async def test_log_analysis_without_images_is_unchanged(monkeypatch, tmp_path):
    from app.services.log_analysis_chat_service import LogAnalysisChatService

    service = LogAnalysisChatService()
    ctx = _make_log_ctx(tmp_path)
    captured: dict = {}
    _patch_log_service(monkeypatch, service, ctx, captured)
    _patch_ocr_success(monkeypatch)

    events = await _drain_until_done(
        service.stream(
            message="纯文本问题",
            session_id="s-noimg",
            history_json=None,
            file=None,
            images=None,
            remember=False,
            db=None,
            user=None,
        )
    )

    assert captured["question"] == "纯文本问题"
    assert "<user_image_ocr" not in captured["question"]
    assert not any(e.get("event") == "ocr_status" for e in events)


async def test_log_analysis_degraded_emits_ocr_status_and_keeps_text(monkeypatch, tmp_path):
    from app.services.log_analysis_chat_service import LogAnalysisChatService

    service = LogAnalysisChatService()
    ctx = _make_log_ctx(tmp_path)
    captured: dict = {}
    _patch_log_service(monkeypatch, service, ctx, captured)
    _patch_ocr_unconfigured(monkeypatch)

    events = await _drain_until_done(
        service.stream(
            message="带图但未配置",
            session_id="s-degraded",
            history_json=None,
            file=None,
            images=[_img()],
            remember=False,
            db=None,
            user=None,
        )
    )

    assert captured["question"] == "带图但未配置"
    ocr_events = [e for e in events if e.get("event") == "ocr_status"]
    assert len(ocr_events) == 1
    assert ocr_events[0]["status"] == "unconfigured"
    assert ocr_events[0]["image_count"] == 1


# ─────────────────────── Project Expert entry ───────────────────────


def _make_pe_ctx(tmp_path):
    from app.agents.project_expert.workspace import WorkspaceContext

    task_json = tmp_path / "task.json"
    task_json.write_text("{}", encoding="utf-8")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    return WorkspaceContext(
        task_id="pe-1",
        temp_dir=str(tmp_path),
        repo_dir=str(repo_dir),
        task_json_path=str(task_json),
        metadata={"question": "", "hints": ""},
    )


async def test_project_expert_merges_images_into_agent_question(monkeypatch, tmp_path):
    from app.services.project_expert_chat_service import ProjectExpertChatService

    service = ProjectExpertChatService()
    ctx = _make_pe_ctx(tmp_path)
    captured: dict = {}

    monkeypatch.setattr(
        service,
        "_load_context",
        lambda *_a, **_kw: (ctx, {"project_repo_id": 1, "project_code": "p"}),
    )

    def _capture_bind(_ctx, *, question, hints):
        captured["question"] = question

    monkeypatch.setattr(service, "_bind_question_and_hints", _capture_bind)
    monkeypatch.setattr(service, "_touch_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_register_chat_run", _noop_async())
    monkeypatch.setattr(service, "_finalize_chat_run", _noop_async())
    monkeypatch.setattr(service, "_persist_job_result", _noop_async())

    async def _fake_history_hint(**_kwargs):
        return ""

    monkeypatch.setattr(service, "_build_history_hint", _fake_history_hint)
    monkeypatch.setattr(
        "app.services.project_expert_chat_service.ProjectExpertAgent", _FakeResultAgent
    )
    _patch_ocr_success(monkeypatch)

    events = await _drain_until_done(
        service.stream(
            message="这个模块是做什么的",
            session_id="pe-img",
            history_json=None,
            remember=False,
            project_repo_id=1,
            images=[_img()],
            db=None,
            user=None,
        )
    )

    assert "<user_image_ocr" in captured["question"]
    assert "CODE 42" in captured["question"]
    assert not any(e.get("event") == "ocr_status" for e in events)
    assert any(e.get("event") == "ocr_result" for e in events)
