"""Integration tests for the happy-path of ``POST /chat`` and ``POST /chat/stream``.

These complement ``test_chat_provider_gate.py`` (which covers the negative
``provider_no_mcp_support`` branch) by exercising the full SSE / response shape
when the SDK actually emits assistant text. The Anthropic SDK is mocked at the
``claude_agent_sdk.query`` boundary so no network call leaves the test.

Coverage (task 47):
- streaming SSE order:  session → run_start → thinking_* → run_complete → done
- non-streaming fields: ``answer`` / ``model`` / ``session_id`` / ``messages``
- history length truncation flows through to the prompt
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_chat as ai_chat_api
from app.api.users import get_current_user, get_optional_user
from app.models.database import get_db


# ────────────────────────── Fake SDK plumbing ──────────────────────


class _FakeUsage:
    def __init__(self, in_t: int = 5, out_t: int = 7) -> None:
        self.input_tokens = in_t
        self.output_tokens = out_t
        self.cache_read_input_tokens = 0


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, blocks: List[_TextBlock]) -> None:
        self.content = blocks
        self.usage = _FakeUsage()


class _ResultMessage:
    def __init__(self, text: str) -> None:
        self.result = text
        self.num_turns = 1
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


def _fake_query_factory(messages: List[Any]):
    async def _q(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        for m in messages:
            yield m

    return _q


def _capture_prompt_query_factory(messages: List[Any], captured: Dict[str, str]):
    """Like ``_fake_query_factory`` but also records the ``prompt`` argument."""

    async def _q(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        if isinstance(prompt, str):
            captured["prompt"] = prompt
        else:
            chunks: List[str] = []
            async for chunk in prompt:
                chunks.append(str(chunk))
            captured["prompt"] = "".join(chunks)
        for m in messages:
            yield m

    return _q


class _FakeDevice:
    def __init__(self) -> None:
        self.capabilities = {"protocol_version": 2, "mcp": {"servers": []}}


# ────────────────────────── FastAPI test app ────────────────────────


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    application.dependency_overrides[get_optional_user] = lambda: None
    application.dependency_overrides[get_current_user] = lambda: type(
        "User", (), {"id": "test-user", "username": "tester", "role": "user", "language": "zh"}
    )()

    async def _no_db():
        yield None

    application.dependency_overrides[get_db] = _no_db
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def anthropic_ok(monkeypatch):
    """Force provider=anthropic so the DeviceAgent capability gate lets us through."""
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr(
        "app.config.settings.anthropic_model", "claude-sonnet-4-6", raising=False
    )


@pytest.fixture
def fake_device(monkeypatch):
    async def _get_device(*_a, **_kw):
        return _FakeDevice()

    monkeypatch.setattr(
        "app.services.device_link_service.device_link_manager.get_device", _get_device
    )


def _parse_sse_events(body: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith("data: "):
            continue
        payload = chunk[len("data: "):]
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return out


# ───────────────────────────── Tests ────────────────────────────────


def test_chat_stream_happy_path_emits_session_runstart_thinking_runcomplete_done(
    client, anthropic_ok, fake_device, monkeypatch
):
    """Streaming endpoint must emit the canonical event sequence in order."""

    fake_query = _fake_query_factory([
        _AssistantMessage([_TextBlock("好的，正在执行")]),
        _ResultMessage("好的，正在执行"),
    ])
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)

    resp = client.post(
        "/chat/stream",
        json={
            "message": "帮我看一下设备状态",
            "session_id": "sess-happy-1",
            "agent_type": "device",
            "target_device_id": "dev-1",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text

    events = _parse_sse_events(resp.text)
    event_types = [e.get("event") for e in events]

    # ``session`` is yielded first so the front-end can update routing.
    assert event_types[0] == "session"
    # The agent run begins with ``run_start`` and ends with ``run_complete``
    # before the trailing service-level ``done`` frame.
    rs_idx = event_types.index("run_start")
    rc_idx = event_types.index("run_complete")
    done_idx = event_types.index("done")
    assert rs_idx < rc_idx < done_idx
    # Thinking events must sit between run_start and run_complete.
    assert "thinking_start" in event_types
    assert "thinking_end" in event_types
    ts_idx = event_types.index("thinking_start")
    te_idx = event_types.index("thinking_end")
    assert rs_idx < ts_idx <= te_idx < rc_idx

    # ``done`` payload carries the aggregated answer + model + full message list.
    done = events[done_idx]
    assert done.get("session_id") == "sess-happy-1"
    assert done.get("answer") == "好的，正在执行"
    assert isinstance(done.get("messages"), list)
    # original history is empty + 1 user + 1 ai = 2 messages
    assert len(done["messages"]) == 2
    assert done["messages"][0]["role"] == "user"
    assert done["messages"][1]["role"] == "ai"
    assert done["messages"][1]["content"] == "好的，正在执行"


def test_chat_nonstream_happy_path_returns_populated_response(
    client, anthropic_ok, fake_device, monkeypatch
):
    """Non-streaming endpoint must populate ``answer`` / ``model`` / ``messages``."""

    fake_query = _fake_query_factory([
        _AssistantMessage([_TextBlock("最终回复")]),
        _ResultMessage("最终回复"),
    ])
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)

    resp = client.post(
        "/chat",
        json={
            "message": "你好",
            "session_id": "sess-nonstream-1",
            "agent_type": "device",
            "target_device_id": "dev-1",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["session_id"] == "sess-nonstream-1"
    assert body["answer"] == "最终回复"
    # The effective model falls back to settings.anthropic_model when run_start
    # provides it (it does in this fixture).
    assert body["model"] == "claude-sonnet-4-6"
    assert isinstance(body["messages"], list)
    # 1 user + 1 ai (no prior history was loaded).
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "你好"
    assert body["messages"][1]["role"] == "ai"
    assert body["messages"][1]["content"] == "最终回复"


def test_chat_stream_truncates_history_to_max_turns(
    client, anthropic_ok, fake_device, monkeypatch
):
    """``anthropic_max_history_turns`` must cap the history block in the prompt.

    We supply 20 prior messages via the request ``history`` field but configure
    ``max_history_turns=2`` (=> keep last 4 entries). The captured prompt should
    contain the most recent entries but not the oldest.
    """
    monkeypatch.setattr(
        "app.config.settings.anthropic_max_history_turns", 2, raising=False
    )

    captured: Dict[str, str] = {}
    fake_query = _capture_prompt_query_factory(
        [_AssistantMessage([_TextBlock("ok")]), _ResultMessage("ok")],
        captured,
    )
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)

    history = [
        {"role": "user" if i % 2 == 0 else "ai", "content": f"m{i}"}
        for i in range(20)
    ]

    resp = client.post(
        "/chat/stream",
        json={
            "message": "新的问题",
            "session_id": "sess-trunc",
            "agent_type": "device",
            "target_device_id": "dev-1",
            "history": history,
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text

    prompt = captured.get("prompt", "")
    # With max_turns=2 → keep last 4 history entries: m16..m19.
    assert "m19" in prompt
    assert "m18" in prompt
    assert "m17" in prompt
    assert "m16" in prompt
    # Older entries must be dropped.
    assert "m15" not in prompt
    assert "m0" not in prompt
    # Current user message also appears.
    assert "新的问题" in prompt
