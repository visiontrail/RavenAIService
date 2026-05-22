"""Integration tests for ``POST /chat/permissions/{request_id}/resolve``.

The endpoint resolves a HITL decision raised by ``DeviceAgent.can_use_tool``.
It must:

- Reject malformed bodies (400).
- Return 404 when no broker holds the request_id.
- Forward ``{decision, updated_args?, message?}`` into the matching broker.
- Locate the broker even when the caller doesn't supply ``session_id``.
- Enforce owner_scope: a caller can only resolve permissions on a run they own.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.device_agent.permissions import PermissionBroker
from app.api import ai_chat as ai_chat_api
from app.api.users import get_optional_user
from app.services.chat_run_service import (
    ChatRunJob,
    RUN_STATUS_RUNNING,
    chat_run_service,
)


_CLIENT_SCOPE_TOKEN = "test-scope-fixed"
_OWNER_SCOPE = f"anon:{_CLIENT_SCOPE_TOKEN}"


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    application.dependency_overrides[get_optional_user] = lambda: None
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def clean_registry():
    """Reset the in-memory chat_run_service state around every test."""
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001
    yield
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001


def _open_pending(
    session_id: str,
    request_id: str,
    *,
    owner_scope: str = _OWNER_SCOPE,
    tool_name: str = "mcp__device__sys__reboot",
    risk: str = "destructive",
) -> tuple[str, PermissionBroker, "asyncio.Future[Dict[str, Any]]"]:
    """Create a ChatRunJob + matching PermissionBroker and register both.

    Returns ``(run_id, broker, future)`` so callers can verify what the
    endpoint pushed into the future.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run_id = str(uuid.uuid4())
    broker = PermissionBroker()
    future = broker.open(request_id, tool_name=tool_name, risk=risk)  # type: ignore[arg-type]
    job = ChatRunJob(
        run_id=run_id,
        session_id=session_id,
        user_id=None,
        owner_scope=owner_scope,
        agent_kind="device",
        status=RUN_STATUS_RUNNING,
        started_at=time.monotonic(),
        user_message="t",
        request_payload={},
    )
    chat_run_service._jobs[run_id] = job  # noqa: SLF001
    chat_run_service._active_by_owner_session[(owner_scope, session_id)] = run_id  # noqa: SLF001
    chat_run_service._brokers[run_id] = broker  # noqa: SLF001
    return run_id, broker, future


def _headers() -> dict[str, str]:
    """Pin the anonymous owner_scope so test requests match the registered job."""
    return {"X-Client-Scope": _CLIENT_SCOPE_TOKEN}


def test_resolve_allow_with_updated_args(client, clean_registry):
    session_id = "sess-1"
    request_id = "req-1"
    run_id, broker, future = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={
            "decision": "allow",
            "updated_args": {"force": True},
            "run_id": run_id,
        },
        headers=_headers(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == request_id
    assert body["decision"] == "allow"

    assert future.done()
    decision = future.result()
    assert decision["decision"] == "allow"
    assert decision["updated_args"] == {"force": True}
    assert not broker.has(request_id)


def test_resolve_deny_without_session_id_finds_broker(client, clean_registry):
    """When neither run_id nor session_id is supplied, the endpoint scans by
    owner_scope-filtered legacy fallback."""
    session_id = "sess-scan"
    request_id = "req-scan"
    _, _, future = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "deny", "message": "not safe"},
        headers=_headers(),
    )

    assert resp.status_code == 200
    assert future.done()
    decision = future.result()
    assert decision["decision"] == "deny"
    assert decision["message"] == "not safe"


def test_resolve_unknown_request_returns_404(client, clean_registry):
    resp = client.post(
        "/chat/permissions/missing/resolve",
        json={"decision": "allow"},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_resolve_already_resolved_returns_404(client, clean_registry):
    session_id = "sess-twice"
    request_id = "req-twice"
    run_id, broker, _ = _open_pending(session_id, request_id)
    assert broker.resolve(request_id, {"decision": "deny", "reason": "preempted"})

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "allow", "run_id": run_id},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_resolve_bad_decision_returns_400(client, clean_registry):
    session_id = "sess-bad"
    request_id = "req-bad"
    run_id, _, _ = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "maybe", "run_id": run_id},
        headers=_headers(),
    )
    assert resp.status_code == 400


def test_resolve_updated_args_must_be_object(client, clean_registry):
    session_id = "sess-args"
    request_id = "req-args"
    run_id, _, _ = _open_pending(session_id, request_id)

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={
            "decision": "allow",
            "updated_args": "not-an-object",
            "run_id": run_id,
        },
        headers=_headers(),
    )
    assert resp.status_code in {400, 422}


def test_resolve_rejects_other_owner_scope(client, clean_registry):
    """User B's scope MUST NOT be able to resolve user A's pending permission."""
    session_id = "sess-iso"
    request_id = "req-iso"
    run_id, _, future = _open_pending(
        session_id, request_id, owner_scope="anon:user-a"
    )

    resp = client.post(
        f"/chat/permissions/{request_id}/resolve",
        json={"decision": "allow", "run_id": run_id},
        headers={"X-Client-Scope": "user-b"},
    )

    assert resp.status_code == 404
    assert not future.done()
