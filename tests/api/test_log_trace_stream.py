"""Integration tests for ``GET /logs/{log_id}/ai-analysis/trace/stream``.

We drive the route handler directly (returns ``StreamingResponse``) and
walk its ``body_iterator``. Both ``log_service.get_log_detail`` and the
Redis ``TraceBuffer`` are mocked — the goal is to verify the three-mode
state machine (running / terminal / missing) and the ``?from_seq`` cursor.
"""

from __future__ import annotations

import asyncio
import json
import types
from typing import List, Optional

import pytest


# ─────────────────────────── fixtures / helpers ────────────────────────────


def _make_event(seq: int, etype: str = "step_start", **fields) -> dict:
    event = {"type": etype, "task_id": "celery-task-1", "seq": seq, "timestamp": float(seq)}
    event.update(fields)
    return event


def _make_log_info(
    *,
    status: Optional[str],
    task_id: Optional[str] = "celery-task-1",
    result: Optional[dict] = None,
):
    """Return a minimal stand-in for the LogFileInfo pydantic model."""
    return types.SimpleNamespace(
        id="log-1",
        is_deleted=False,
        ai_analysis_task_id=task_id,
        ai_analysis_status=status,
        ai_analysis_progress=100.0 if status in {"completed", "failed"} else 50.0,
        ai_analysis_result=result,
    )


class FakeTraceBuffer:
    """In-memory ``TraceBuffer`` substitute used by the endpoint poll loop."""

    def __init__(self) -> None:
        self.events: List[dict] = []

    def read_all(self, _task_id: str) -> List[dict]:
        return list(self.events)

    def push(self, event: dict) -> None:
        self.events.append(event)


async def _drive_stream(response, *, max_frames: int = 50, timeout: float = 2.0):
    """Pull frames off a StreamingResponse.body_iterator until 'stream_end'."""
    frames: list[dict] = []

    async def _pull():
        async for raw in response.body_iterator:
            payload = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            for line in payload.split("\n"):
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                frames.append(json.loads(line[len("data:"):].strip()))
                if frames[-1].get("event") == "stream_end" or len(frames) >= max_frames:
                    return

    await asyncio.wait_for(_pull(), timeout=timeout)
    return frames


@pytest.fixture(autouse=True)
def _short_poll(monkeypatch):
    """Shrink the timing knobs so tests do not wait realtime intervals."""
    monkeypatch.setattr(
        "app.api.logs._TRACE_STREAM_POLL_INTERVAL_SECONDS", 0.01
    )
    monkeypatch.setattr(
        "app.api.logs._TRACE_STREAM_HEARTBEAT_INTERVAL_SECONDS", 0.05
    )


# ─────────────────────────────── tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_no_task_returns_404(monkeypatch):
    from app.api import logs as logs_api
    from fastapi import HTTPException

    async def fake_get_log_detail(_db, _log_id):
        return _make_log_info(status=None, task_id=None, result=None)

    monkeypatch.setattr(logs_api.log_service, "get_log_detail", fake_get_log_detail)
    monkeypatch.setattr(logs_api.request_validator, "validate_log_id", lambda *_: None)

    with pytest.raises(HTTPException) as excinfo:
        await logs_api.stream_ai_analysis_trace(log_id="log-1", from_seq=0, db=None)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_terminal_state_replays_persisted_events(monkeypatch):
    from app.api import logs as logs_api

    persisted = [
        _make_event(1, "run_start", model="m", provider="p"),
        _make_event(2, "step_start", step_id="s1", tool_name="Bash", tool_input={}),
        _make_event(3, "step_end", step_id="s1", status="ok", output_excerpt="ok"),
        _make_event(4, "run_complete", trace_summary={
            "thought_duration_seconds": 1.0, "tool_call_count": 1, "thinking_chars": 0
        }),
    ]

    async def fake_get_log_detail(_db, _log_id):
        return _make_log_info(status="completed", result={"trace_events": persisted})

    monkeypatch.setattr(logs_api.log_service, "get_log_detail", fake_get_log_detail)
    monkeypatch.setattr(logs_api.request_validator, "validate_log_id", lambda *_: None)

    response = await logs_api.stream_ai_analysis_trace(log_id="log-1", from_seq=0, db=None)
    frames = await _drive_stream(response)

    types_seen = [f.get("type") for f in frames if f.get("event") == "agent_trace"]
    assert types_seen == ["run_start", "step_start", "step_end", "run_complete"]
    assert frames[-1]["event"] == "stream_end"
    assert frames[-1]["reason"] == "completed"


@pytest.mark.asyncio
async def test_terminal_state_respects_from_seq_cursor(monkeypatch):
    """A reconnecting client passes from_seq → only newer events stream out."""
    from app.api import logs as logs_api

    persisted = [
        _make_event(1, "run_start"),
        _make_event(2, "step_start"),
        _make_event(3, "step_end"),
        _make_event(4, "run_complete", trace_summary={
            "thought_duration_seconds": 1.0, "tool_call_count": 1, "thinking_chars": 0
        }),
    ]

    async def fake_get_log_detail(_db, _log_id):
        return _make_log_info(status="completed", result={"trace_events": persisted})

    monkeypatch.setattr(logs_api.log_service, "get_log_detail", fake_get_log_detail)
    monkeypatch.setattr(logs_api.request_validator, "validate_log_id", lambda *_: None)

    response = await logs_api.stream_ai_analysis_trace(log_id="log-1", from_seq=2, db=None)
    frames = await _drive_stream(response)

    seqs = [f.get("seq") for f in frames if f.get("event") == "agent_trace"]
    assert seqs == [3, 4]
    assert frames[-1]["event"] == "stream_end"


@pytest.mark.asyncio
async def test_running_state_polls_redis_then_closes_on_completion(monkeypatch):
    from app.api import logs as logs_api

    buffer = FakeTraceBuffer()
    buffer.push(_make_event(1, "run_start"))
    buffer.push(_make_event(2, "step_start"))

    completed_result = {
        "trace_events": [
            _make_event(1, "run_start"),
            _make_event(2, "step_start"),
            _make_event(3, "step_end"),
            _make_event(4, "run_complete", trace_summary={
                "thought_duration_seconds": 1.0, "tool_call_count": 1, "thinking_chars": 0
            }),
        ]
    }

    # First two get_log_detail calls return "running"; the third returns
    # "completed" — exercises the transition mid-stream.
    call_count = {"n": 0}

    async def fake_get_log_detail(_db, _log_id):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            return _make_log_info(status="completed", result=completed_result)
        # While the endpoint is polling, simulate the Celery worker adding
        # an event to Redis on the second tick.
        if call_count["n"] == 2:
            buffer.push(_make_event(3, "step_end"))
        return _make_log_info(status="running")

    monkeypatch.setattr(logs_api.log_service, "get_log_detail", fake_get_log_detail)
    monkeypatch.setattr(logs_api.request_validator, "validate_log_id", lambda *_: None)
    monkeypatch.setattr(logs_api, "get_buffer", lambda: buffer)
    # The endpoint imports get_buffer lazily inside _generate(); also patch
    # the source module so the deferred import resolves to the same fake.
    monkeypatch.setattr(
        "app.services.agent_trace_redis.get_buffer", lambda: buffer
    )

    response = await logs_api.stream_ai_analysis_trace(log_id="log-1", from_seq=0, db=None)
    frames = await _drive_stream(response, max_frames=20, timeout=3.0)

    types_seen = [f.get("type") for f in frames if f.get("event") == "agent_trace"]
    # All four trace events should arrive exactly once.
    assert types_seen.count("run_start") == 1
    assert types_seen.count("step_start") == 1
    assert types_seen.count("step_end") == 1
    assert types_seen.count("run_complete") == 1
    assert frames[-1]["event"] == "stream_end"
    assert frames[-1]["reason"] == "completed"
