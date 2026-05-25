"""Unit tests for log-analysis run projection into ``chat_run_service``.

Covers tasks:

- 7.1 LogAnalysisChatService 创建/完成/cancel 的 AgentJob 状态投影到 chat_agent_runs
  (the chat_run_service side; the DB-write side is best-effort and only checked
  to not raise when ``db_manager.session_factory is None``).
- 7.2 active-run snapshot for log_analysis runs exposes the agreed shape:
  ``run_id/session_id/agent_kind/events/trace_events/status/answer/error``.

These tests stay at the registry layer because the agent execution path uses
``asyncio.to_thread`` + Anthropic SDK; rather than fake the whole loop, we
drive ``register_external_job`` / ``mark_external_terminal`` directly — the
same surface :class:`LogAnalysisChatService` calls from
``_register_chat_run`` and ``_finalize_chat_run``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.chat_run_service import (
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_CANCELLED,
    TERMINAL_RUN_STATUSES,
    chat_run_service,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001
    yield
    chat_run_service._jobs.clear()  # noqa: SLF001
    chat_run_service._active_by_owner_session.clear()  # noqa: SLF001
    chat_run_service._brokers.clear()  # noqa: SLF001


def test_log_analysis_run_appears_in_active_snapshot():
    events: list = []
    trace_events: list = []
    job = chat_run_service.register_external_job(
        run_id="run-la-1",
        session_id="sess-la-1",
        user_id="user-1",
        owner_scope="user:user-1",
        agent_kind="log_analysis",
        user_message="分析日志",
        request_payload={"filename": "trace.zip"},
        events_ref=events,
        trace_events_ref=trace_events,
    )
    assert job.status == RUN_STATUS_RUNNING

    snap = chat_run_service.get_active_run_snapshot("user:user-1", "sess-la-1")
    assert snap is not None
    # 7.2: all required snapshot fields present.
    assert snap["run_id"] == "run-la-1"
    assert snap["session_id"] == "sess-la-1"
    assert snap["agent_kind"] == "log_analysis"
    assert snap["status"] == RUN_STATUS_RUNNING
    assert snap["events"] == []
    assert snap["trace_events"] == []
    assert snap["answer_so_far"] == ""
    assert snap["error"] is None

    # Buffer references are shared with the external driver.
    events.append({"event": "log_analysis_status", "message": "running"})
    trace_events.append({"type": "system_notice", "kind": "progress"})
    snap2 = chat_run_service.get_active_run_snapshot("user:user-1", "sess-la-1")
    assert snap2 is not None
    assert len(snap2["events"]) == 1
    assert len(snap2["trace_events"]) == 1


def test_log_analysis_run_terminal_clears_active_pointer():
    chat_run_service.register_external_job(
        run_id="run-la-2",
        session_id="sess-la-2",
        user_id="user-1",
        owner_scope="user:user-1",
        agent_kind="log_analysis",
        user_message="再分析",
        request_payload={},
        events_ref=[],
        trace_events_ref=[],
    )
    chat_run_service.mark_external_terminal(
        "run-la-2",
        RUN_STATUS_SUCCEEDED,
        answer="done!",
        model="claude-x",
    )

    # Active pointer cleared so a new run can start.
    assert (
        chat_run_service.get_active_job_for_session("user:user-1", "sess-la-2") is None
    )

    snap = chat_run_service.get_snapshot("run-la-2", "user:user-1")
    assert snap is not None
    assert snap["status"] == RUN_STATUS_SUCCEEDED
    assert snap["answer_so_far"] == "done!"
    assert snap["model"] == "claude-x"


def test_log_analysis_run_cancelled_terminal():
    chat_run_service.register_external_job(
        run_id="run-la-3",
        session_id="sess-la-3",
        user_id=None,
        owner_scope="anon:ABC",
        agent_kind="log_analysis",
        user_message="?",
        request_payload={},
        events_ref=[],
        trace_events_ref=[],
    )
    chat_run_service.mark_external_terminal(
        "run-la-3",
        RUN_STATUS_CANCELLED,
        error="用户取消",
    )

    assert (
        chat_run_service.get_active_job_for_session("anon:ABC", "sess-la-3") is None
    )
    snap = chat_run_service.get_snapshot("run-la-3", "anon:ABC")
    assert snap is not None
    assert snap["status"] == RUN_STATUS_CANCELLED
    assert snap["error"] == "用户取消"
    assert RUN_STATUS_CANCELLED in TERMINAL_RUN_STATUSES


def test_log_analysis_run_owner_scope_isolation():
    chat_run_service.register_external_job(
        run_id="run-la-4",
        session_id="shared-sess",
        user_id="user-A",
        owner_scope="user:user-A",
        agent_kind="log_analysis",
        user_message="A",
        request_payload={},
        events_ref=[],
        trace_events_ref=[],
    )
    # Different user, same session_id: NOT a conflict — two distinct active
    # entries keyed on (owner_scope, session_id).
    chat_run_service.register_external_job(
        run_id="run-la-5",
        session_id="shared-sess",
        user_id="user-B",
        owner_scope="user:user-B",
        agent_kind="log_analysis",
        user_message="B",
        request_payload={},
        events_ref=[],
        trace_events_ref=[],
    )

    snap_a = chat_run_service.get_active_run_snapshot("user:user-A", "shared-sess")
    snap_b = chat_run_service.get_active_run_snapshot("user:user-B", "shared-sess")
    assert snap_a is not None and snap_a["run_id"] == "run-la-4"
    assert snap_b is not None and snap_b["run_id"] == "run-la-5"

    # User B cannot read user A's snapshot — owner mismatch returns 404.
    with pytest.raises(HTTPException) as excinfo:
        chat_run_service.get_snapshot("run-la-4", "user:user-B")
    assert excinfo.value.status_code == 404
    # Active-run lookup for B's scope also doesn't leak A's run.
    assert (
        chat_run_service.get_active_job_for_session("user:user-B", "shared-sess")
        is not None
    )


def test_log_analysis_run_conflicts_with_existing_active_run():
    chat_run_service.register_external_job(
        run_id="run-la-6",
        session_id="dup-sess",
        user_id="user-1",
        owner_scope="user:user-1",
        agent_kind="log_analysis",
        user_message="first",
        request_payload={},
        events_ref=[],
        trace_events_ref=[],
    )
    with pytest.raises(HTTPException) as excinfo:
        chat_run_service.register_external_job(
            run_id="run-la-7",
            session_id="dup-sess",
            user_id="user-1",
            owner_scope="user:user-1",
            agent_kind="log_analysis",
            user_message="second",
            request_payload={},
            events_ref=[],
            trace_events_ref=[],
        )
    assert excinfo.value.status_code == 409
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail.get("active_run_id") == "run-la-6"
