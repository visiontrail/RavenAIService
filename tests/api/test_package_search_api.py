"""Integration tests for ``POST /packages/agent-search`` (project-bound).

We drive the FastAPI app via ``TestClient`` (sync) for the non-stream
branch and the StreamingResponse ``body_iterator`` for the SSE branch.
``PackageSearchAgent.run`` and ``.stream`` are monkeypatched so the
tests never reach the real Claude SDK; ``project_repo_service.get_by_id``
is stubbed so no database is needed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import packages as packages_api
from app.models.database import get_db


PROJECT_REPO_ID = 3


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(packages_api.router)

    async def fake_db():
        yield None

    application.dependency_overrides[get_db] = fake_db
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_workspace(monkeypatch, tmp_path):
    """Run the real prepare/cleanup against an isolated temp base dir."""
    from app.config import settings as app_settings

    monkeypatch.setattr(
        app_settings, "code_repo_clone_base_dir", str(tmp_path / "clones")
    )
    return tmp_path


@pytest.fixture
def fake_project_repo(monkeypatch):
    """Stub project_repo lookup: only ``PROJECT_REPO_ID`` exists & is enabled."""
    repo = SimpleNamespace(
        id=PROJECT_REPO_ID,
        project_code="proj-a",
        project_name="Project A",
        repo_url="https://git.example.com/proj-a.git",
        default_branch="main",
        enabled=True,
    )
    disabled = SimpleNamespace(
        id=99,
        project_code="proj-off",
        project_name="Disabled",
        repo_url="https://git.example.com/off.git",
        default_branch="main",
        enabled=False,
    )

    async def fake_get_by_id(db, repo_id):
        if repo_id == PROJECT_REPO_ID:
            return repo
        if repo_id == 99:
            return disabled
        return None

    async def fake_supports_agent(db, project_repo, agent_key):
        # Only the enabled Project A supports package_search in these tests.
        return getattr(project_repo, "id", None) == PROJECT_REPO_ID

    from app.services import project_repo_service

    monkeypatch.setattr(project_repo_service, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(project_repo_service, "supports_agent", fake_supports_agent)
    return repo


@pytest.fixture
def fake_agent(monkeypatch, fake_workspace, fake_project_repo):
    """Patch ``PackageSearchAgent`` so .run / .stream return canned data."""
    captured: Dict[str, Any] = {"runs": [], "streams": []}

    canned_run = {
        "status": "ok",
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
        async def run(self, ctx, cancel_event=None, trace_emitter=None):
            captured["runs"].append({"ctx": ctx})
            return dict(canned_run)

        async def stream(self, ctx, cancel_event=None):
            captured["streams"].append({"ctx": ctx})
            for event in canned_stream_events:
                yield event

    import app.agents.package_search.agent as agent_module
    monkeypatch.setattr(agent_module, "PackageSearchAgent", FakeAgent)
    return captured


# ────────────────────── non-stream branch ──────────────────────


def test_non_stream_returns_structured_payload(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "find latest ka-tx package", "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Here is the answer."
    assert body["recommended_package_ids"] == ["pkg-real-1"]
    assert body["relevant_package_ids"] == ["pkg-real-1", "pkg-real-2"]
    assert body["model"] == "fake-model"
    assert "usage" in body
    assert isinstance(body["tool_trace"], list)


def test_non_stream_binds_workspace_to_selected_project(client, fake_agent):
    from pathlib import Path

    resp = client.post(
        "/packages/agent-search",
        json={"query": "x", "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 200
    ctx = fake_agent["runs"][0]["ctx"]
    assert ctx.project_code == "proj-a"
    assert ctx.metadata["repo_info"]["source"] == "user_selected_project_repo"
    # Per-request workspace: cleaned up once the response is produced.
    assert not Path(ctx.temp_dir).exists()


def test_missing_project_repo_id_returns_400(client, fake_agent):
    resp = client.post("/packages/agent-search", json={"query": "x"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["reason"] == "project_repo_required"


def test_unknown_project_repo_id_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search", json={"query": "x", "project_repo_id": 12345}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "project_repo_required"


def test_disabled_project_repo_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search", json={"query": "x", "project_repo_id": 99}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "project_repo_required"


def test_empty_query_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "   ", "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 400
    assert "query" in resp.json()["detail"].lower()


def test_missing_query_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search", json={"project_repo_id": PROJECT_REPO_ID}
    )
    assert resp.status_code == 400


def test_overlong_query_returns_400(client, fake_agent):
    over_limit = "x" * 1001
    resp = client.post(
        "/packages/agent-search",
        json={"query": over_limit, "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 400
    assert "1000" in resp.json()["detail"]


def test_non_string_session_id_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search",
        json={"query": "x", "session_id": 42, "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 400


# ────────────────────── stream branch ──────────────────────


def test_stream_returns_sse_events(client, fake_agent):
    with client.stream(
        "POST",
        "/packages/agent-search",
        json={"query": "stream me", "stream": True, "project_repo_id": PROJECT_REPO_ID},
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


def test_stream_missing_project_repo_id_returns_400(client, fake_agent):
    resp = client.post(
        "/packages/agent-search", json={"query": "stream me", "stream": True}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "project_repo_required"


# ────────────────────── invalid ID filtering (end-to-end via real agent) ──────────────────────


def test_invalid_ids_get_filtered_by_agent(
    client, monkeypatch, fake_workspace, fake_project_repo
):
    """Use the real agent with a stubbed SDK loop and stubbed service.

    Bypasses ``fake_agent`` fixture — we want the actual project-scoped
    filtering path in ``PackageSearchAgent.run`` to execute.
    """
    from app.agents.package_search import agent as agent_module
    from app.services import raven_package_service as svc_module

    # Stub get_package: ``pkg-real-1`` belongs to the selected project,
    # ``pkg-foreign`` belongs to another project (must also be dropped).
    catalog = {
        "pkg-real-1": {"id": "pkg-real-1", "projectCode": "proj-a"},
        "pkg-foreign": {"id": "pkg-foreign", "projectCode": "proj-b"},
    }
    monkeypatch.setattr(
        svc_module.raven_package_service, "get_package", catalog.get
    )

    # Stub _build_options to avoid touching anthropic_client config.
    def fake_build_options(self, *, system_prompt, project_code, cwd, endpoint=None):
        return (object(), "fake-model", "fake-provider")
    monkeypatch.setattr(agent_module.PackageSearchAgent, "_build_options", fake_build_options)

    class _ResultMessage:
        def __init__(self, result):
            self.content = None
            self.result = result

    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1", "fake-id"],'
        ' "relevant_package_ids": ["pkg-real-1", "pkg-foreign"]}\n'
        "```\n"
    )

    async def fake_loop(self, prompt, options):
        yield _ResultMessage(answer_text)
    monkeypatch.setattr(agent_module.PackageSearchAgent, "_run_sdk_loop", fake_loop)

    resp = client.post(
        "/packages/agent-search",
        json={"query": "test", "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_package_ids"] == ["pkg-real-1"]
    assert body["relevant_package_ids"] == ["pkg-real-1"]
    warnings = [e for e in body["tool_trace"] if e.get("type") == "warning"]
    assert any("filtered 2 invalid ids" in w["message"] for w in warnings)


# ────────────────────── metrics project attribution ──────────────────────


@pytest.fixture
def capture_metrics(monkeypatch):
    """Capture the kwargs passed to ``record_agent_run_usage`` for assertions."""
    calls: List[Dict[str, Any]] = []

    async def fake_record(**kwargs):
        calls.append(kwargs)

    from app.services import metrics_service

    monkeypatch.setattr(metrics_service, "record_agent_run_usage", fake_record)
    return calls


def test_non_stream_records_metric_with_project_repo_id(
    client, fake_agent, capture_metrics
):
    """The API-driven search must attribute its ai_usage event to the bound
    project; otherwise every run shows as "未归属项目" in the metrics dashboard."""
    resp = client.post(
        "/packages/agent-search",
        json={"query": "x", "project_repo_id": PROJECT_REPO_ID},
    )
    assert resp.status_code == 200
    assert len(capture_metrics) == 1
    assert capture_metrics[0]["project_repo_id"] == str(PROJECT_REPO_ID)


def test_stream_records_metric_with_project_repo_id(
    client, fake_agent, capture_metrics
):
    with client.stream(
        "POST",
        "/packages/agent-search",
        json={"query": "x", "stream": True, "project_repo_id": PROJECT_REPO_ID},
    ) as resp:
        assert resp.status_code == 200
        b"".join(resp.iter_bytes())
    assert len(capture_metrics) == 1
    assert capture_metrics[0]["project_repo_id"] == str(PROJECT_REPO_ID)
