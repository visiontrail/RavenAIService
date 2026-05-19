from __future__ import annotations

import json
import time

import pytest

from app.agents.log_analysis.workspace import WorkspaceContext
from app.services.log_analysis_chat_service import LogAnalysisChatService


def _decode_sse_event(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk[len("data: "):].strip())


@pytest.mark.asyncio
async def test_log_analysis_stream_sends_heartbeat_while_agent_runs(monkeypatch, tmp_path):
    task_json = tmp_path / "task.json"
    task_json.write_text("{}", encoding="utf-8")
    logs_dir = tmp_path / "logs"
    repo_dir = tmp_path / "repo"
    logs_dir.mkdir()
    repo_dir.mkdir()

    ctx = WorkspaceContext(
        task_id="task-1",
        temp_dir=str(tmp_path),
        logs_dir=str(logs_dir),
        repo_dir=str(repo_dir),
        task_json_path=str(task_json),
        metadata={"log_type": "oam_antenna", "question": "why failed?"},
    )
    context_meta = {
        "session_id": "session-1",
        "filename": "main_oam.tgz",
        "log_type": "oam_antenna",
    }

    class FakeLogAnalysisAgent:
        def run_sync(self, _ctx):
            time.sleep(0.03)
            return {
                "status": "ok",
                "model": "fake-model",
                "answer": "分析完成",
                "summary": "分析完成",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
            }

    service = LogAnalysisChatService()
    monkeypatch.setattr(service, "_load_context", lambda *_args, **_kwargs: (ctx, context_meta))
    monkeypatch.setattr(service, "_bind_question_and_hints", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_touch_context", lambda *_args, **_kwargs: None)

    async def fake_history_hint(**_kwargs):
        return ""

    async def fake_save_result(**_kwargs):
        return None

    monkeypatch.setattr(service, "_build_history_hint", fake_history_hint)
    monkeypatch.setattr(service, "_save_analysis_result", fake_save_result)
    monkeypatch.setattr(
        "app.services.log_analysis_chat_service.LogAnalysisAgent",
        FakeLogAnalysisAgent,
    )
    monkeypatch.setattr(
        "app.services.log_analysis_chat_service._AGENT_PROGRESS_INTERVAL_SECONDS",
        0.01,
    )

    events = []
    async for chunk in service.stream(
        message="why failed?",
        session_id="session-1",
        history_json=None,
        file=None,
        remember=False,
        db=None,
        user=None,
    ):
        event = _decode_sse_event(chunk)
        events.append(event)
        if event.get("event") == "done":
            break

    assert any(event.get("heartbeat") for event in events)
    assert events[-1]["event"] == "done"
    assert events[-1]["answer"]
