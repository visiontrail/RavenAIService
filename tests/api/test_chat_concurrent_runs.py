"""Integration test for task 10.2 — concurrent chat agent runs across sessions.

Two distinct sessions kicked off in parallel must:

1. Both finish in roughly *one* fake-agent duration, not two (i.e. they run
   concurrently rather than serially behind the same event loop slot).
2. Each produce their own session-scoped events with no cross-talk: session A
   never observes session B's text, and vice-versa.

The Anthropic SDK is faked at the ``claude_agent_sdk.query`` boundary. Each
fake call sleeps for a fixed delay before yielding its assistant message, so
total elapsed time is the actual signal that ChatRunService is running the
two jobs in parallel.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_chat as ai_chat_api
from app.api.users import get_optional_user
from app.models.database import get_db
from app.services.chat_run_service import chat_run_service


# ────────────────────────── Fake SDK plumbing ──────────────────────


_FAKE_AGENT_DELAY_SECONDS = 0.6


class _FakeUsage:
    input_tokens = 5
    output_tokens = 7
    cache_read_input_tokens = 0


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


def _delayed_query_factory(answer: str):
    """Return a fake ``claude_agent_sdk.query`` that sleeps then yields ``answer``.

    The sleep ensures two concurrent calls overlap on the event loop; total
    elapsed time would be 2× the delay if execution were serialized.
    """

    async def _q(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        await asyncio.sleep(_FAKE_AGENT_DELAY_SECONDS)
        yield _AssistantMessage([_TextBlock(answer)])
        yield _ResultMessage(answer)

    return _q


class _FakeDevice:
    def __init__(self) -> None:
        self.capabilities = {"protocol_version": 2, "mcp": {"servers": []}}


# ────────────────────────── Fixtures ────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    application.dependency_overrides[get_optional_user] = lambda: None

    async def _no_db():
        yield None

    application.dependency_overrides[get_db] = _no_db
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def anthropic_ok(monkeypatch):
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


@pytest.fixture
def clean_registry():
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001
    yield
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001


# ────────────────────────── Helpers ─────────────────────────────────


def _parse_sse_events(body: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith("data:"):
            continue
        payload = chunk[len("data:"):].strip()
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return out


def _post_chat_stream(client: TestClient, session_id: str, scope_token: str, answer: str) -> Dict[str, Any]:
    """Send a POST /chat/stream request and return ``{events, elapsed}``."""
    start = time.monotonic()
    resp = client.post(
        "/chat/stream",
        json={
            "message": f"please return {answer}",
            "session_id": session_id,
            "target_device_id": "dev-x",
            "remember": False,
        },
        headers={"X-Client-Scope": scope_token},
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 200, resp.text
    return {"events": _parse_sse_events(resp.text), "elapsed": elapsed}


# ───────────────────────────── Test ────────────────────────────────


def test_two_sessions_run_concurrently_without_event_crosstalk(
    client, anthropic_ok, fake_device, clean_registry, monkeypatch
):
    """Two independent sessions must complete concurrently and stay isolated.

    The fake DeviceAgent sleeps for ``_FAKE_AGENT_DELAY_SECONDS`` before
    answering. If ChatRunService correctly schedules each job on its own
    asyncio task, two concurrent client requests finish in roughly one delay
    plus overhead. If execution were serialized, the slower thread would wait
    for the first job to finish, doubling total elapsed time.
    """

    monkeypatch.setattr(
        "claude_agent_sdk.query", _delayed_query_factory("ANSWER_FOR_SESSION_A")
    )

    results: Dict[str, Dict[str, Any]] = {}
    errors: Dict[str, Exception] = {}

    def _run_a():
        try:
            results["A"] = _post_chat_stream(
                client, session_id="sess-A", scope_token="scope-A", answer="ANSWER_FOR_SESSION_A"
            )
        except Exception as exc:  # noqa: BLE001
            errors["A"] = exc

    def _run_b():
        try:
            results["B"] = _post_chat_stream(
                client, session_id="sess-B", scope_token="scope-B", answer="ANSWER_FOR_SESSION_B"
            )
        except Exception as exc:  # noqa: BLE001
            errors["B"] = exc

    # Stagger to ~0 so both arrive on the server before either has finished.
    t_a = threading.Thread(target=_run_a, daemon=True)
    t_b = threading.Thread(target=_run_b, daemon=True)

    wall_start = time.monotonic()
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)
    wall_elapsed = time.monotonic() - wall_start

    assert not errors, f"thread errors: {errors}"
    assert "A" in results and "B" in results

    # 1. Both finished — and wall-clock elapsed proves concurrency.
    # A serial execution would be > 2 * delay. We pad generously to absorb
    # request setup + SSE buffer flush, but keep the bound tight enough that
    # a truly serialized implementation would fail.
    serial_lower_bound = _FAKE_AGENT_DELAY_SECONDS * 1.8
    assert wall_elapsed < serial_lower_bound, (
        f"two concurrent runs took {wall_elapsed:.2f}s; "
        f"a serial execution would be >= {serial_lower_bound:.2f}s — "
        "ChatRunService is not actually running jobs in parallel."
    )

    # 2. Event isolation — each session sees only its own session_id, run_id,
    # and final answer.
    events_a = results["A"]["events"]
    events_b = results["B"]["events"]
    assert events_a and events_b

    done_a = next((e for e in events_a if (e.get("event") or e.get("type")) == "done"), None)
    done_b = next((e for e in events_b if (e.get("event") or e.get("type")) == "done"), None)
    assert done_a is not None, f"session A missing done event: {events_a}"
    assert done_b is not None, f"session B missing done event: {events_b}"
    assert done_a["session_id"] == "sess-A"
    assert done_b["session_id"] == "sess-B"
    # run_id must be distinct so caches/brokers cannot collide.
    assert done_a["run_id"] != done_b["run_id"]

    # 3. No cross-session leakage in any per-event payload.
    for ev in events_a:
        sid = ev.get("session_id")
        if sid is not None:
            assert sid == "sess-A", f"session A saw foreign session_id: {ev}"
    for ev in events_b:
        sid = ev.get("session_id")
        if sid is not None:
            assert sid == "sess-B", f"session B saw foreign session_id: {ev}"
