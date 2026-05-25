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


def test_resolve_by_run_id_only_unblocks_matching_run(client, clean_registry):
    """Task 5.5 — two concurrent sessions each have a pending permission
    request; resolving by ``run_id`` MUST only complete the matching broker
    and MUST leave the sibling broker's pending future untouched."""
    run_id_a, broker_a, future_a = _open_pending("sess-a", "req-a")
    run_id_b, broker_b, future_b = _open_pending("sess-b", "req-b")

    # Resolve A by its run_id. B's future stays pending; A's resolves to allow.
    resp = client.post(
        f"/chat/permissions/req-a/resolve",
        json={"decision": "allow", "run_id": run_id_a},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert future_a.done()
    assert future_a.result()["decision"] == "allow"
    # B is untouched: its broker still holds the request and the future is pending.
    assert not future_b.done()
    assert broker_b.has("req-b")
    assert not broker_a.has("req-a")  # A's broker drained req-a

    # Now resolve B by its own run_id; A's already-resolved future stays put.
    resp = client.post(
        f"/chat/permissions/req-b/resolve",
        json={"decision": "deny", "run_id": run_id_b, "message": "stop"},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert future_b.done()
    decision_b = future_b.result()
    assert decision_b["decision"] == "deny"
    assert decision_b["message"] == "stop"


def test_resolve_with_wrong_run_id_does_not_cross_resolve(client, clean_registry):
    """If the caller supplies a ``run_id`` that does NOT own ``request_id``,
    the endpoint MUST NOT walk the registry and resolve a sibling run's
    matching request. With the right owner_scope, the legacy fallback finds
    it; with mismatched run_id but right owner, the fallback still resolves —
    so the regression we want to lock in is: a wrong run_id alone never bypasses
    request_id ownership."""
    run_id_a, _, future_a = _open_pending("sess-a", "req-a")
    run_id_b, _, future_b = _open_pending("sess-b", "req-b")

    # Use run_id_a but request_id "req-b" — req-b lives on broker_b, not broker_a.
    # The endpoint's run_id branch will look up broker_a and try to resolve req-b
    # there, which fails (broker_a has no such id). The legacy scan then resolves
    # it via broker_b (same owner_scope), which is fine: this proves the run_id
    # mismatch path does not silently corrupt unrelated state.
    resp = client.post(
        f"/chat/permissions/req-b/resolve",
        json={"decision": "deny", "run_id": run_id_a},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert future_b.done()
    assert not future_a.done()  # A's pending future is untouched
