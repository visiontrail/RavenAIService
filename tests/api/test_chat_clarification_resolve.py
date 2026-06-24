"""Integration tests for ``POST /chat/clarifications/{request_id}/resolve``.

Mirrors the permission-resolve endpoint contract for AskUserQuestion answers:

- 200 forwards ``{"answers": [...]}`` into the matching broker future.
- 400 when answers are empty or a required question is left blank.
- 404 for unknown / already-resolved request_id.
- owner_scope isolation: a caller can only resolve a run they own.
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


_CLIENT_SCOPE_TOKEN = "clarify-scope-fixed"
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
) -> tuple[str, PermissionBroker, "asyncio.Future[Dict[str, Any]]"]:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run_id = str(uuid.uuid4())
    broker = PermissionBroker()
    future = broker.open_clarification(request_id)
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
    return {"X-Client-Scope": _CLIENT_SCOPE_TOKEN}


def test_resolve_answers_forwards_to_broker(client, clean_registry):
    run_id, broker, future = _open_pending("sess-1", "req-1")
    resp = client.post(
        "/chat/clarifications/req-1/resolve",
        json={
            "run_id": run_id,
            "answers": [
                {"question_index": 0, "selected_labels": ["nginx"]},
                {"question_index": 1, "selected_labels": [], "custom_text": "先看日志"},
            ],
        },
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["request_id"] == "req-1"
    assert future.done()
    answers = future.result()["answers"]
    assert answers[0]["selected_labels"] == ["nginx"]
    assert answers[1]["custom_text"] == "先看日志"
    assert not broker.has("req-1")


def test_resolve_without_run_id_scans_by_owner(client, clean_registry):
    _, _, future = _open_pending("sess-scan", "req-scan")
    resp = client.post(
        "/chat/clarifications/req-scan/resolve",
        json={"answers": [{"question_index": 0, "selected_labels": ["a"]}]},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert future.done()


def test_resolve_empty_answers_returns_400(client, clean_registry):
    run_id, _, future = _open_pending("sess-empty", "req-empty")
    resp = client.post(
        "/chat/clarifications/req-empty/resolve",
        json={"run_id": run_id, "answers": []},
        headers=_headers(),
    )
    assert resp.status_code == 400
    assert not future.done()


def test_resolve_blank_answer_returns_400(client, clean_registry):
    run_id, _, future = _open_pending("sess-blank", "req-blank")
    resp = client.post(
        "/chat/clarifications/req-blank/resolve",
        json={
            "run_id": run_id,
            "answers": [{"question_index": 0, "selected_labels": [], "custom_text": "  "}],
        },
        headers=_headers(),
    )
    assert resp.status_code == 400
    assert not future.done()


def test_resolve_unknown_returns_404(client, clean_registry):
    resp = client.post(
        "/chat/clarifications/missing/resolve",
        json={"answers": [{"question_index": 0, "selected_labels": ["a"]}]},
        headers=_headers(),
    )
    assert resp.status_code == 404


def test_resolve_rejects_other_owner_scope(client, clean_registry):
    run_id, _, future = _open_pending("sess-iso", "req-iso", owner_scope="anon:user-a")
    resp = client.post(
        "/chat/clarifications/req-iso/resolve",
        json={"run_id": run_id, "answers": [{"question_index": 0, "selected_labels": ["a"]}]},
        headers={"X-Client-Scope": "user-b"},
    )
    assert resp.status_code == 404
    assert not future.done()
