"""End-to-end concurrency tests for :class:`ChatRunService`.

Covers tasks:

- 3.7 两个 session 同时启动 fake DeviceAgent，各自产生事件并成功完成，
  事件和答案不串线。
- 3.8 订阅 A run 后主动断开，run 继续完成；重新订阅可 replay 全部事件与 done。
- 3.9 同一 session active 时再次发送新消息返回 409，并携带 active_run_id。
- 4.5 并发两个 run 时 workspace path 不同，且均位于各自 session/run 目录下。

The DeviceAgent class is monkey-patched to a controllable fake that yields a
fixed sequence of trace events; this lets us drive the entire ``ChatRunJob``
lifecycle without touching the Anthropic SDK or any device infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
from fastapi import HTTPException

from app.agents.log_analysis.trace import RUN_COMPLETE, RUN_START
from app.services.chat_run_service import (
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    TERMINAL_RUN_STATUSES,
    chat_run_service,
)


# ─────────────────────── Helpers / Fixtures ────────────────────────────


@pytest.fixture(autouse=True)
def _temp_workspace_root(monkeypatch):
    """Redirect device_agent workspace base to a temp dir so tests don't
    pollute the repo's ``temp/code_repos``."""
    scratch = tempfile.mkdtemp(prefix="chatrun-concurrent-")
    monkeypatch.setattr(
        "app.config.settings.code_repo_clone_base_dir", scratch, raising=False
    )
    yield scratch


@pytest.fixture(autouse=True)
def _reset_registry():
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001
    yield
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001


@pytest.fixture
def fake_device_agent(monkeypatch):
    """Replace ``DeviceAgent`` with a controllable fake.

    The fake reads its scripted events from a per-session list registered on
    the fixture object itself. Each call to ``run_stream`` looks up the event
    list by ``ctx.session_id``; tests can register distinct scripts for each
    session to assert that events don't cross-pollinate.
    """
    scripts: Dict[str, List[Dict[str, Any]]] = {}
    # When set, blocks the fake agent after RUN_START until set; lets tests
    # exercise the "run in progress while subscriber disconnects" path.
    gates: Dict[str, asyncio.Event] = {}

    class _FakeDeviceAgent:
        async def run_stream(self, ctx) -> AsyncIterator[Dict[str, Any]]:
            session_events = scripts.get(ctx.session_id, [])
            for ev in session_events:
                # If a gate exists for this session, wait once before yielding
                # the RUN_COMPLETE so subscribers can disconnect mid-flight.
                if (
                    ev.get("type") == RUN_COMPLETE
                    and ctx.session_id in gates
                ):
                    await gates[ctx.session_id].wait()
                yield ev

    monkeypatch.setattr(
        "app.agents.device_agent.agent.DeviceAgent", _FakeDeviceAgent
    )

    class _Handle:
        def __init__(self) -> None:
            self.scripts = scripts
            self.gates = gates

        def set_script(self, session_id: str, events: List[Dict[str, Any]]) -> None:
            self.scripts[session_id] = events

        def gate(self, session_id: str) -> asyncio.Event:
            ev = asyncio.Event()
            self.gates[session_id] = ev
            return ev

    return _Handle()


def _default_script(session_id: str, answer: str) -> List[Dict[str, Any]]:
    """Build a minimal RUN_START → RUN_COMPLETE event list."""
    return [
        {"type": RUN_START, "session_id": session_id, "model": "claude-sonnet-4-6"},
        {"type": RUN_COMPLETE, "session_id": session_id, "final_text": answer},
    ]


async def _wait_for_terminal(job, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.status in TERMINAL_RUN_STATUSES:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"job {job.run_id} did not terminate within {timeout}s")


async def _drain_subscribe(run_id: str, owner_scope: str) -> List[Dict[str, Any]]:
    """Consume the SSE stream for a run until the ``done`` frame, parsing
    each ``data: ...`` line back into a dict."""
    events: List[Dict[str, Any]] = []
    async for raw in chat_run_service.subscribe(run_id, owner_scope=owner_scope):
        text = raw.strip()
        if not text.startswith("data:"):
            continue
        payload = text[len("data:"):].strip()
        try:
            ev = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(ev)
        if ev.get("event") == "done":
            break
    return events


async def _start_run(
    *,
    owner_scope: str,
    session_id: str,
    user_message: str,
    target_device_id: str = "dev-1",
):
    """Start a DeviceAgent run with no DB / no user (anonymous flow).

    Returns the ``ChatRunJob``.
    """
    return await chat_run_service.start_device_run(
        db=None,  # anonymous path skips DB
        user=None,
        owner_scope=owner_scope,
        session_id=session_id,
        user_message=user_message,
        target_device_id=target_device_id,
        target_device_name=None,
        history=[],
        system_prompt_override=None,
        remember=False,
    )


# ─────────────────────── Task 3.7 — concurrency ────────────────────────


@pytest.mark.asyncio
async def test_concurrent_runs_in_different_sessions_dont_cross_streams(
    fake_device_agent,
):
    """Two sessions running in parallel must each receive ONLY their own
    events; ``run_id`` / ``session_id`` are part of every emitted frame so
    we can verify per-frame attribution."""
    fake_device_agent.set_script(
        "sess-A", _default_script("sess-A", "answer for A")
    )
    fake_device_agent.set_script(
        "sess-B", _default_script("sess-B", "answer for B")
    )

    owner = "anon:concurrent-user"
    job_a = await _start_run(
        owner_scope=owner, session_id="sess-A", user_message="hi A"
    )
    job_b = await _start_run(
        owner_scope=owner, session_id="sess-B", user_message="hi B"
    )

    # Subscribe to both concurrently; gather their frames in parallel.
    events_a, events_b = await asyncio.gather(
        _drain_subscribe(job_a.run_id, owner),
        _drain_subscribe(job_b.run_id, owner),
    )

    # Every frame from A's subscription carries A's run_id; same for B.
    a_run_ids = {ev.get("run_id") for ev in events_a if ev.get("run_id")}
    b_run_ids = {ev.get("run_id") for ev in events_b if ev.get("run_id")}
    assert a_run_ids == {job_a.run_id}
    assert b_run_ids == {job_b.run_id}

    a_sessions = {ev.get("session_id") for ev in events_a if ev.get("session_id")}
    b_sessions = {ev.get("session_id") for ev in events_b if ev.get("session_id")}
    assert a_sessions == {"sess-A"}
    assert b_sessions == {"sess-B"}

    # Final answers must end up on each job — not swapped.
    assert job_a.status == RUN_STATUS_SUCCEEDED
    assert job_b.status == RUN_STATUS_SUCCEEDED
    assert job_a.answer == "answer for A"
    assert job_b.answer == "answer for B"

    # The terminal ``done`` frame should also carry the per-run answer.
    done_a = next(ev for ev in events_a if ev.get("event") == "done")
    done_b = next(ev for ev in events_b if ev.get("event") == "done")
    assert done_a["answer"] == "answer for A"
    assert done_b["answer"] == "answer for B"
    assert done_a["run_id"] == job_a.run_id
    assert done_b["run_id"] == job_b.run_id


# ─────────────────────── Task 3.8 — replay ─────────────────────────────


@pytest.mark.asyncio
async def test_subscriber_disconnect_does_not_cancel_run_and_resubscribe_replays(
    fake_device_agent,
):
    """Subscribe to A, abandon the subscription before it completes, and
    verify (a) the run still finishes in the background, (b) a fresh
    subscription gets the full replay including ``run_start`` and ``done``."""
    fake_device_agent.set_script(
        "sess-R", _default_script("sess-R", "final R")
    )
    gate = fake_device_agent.gate("sess-R")

    owner = "anon:replay-user"
    job = await _start_run(
        owner_scope=owner, session_id="sess-R", user_message="hi"
    )

    # First subscriber: walk a few events, then abandon (close the async gen).
    first_iter = chat_run_service.subscribe(job.run_id, owner_scope=owner)
    seen_first: List[Dict[str, Any]] = []
    # Pull at least the run_start_pending + run_start frames; with the gate
    # closed the fake will block before emitting RUN_COMPLETE.
    for _ in range(4):
        try:
            raw = await asyncio.wait_for(first_iter.__anext__(), timeout=1.0)
        except (StopAsyncIteration, asyncio.TimeoutError):
            break
        text = raw.strip()
        if text.startswith("data:"):
            payload = text[len("data:"):].strip()
            try:
                seen_first.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
        if any(ev.get("event") == "run_start" for ev in seen_first):
            break

    # Subscriber drops off. The underlying job MUST still be running.
    await first_iter.aclose()
    assert job.status == RUN_STATUS_RUNNING

    # Release the agent — the run finishes in the background.
    gate.set()
    await _wait_for_terminal(job)
    assert job.status == RUN_STATUS_SUCCEEDED

    # Re-subscribe: the full event history must replay including done.
    events_after = await _drain_subscribe(job.run_id, owner)
    event_kinds = [ev.get("event") for ev in events_after]
    # run_start_pending + run_start + run_complete + done are all expected.
    assert "run_start" in event_kinds
    assert "run_complete" in event_kinds
    assert event_kinds[-1] == "done"
    done = events_after[-1]
    assert done["status"] == RUN_STATUS_SUCCEEDED
    assert done["answer"] == "final R"
    assert done["run_id"] == job.run_id


# ─────────────────────── Task 3.9 — 409 on duplicate ───────────────────


@pytest.mark.asyncio
async def test_start_run_when_session_already_active_returns_409_with_active_run_id(
    fake_device_agent,
):
    """While a session has an active run, ``start_device_run`` MUST raise
    HTTP 409 and surface the existing ``active_run_id`` so the frontend can
    switch to subscribe mode rather than retrying."""
    fake_device_agent.set_script(
        "sess-X", _default_script("sess-X", "answer X")
    )
    gate = fake_device_agent.gate("sess-X")

    owner = "anon:409-user"
    first = await _start_run(
        owner_scope=owner, session_id="sess-X", user_message="hi"
    )
    assert first.status == RUN_STATUS_RUNNING

    with pytest.raises(HTTPException) as exc_info:
        await _start_run(
            owner_scope=owner, session_id="sess-X", user_message="hi again"
        )

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("active_run_id") == first.run_id

    # Release the first run so the fixture's task cleanup is clean.
    gate.set()
    await _wait_for_terminal(first)


# ─────────────────────── Task 4.5 — workspace isolation ────────────────


@pytest.mark.asyncio
async def test_concurrent_runs_get_distinct_workspace_paths_under_session_run_dirs(
    fake_device_agent, _temp_workspace_root
):
    """Each ``(owner_scope, session_id, run_id)`` MUST get its own workspace
    directory; running two runs concurrently MUST produce two distinct paths
    that both live under the configured base."""
    fake_device_agent.set_script(
        "sess-W1", _default_script("sess-W1", "answer W1")
    )
    fake_device_agent.set_script(
        "sess-W2", _default_script("sess-W2", "answer W2")
    )

    owner = "anon:ws-user"
    job1 = await _start_run(
        owner_scope=owner, session_id="sess-W1", user_message="hi"
    )
    job2 = await _start_run(
        owner_scope=owner, session_id="sess-W2", user_message="hi"
    )

    assert job1.workspace_path
    assert job2.workspace_path
    assert job1.workspace_path != job2.workspace_path

    p1 = Path(job1.workspace_path)
    p2 = Path(job2.workspace_path)

    # Both paths exist on disk under the temp base.
    assert p1.exists() and p1.is_dir()
    assert p2.exists() and p2.is_dir()

    # Path layout: <base>/device_agent/<owner>/<session>/<run>/.
    assert p1.name == job1.run_id[:64]  # _sanitize truncates to 64 chars
    assert p2.name == job2.run_id[:64]
    assert "sess-W1" in p1.parts
    assert "sess-W2" in p2.parts
    # The owner segment is shared so two distinct sessions land in different
    # subtrees but the same owner scope.
    assert p1.parts.index("sess-W1") == p2.parts.index("sess-W2")

    # Drain both runs to terminal to avoid stranded background tasks.
    await asyncio.gather(
        _drain_subscribe(job1.run_id, owner),
        _drain_subscribe(job2.run_id, owner),
    )
    assert job1.status == RUN_STATUS_SUCCEEDED
    assert job2.status == RUN_STATUS_SUCCEEDED
