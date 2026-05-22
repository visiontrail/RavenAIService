"""Integration tests for ``POST /chat/permissions/{request_id}/resolve``.

The endpoint resolves a HITL decision raised by ``DeviceAgent.can_use_tool``.
It must:

- Reject malformed bodies (400).
- Return 404 when no broker holds the request_id.
- Forward ``{decision, updated_args?, message?}`` into the matching broker.
- Locate the broker even when the caller doesn't supply ``session_id``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.device_agent.permissions import PermissionBroker
from app.api import ai_chat as ai_chat_api
from app.api.users import get_optional_user
from app.services.ai_chat_service import ai_chat_service


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    # The endpoint pulls in ``get_optional_user`` which depends on a live DB.
    # Replace with an anonymous-user override so the test never touches DB.
    application.dependency_overrides[get_optional_user] = lambda: None
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_registry():
    """Reset the in-memory broker registry around every test."""
    ai_chat_service.permission_broker_registry.clear()
    yield ai_chat_service.permission_broker_registry
    ai_chat_service.permission_broker_registry.clear()


def _open_pending(
    session_id: str,
    request_id: str,
    *,
    tool_name: str = "mcp__device__sys__reboot",
    risk: str = "destructive",
) -> tuple[PermissionBroker, "asyncio.Future[Dict[str, Any]]"]:
    """Create a broker, register it, and open one pending future on it.

    Returns ``(broker, future)`` so callers can later assert what the
    endpoint pushed into the future.
    """
    # The endpoint runs broker.resolve() which uses asyncio.Future.set_result();
    # creating the future requires a running event loop. We materialise a
    # short-lived loop via asyncio.new_event_loop just for the open() call
    # and keep it set as the running loop for the duration of the test.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    broker = PermissionBroker()
    future = broker.open(request_id, tool_name=tool_name, risk=risk)  # type: ignore[arg-type]
    ai_chat_service.permission_broker_registry[session_id] = broker
    return broker, future


def test_resolve_allow_with_updated_args(client, clean_registry):
    session_id = "sess-1"
    request_id = "req-1"
    broker, future = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={
            "decision": "allow",
            "updated_args": {"force": True},
            "session_id": session_id,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == request_id
    assert body["decision"] == "allow"

    assert future.done()
    decision = future.result()
    assert decision["decision"] == "allow"
    assert decision["updated_args"] == {"force": True}

    # Once resolved, the broker no longer holds the request.
    assert not broker.has(request_id)


def test_resolve_deny_without_session_id_finds_broker(client, clean_registry):
    """When session_id is omitted, the endpoint scans the registry."""
    session_id = "sess-scan"
    request_id = "req-scan"
    _, future = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "deny", "message": "not safe"},
    )

    assert resp.status_code == 200
    assert future.done()
    decision = future.result()
    assert decision["decision"] == "deny"
    assert decision["message"] == "not safe"


def test_resolve_unknown_request_returns_404(client, clean_registry):
    # Empty registry → no broker can resolve.
    resp = client.post(
        "/chat/permissions/missing/resolve",
        json={"decision": "allow"},
    )
    assert resp.status_code == 404


def test_resolve_already_resolved_returns_404(client, clean_registry):
    session_id = "sess-twice"
    request_id = "req-twice"
    broker, _ = _open_pending(session_id, request_id)
    # Pre-resolve so the second call fails with 404.
    assert broker.resolve(request_id, {"decision": "deny", "reason": "preempted"})

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "allow", "session_id": session_id},
    )
    assert resp.status_code == 404


def test_resolve_bad_decision_returns_400(client, clean_registry):
    session_id = "sess-bad"
    request_id = "req-bad"
    _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "maybe", "session_id": session_id},
    )
    assert resp.status_code == 400


def test_resolve_updated_args_must_be_object(client, clean_registry):
    session_id = "sess-args"
    request_id = "req-args"
    _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={
            "decision": "allow",
            "updated_args": "not-an-object",
            "session_id": session_id,
        },
    )
    # Pydantic itself coerces this to 422 because ``updated_args: Optional[dict]``
    # rejects strings; if Pydantic ever loosens, our hand-rolled 400 takes over.
    assert resp.status_code in {400, 422}
