"""Integration test for the DeviceAgent provider capability gate via ``POST /chat``.

The gate (``DeviceAgent.run_stream`` ``provider_no_mcp_support`` branch) is
already unit-tested in ``tests/agents/device_agent/test_agent.py``. This file
verifies the *end-to-end SSE wiring*: when the active provider lacks MCP
support, the streaming endpoint surfaces an ``event=error`` payload with
``error_kind="provider_no_mcp_support"`` instead of invoking the SDK.
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
def deepseek_no_mcp(monkeypatch):
    """Force the active provider to deepseek with ``supports_mcp_server_tools=False``.

    The real deepseek profile may flip this flag over time (it currently
    advertises True since the SDK proxies in-process tool_use), so we install
    a fixed test profile rather than reading the live one.
    """
    from app.agents.anthropic_client import ProviderProfile
    import app.agents.anthropic_client as ac

    fake = ProviderProfile(
        name="deepseek",
        default_base_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-v4-pro",
        default_small_fast_model="deepseek-v4-flash",
        supports_image_input=False,
        supports_document_input=False,
        supports_mcp_server_tools=False,
        thinking_budget_tokens_effective=False,
        disable_parallel_tool_use_effective=False,
    )
    monkeypatch.setitem(ac.PROVIDER_PROFILES, "deepseek", fake)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "deepseek")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")


def _parse_sse_events(body: str) -> List[Dict[str, Any]]:
    """Decode the ``data: <json>`` blocks emitted by ``_sse_event``."""
    events: List[Dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith("data: "):
            continue
        payload = chunk[len("data: "):]
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events


def test_chat_stream_refuses_when_provider_no_mcp_support(
    client, deepseek_no_mcp, monkeypatch
):
    """The streaming chat endpoint must NOT touch the SDK when the gate fires."""

    sdk_calls = {"n": 0}

    async def _should_not_be_called(**kwargs):  # noqa: ARG001
        sdk_calls["n"] += 1
        if False:
            yield

    monkeypatch.setattr("claude_agent_sdk.query", _should_not_be_called)

    resp = client.post(
        "/chat/stream",
        json={
            "message": "list background tasks",
            "session_id": "sess-deepseek",
            "agent_type": "device",
            "target_device_id": "dev-x",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text

    events = _parse_sse_events(resp.text)
    types = [e.get("event") for e in events]

    # session frame emitted before the agent runs; gate fires next.
    assert types[0] == "session"
    assert "run_start" in types
    assert "error" in types

    err = next(e for e in events if e.get("event") == "error")
    # The DeviceAgent error frame carries ``error_kind`` and ``message``;
    # ``_sse_event`` re-keys ``type`` → ``event`` but leaves the rest intact.
    assert err.get("error_kind") == "provider_no_mcp_support"
    assert "deepseek" in (err.get("message") or "")

    # SDK was never invoked.
    assert sdk_calls["n"] == 0


def test_chat_nonstream_returns_empty_answer_when_provider_no_mcp_support(
    client, deepseek_no_mcp, monkeypatch
):
    """Non-streaming ``POST /chat`` still returns 200 (the error is in the
    event trace) but the answer is empty when the gate fires."""

    async def _should_not_be_called(**kwargs):  # noqa: ARG001
        if False:
            yield

    monkeypatch.setattr("claude_agent_sdk.query", _should_not_be_called)

    resp = client.post(
        "/chat",
        json={
            "message": "hello",
            "session_id": "sess-ds-nonstream",
            "agent_type": "device",
            "target_device_id": "dev-x",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The provider gate emits an ``error`` event and returns without producing
    # a final text; the chat response surfaces this as an empty ``answer``.
    assert body.get("answer", "") == ""
