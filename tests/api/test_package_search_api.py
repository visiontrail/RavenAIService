"""Integration tests for ``POST /packages/agent-search``.

We drive the FastAPI app via ``TestClient`` (sync) for the non-stream
branch and the StreamingResponse ``body_iterator`` for the SSE branch.
``PackageSearchAgent.run`` and ``.stream`` are monkeypatched so the
tests never reach the real Claude SDK.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import packages as packages_api


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(packages_api.router)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_agent(monkeypatch):
    """Patch ``PackageSearchAgent`` so .run / .stream return canned data."""
    captured: Dict[str, Any] = {"runs": [], "streams": []}

    canned_run = {
        "answer": "Here is the answer.",
        "recommended_package_ids": ["pkg-real-1"],
        "relevant_package_ids": ["pkg-real-1", "pkg-real-2"],
        "notes": "demo",
        "tool_trace": [
            {"name": "mcp__package_search__list_packages", "input": "{}", "output_excerpt": "ok"},
        ],
        "trace_events": [],
        "trace_summary": {"thought_duration_seconds": 0.1, "tool_call_count": 1, "thinking_chars": 0},
        "model": "fake-model",
        "provider": "fake-provider",
        "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0},
        "duration_seconds": 0.1,
        "session_id": "sess-1",
    }

    canned_stream_events: List[dict] = [
        {"type": "run_start", "task_id": "sess-1", "seq": 1, "timestamp": 1.0,
         "model": "fake-model", "provider": "fake-provider"},
        {"type": "step_start", "task_id": "sess-1", "seq": 2, "timestamp": 1.1,
         "step_id": "s1", "tool_name": "mcp__package_search__list_packages", "tool_input": {}},
        {"type": "step_end", "task_id": "sess-1", "seq": 3, "timestamp": 1.2,
         "step_id": "s1", "status": "ok", "output_excerpt": "ok", "duration_seconds": 0.1},
        {"type": "run_complete", "task_id": "sess-1", "seq": 4, "timestamp": 1.3,
         "trace_summary": {"thought_duration_seconds": 0.3, "tool_call_count": 1, "thinking_chars": 0},
         "final_text": "done"},
        {"type": "final", "task_id": "sess-1", "seq": 5, "timestamp": 1.4,
         "data": {
             "answer": "Here is the answer.",
             "recommended_package_ids": ["pkg-real-1"],
             "relevant_package_ids": ["pkg-real-1"],
             "notes": "demo",
             "tool_trace": [],
             "model": "fake-model",
             "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0},
         }},
    ]

    class FakeAgent:
        async def run(self, query, session_id=None):
            captured["runs"].append({"query": query, "session_id": session_id})
            return dict(canned_run)

        async def stream(self, query, session_id=None):
            captured["streams"].append({"query": query, "session_id": session_id})
            for event in canned_stream_events:
                yield event

    import app.agents.package_search.agent as agent_module
    monkeypatch.setattr(agent_module, "PackageSearchAgent", FakeAgent)
    return captured


# ────────────────────── non-stream branch ──────────────────────


def test_non_stream_returns_structured_payload(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "find latest ka-tx package"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Here is the answer."
    assert body["recommended_package_ids"] == ["pkg-real-1"]
    assert body["relevant_package_ids"] == ["pkg-real-1", "pkg-real-2"]
    assert body["model"] == "fake-model"
    assert "usage" in body
    assert isinstance(body["tool_trace"], list)
    # session_id not provided → agent receives None
    assert fake_agent["runs"][0]["session_id"] is None


def test_non_stream_passes_session_id(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "x", "session_id": "my-session"},
    )
    assert resp.status_code == 200
    assert fake_agent["runs"][0]["session_id"] == "my-session"


def test_empty_query_returns_400(client, fake_agent):
    resp = client.post("/packages/agent-search", json={"query": "   "})
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_missing_query_returns_400(client, fake_agent):
    resp = client.post("/packages/agent-search", json={})
    assert resp.status_code == 400


def test_overlong_query_returns_400(client, fake_agent):
    over_limit = "x" * 1001
    resp = client.post("/packages/agent-search", json={"query": over_limit})
    assert resp.status_code == 400
    assert "1000" in resp.json()["detail"]


def test_non_string_session_id_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "x", "session_id": 42},
    )
    assert resp.status_code == 400


# ────────────────────── stream branch ──────────────────────


def test_stream_returns_sse_events(client, fake_agent):
    with client.stream(
        "POST",
        "/packages/agent-search",
        json={"query": "stream me", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes()).decode("utf-8")

    # Each SSE frame: ``event: <type>\ndata: <json>\n\n``.
    frames = [chunk for chunk in body.split("\n\n") if chunk.strip()]
    event_types = []
    final_data = None
    for frame in frames:
        lines = frame.splitlines()
        event_line = next((ln for ln in lines if ln.startswith("event: ")), None)
        data_line = next((ln for ln in lines if ln.startswith("data: ")), None)
        if event_line:
            event_types.append(event_line[len("event: "):])
        if event_line == "event: final" and data_line:
            final_data = json.loads(data_line[len("data: "):])

    assert "run_start" in event_types
    assert "step_start" in event_types
    assert "step_end" in event_types
    assert "run_complete" in event_types
    assert "final" in event_types
    assert final_data is not None
    assert final_data["data"]["recommended_package_ids"] == ["pkg-real-1"]


# ────────────────────── invalid ID filtering (end-to-end via real agent) ──────────────────────


def test_invalid_ids_get_filtered_by_agent(client, monkeypatch):
    """Use the real agent with a stubbed SDK loop and stubbed service.

    Bypasses ``fake_agent`` fixture — we want the actual filtering path
    in ``PackageSearchAgent._drive`` to run.
    """
    from app.agents.package_search import agent as agent_module
    from app.services import raven_package_service as svc_module

    # Stub get_package: only ``pkg-real-1`` exists.
    monkeypatch.setattr(
        svc_module.raven_package_service,
        "get_package",
        lambda pid: {"id": pid} if pid == "pkg-real-1" else None,
    )

    # Stub _build_options to avoid touching anthropic_client config.
    def fake_build_options(self, *, system_prompt, max_turns=None):
        return (object(), "fake-model", "fake-provider")
    monkeypatch.setattr(agent_module.PackageSearchAgent, "_build_options", fake_build_options)

    # Stub _run_sdk_loop with a fake message yielding the fenced JSON answer.
    class _TextBlock:
        def __init__(self, text):
            self.text = text

    class _Msg:
        def __init__(self, blocks):
            self.content = blocks

    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1", "fake-id"],'
        ' "relevant_package_ids": ["pkg-real-1", "ghost"]}\n'
        "```\n"
    )

    async def fake_loop(self, prompt, options):
        yield _Msg([_TextBlock(answer_text)])
    monkeypatch.setattr(agent_module.PackageSearchAgent, "_run_sdk_loop", fake_loop)

    resp = client.post("/packages/agent-search", json={"query": "test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_package_ids"] == ["pkg-real-1"]
    assert body["relevant_package_ids"] == ["pkg-real-1"]
    warnings = [e for e in body["tool_trace"] if e.get("type") == "warning"]
    assert any("filtered 2 invalid ids" in w["message"] for w in warnings)
