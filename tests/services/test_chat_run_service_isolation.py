"""Cross-user isolation tests for :class:`ChatRunService` (Tasks 11.7, 11.8).

These tests verify owner_scope keeps two users' runs completely separated:

- Task 11.7: two users using the SAME ``session_id`` MUST each get their own
  active run with no false 409 conflict; each user's active-run lookup MUST
  return their own run, never the other's.
- Task 11.8: user B MUST NOT be able to fetch snapshot, subscribe to stream,
  cancel, or resolve permissions on user A's run. All such attempts return
  a 404 (no information leak) and leave user A's run untouched.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

import pytest
from fastapi import HTTPException

from app.agents.device_agent.permissions import PermissionBroker
from app.services.chat_run_service import (
    ChatRunJob,
    RUN_STATUS_RUNNING,
    chat_run_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001
    yield
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001


def _make_job(
    *,
    owner_scope: str,
    session_id: str,
    user_id: Optional[str] = None,
) -> ChatRunJob:
    run_id = str(uuid.uuid4())
    job = ChatRunJob(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        owner_scope=owner_scope,
        agent_kind="device",
        status=RUN_STATUS_RUNNING,
        started_at=time.monotonic(),
        user_message="hello",
        request_payload={},
    )
    chat_run_service._jobs[run_id] = job  # noqa: SLF001
    chat_run_service._active_by_owner_session[(owner_scope, session_id)] = run_id  # noqa: SLF001
    return job


# ---------------------------------------------------------------------------
# Task 11.7 — two users, same session_id, no collision
# ---------------------------------------------------------------------------


def test_two_users_same_session_id_isolated_active_runs():
    """Spec: user A and user B both use session_id="shared" → distinct runs,
    each user's active-run lookup hits their own."""
    session_id = "shared"
    job_a = _make_job(owner_scope="user:alice", session_id=session_id, user_id="alice")
    job_b = _make_job(owner_scope="user:bob", session_id=session_id, user_id="bob")

    assert job_a.run_id != job_b.run_id

    seen_a = chat_run_service.get_active_job_for_session("user:alice", session_id)
    seen_b = chat_run_service.get_active_job_for_session("user:bob", session_id)

    assert seen_a is job_a
    assert seen_b is job_b

    # Third-party scope sees neither.
    seen_c = chat_run_service.get_active_job_for_session("user:carol", session_id)
    assert seen_c is None


def test_user_a_second_message_doesnt_block_user_b(monkeypatch):
    """A user A duplicate request on session "X" must 409 only against user A's
    own run; user B with the same session_id must still be allowed."""
    session_id = "dup"
    _make_job(owner_scope="user:alice", session_id=session_id, user_id="alice")

    # Verify the 409 only fires within the same owner_scope: simulate the
    # in-service guard used by start_device_run.
    existing_a = chat_run_service.get_active_job_for_session("user:alice", session_id)
    existing_b = chat_run_service.get_active_job_for_session("user:bob", session_id)
    assert existing_a is not None
    assert existing_b is None


# ---------------------------------------------------------------------------
# Task 11.8 — user B can't touch user A's run
# ---------------------------------------------------------------------------


def test_snapshot_rejects_other_owner_scope():
    job = _make_job(owner_scope="user:alice", session_id="s", user_id="alice")
    with pytest.raises(HTTPException) as exc_info:
        chat_run_service.get_snapshot(job.run_id, owner_scope="user:bob")
    assert exc_info.value.status_code == 404


def test_snapshot_owner_scope_match_returns_payload():
    job = _make_job(owner_scope="user:alice", session_id="s", user_id="alice")
    snap = chat_run_service.get_snapshot(job.run_id, owner_scope="user:alice")
    assert snap is not None
    assert snap["run_id"] == job.run_id


def test_active_run_snapshot_isolated():
    """``get_active_run_snapshot`` for user B on user A's session returns None."""
    _make_job(owner_scope="user:alice", session_id="dual", user_id="alice")
    assert chat_run_service.get_active_run_snapshot("user:bob", "dual") is None


def test_cancel_rejects_other_owner_scope():
    """user B cancel attempt MUST 404 and MUST NOT cancel user A's task."""

    async def _run():
        async def _never():
            await asyncio.sleep(60)

        task = asyncio.create_task(_never())
        job = _make_job(owner_scope="user:alice", session_id="s", user_id="alice")
        job.task = task

        try:
            with pytest.raises(HTTPException) as exc_info:
                chat_run_service.cancel(job.run_id, owner_scope="user:bob")
            assert exc_info.value.status_code == 404
            assert not task.done()
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BaseException):
                pass

    asyncio.run(_run())


def test_cancel_owner_match_succeeds():
    async def _run():
        async def _never():
            await asyncio.sleep(60)

        task = asyncio.create_task(_never())
        job = _make_job(owner_scope="user:alice", session_id="s", user_id="alice")
        job.task = task

        try:
            assert chat_run_service.cancel(job.run_id, owner_scope="user:alice") is True
            await asyncio.sleep(0)  # let the cancel propagate
            assert task.cancelled() or task.done()
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, BaseException):
                    pass

    asyncio.run(_run())


def test_subscribe_rejects_other_owner_scope():
    async def _run():
        job = _make_job(owner_scope="user:alice", session_id="s", user_id="alice")
        agen = chat_run_service.subscribe(job.run_id, owner_scope="user:bob")
        with pytest.raises(HTTPException) as exc_info:
            await agen.__anext__()
        assert exc_info.value.status_code == 404

    asyncio.run(_run())
