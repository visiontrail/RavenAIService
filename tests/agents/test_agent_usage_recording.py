"""Agent/service usage-recording tests using fake SDK messages and results.

Covers task 7.4 (openspec/changes/add-system-user-metrics/tasks.md):

    Add Agent/service tests for GeneralAgent, DeviceAgent, log analysis, project
    expert, package search, and title generator usage recording using fake SDK
    messages/results.

Two layers are exercised:

1. The shared SDK usage accumulator (``app/agents/usage.py``) that every Agent
   loop feeds raw SDK ``usage`` payloads into — object-attribute form, dict
   form, cache-field aliases, ``None`` safety, and alias de-duplication.

2. The terminal-result → ``MetricEvent`` mapping (``record_agent_run_usage``)
   that ChatRunService / LogAnalysisChatService / ProjectExpertChatService /
   package search all funnel through. We drive it with the exact terminal-result
   shapes those agents emit (``token_usage``/``model``/``provider``/
   ``duration_seconds``/``error_kind``) and assert the persisted row.

The accumulator tests are pure; the recording tests use a throwaway SQLite DB
(same pattern as ``tests/services/test_metrics_service_db.py``).
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from sqlalchemy import select

from app.agents.usage import accumulate_usage, new_token_usage
from app.config import settings
from app.models.database import Base, db_manager
from app.models.metrics import MetricEvent
from app.services import metrics_service as ms


# ==================== 3.1 shared usage accumulator ====================
#
# Fake SDK messages: real Claude Agent SDK assistant/result messages carry a
# ``usage`` attribute that may be an object with token attributes or a plain
# dict, with cache fields named differently across SDK versions.


class _FakeUsage:
    """Object-attribute ``usage`` payload like newer SDK message objects."""

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


class _FakeMessage:
    """A fake SDK message carrying a ``usage`` payload (or ``None``)."""

    def __init__(self, usage=None):
        self.usage = usage


def _drive_accumulator(messages):
    """Mimic an Agent loop: accumulate ``usage`` from each streamed message."""
    token_usage = new_token_usage()
    for message in messages:
        accumulate_usage(getattr(message, "usage", None), token_usage)
    return token_usage


def test_accumulator_sums_object_usage_across_messages():
    messages = [
        _FakeMessage(_FakeUsage(input_tokens=100, output_tokens=10)),
        _FakeMessage(_FakeUsage(input_tokens=5, output_tokens=40)),
        _FakeMessage(None),  # streamed deltas without usage are ignored
    ]
    assert _drive_accumulator(messages) == {
        "input_tokens": 105,
        "output_tokens": 50,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_accumulator_maps_cache_field_aliases():
    # SDK exposes cache fields as cache_read_input_tokens / cache_creation_input_tokens.
    messages = [
        _FakeMessage(
            _FakeUsage(
                input_tokens=20,
                output_tokens=8,
                cache_read_input_tokens=200,
                cache_creation_input_tokens=64,
            )
        )
    ]
    assert _drive_accumulator(messages) == {
        "input_tokens": 20,
        "output_tokens": 8,
        "cache_read_tokens": 200,
        "cache_write_tokens": 64,
    }


def test_accumulator_handles_dict_usage_payload():
    messages = [_FakeMessage({"prompt_tokens": 12, "completion_tokens": 3})]
    assert _drive_accumulator(messages) == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_accumulator_does_not_double_count_alias_and_canonical():
    # If both prompt_tokens and input_tokens are present on one payload, the
    # canonical field is written at most once.
    usage = _FakeUsage(input_tokens=10, prompt_tokens=10, output_tokens=5)
    token_usage = new_token_usage()
    accumulate_usage(usage, token_usage)
    assert token_usage["input_tokens"] == 10


def test_accumulator_ignores_negative_and_non_numeric():
    usage = {"input_tokens": -50, "output_tokens": "garbage", "cache_read_tokens": 7}
    token_usage = new_token_usage()
    accumulate_usage(usage, token_usage)
    assert token_usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 7,
        "cache_write_tokens": 0,
    }


# ==================== DB fixture for recording assertions ====================


@pytest.fixture
def metrics_db():
    """Point ``db_manager`` at a fresh temp SQLite file with only metric_events."""
    fd, path = tempfile.mkstemp(prefix="agent-usage-db-", suffix=".sqlite")
    os.close(fd)

    prev_url = settings.database_url
    prev_engine = db_manager.engine
    prev_factory = db_manager.session_factory

    settings.database_url = f"sqlite+aiosqlite:///{path}"
    db_manager.initialize()

    async def _create() -> None:
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[MetricEvent.__table__])

    asyncio.run(_create())
    try:
        yield
    finally:
        asyncio.run(db_manager.close())
        settings.database_url = prev_url
        db_manager.engine = prev_engine
        db_manager.session_factory = prev_factory
        try:
            os.remove(path)
        except OSError:
            pass


def _fetch_one(idempotency_key: str) -> MetricEvent:
    async def _run() -> MetricEvent:
        async with db_manager.session_factory() as session:
            return (
                await session.execute(
                    select(MetricEvent).where(
                        MetricEvent.idempotency_key == idempotency_key
                    )
                )
            ).scalar_one()

    return asyncio.run(_run())


# ==================== 7.4 terminal-result → MetricEvent mapping ====================


def test_general_agent_run_complete_records_tokens_and_ownership(metrics_db):
    """A GeneralAgent ``run_complete`` event maps onto a succeeded MetricEvent."""
    result = {
        "type": "run_complete",
        "final_text": "answer",
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "token_usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        },
        "duration_seconds": 1.25,
    }

    asyncio.run(
        ms.record_agent_run_usage(
            source="general_agent",
            agent_kind="general",
            result=result,
            run_id="run-gen-1",
            terminal_status="succeeded",
            user_id="user-1",
            owner_scope="user",
            session_id="sess-1",
        )
    )

    row = _fetch_one("ai_usage:general_run:run-gen-1")
    assert row.event_type == "ai_usage"
    assert row.agent_kind == "general"
    assert row.provider == "anthropic"
    assert row.model == "claude-haiku-4-5"
    assert row.status == "succeeded"
    assert row.input_tokens == 120
    assert row.output_tokens == 30
    assert row.total_tokens == 150
    assert row.duration_ms == 1250  # 1.25s → ms
    assert row.user_id == "user-1"
    assert row.owner_scope == "user"
    assert row.session_id == "sess-1"


def test_device_agent_run_complete_records_device_kind(metrics_db):
    result = {
        "type": "run_complete",
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "token_usage": {"input_tokens": 80, "output_tokens": 200},
        "duration_seconds": 3,
    }

    asyncio.run(
        ms.record_agent_run_usage(
            source="device_agent",
            agent_kind="device",
            result=result,
            run_id="run-dev-1",
            terminal_status="succeeded",
            user_id="user-2",
        )
    )

    row = _fetch_one("ai_usage:device_run:run-dev-1")
    assert row.agent_kind == "device"
    assert row.total_tokens == 280
    assert row.duration_ms == 3000


def test_log_analysis_failure_still_records_invocation_with_error(metrics_db):
    """A failed terminal still produces an invocation row with error metadata (3.9)."""
    result = {
        "model": "claude-sonnet-4-6",
        "error_kind": "timeout",
        "duration_seconds": 30,
        # no token_usage available on a timeout
    }

    asyncio.run(
        ms.record_agent_run_usage(
            source="log_analysis_agent",
            agent_kind="log_analysis",
            result=result,
            run_id="run-log-1",
            terminal_status="succeeded",  # downgraded by the error_kind
            log_id="log-1",
        )
    )

    row = _fetch_one("ai_usage:log_analysis_run:run-log-1")
    # A clean "succeeded" carrying a timeout error_kind is downgraded to timeout.
    assert row.status == "timeout"
    assert row.error_kind == "timeout"
    assert row.total_tokens == 0
    assert row.log_id == "log-1"


def test_cancelled_terminal_sets_cancelled_error_kind(metrics_db):
    result = {"model": "m", "token_usage": {"input_tokens": 5}}

    asyncio.run(
        ms.record_agent_run_usage(
            source="general_agent",
            agent_kind="general",
            result=result,
            run_id="run-cancel-1",
            terminal_status="cancelled",
        )
    )

    row = _fetch_one("ai_usage:general_run:run-cancel-1")
    assert row.status == "cancelled"
    # error_kind is backfilled from a non-success terminal status.
    assert row.error_kind == "cancelled"


def test_project_expert_records_project_code_metadata(metrics_db):
    result = {
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "token_usage": {"input_tokens": 40, "output_tokens": 60},
        "duration_seconds": 2.0,
        "trace_summary": {"tool_call_count": 4},
    }

    asyncio.run(
        ms.record_agent_run_usage(
            source="project_expert_agent",
            agent_kind="project_expert",
            result=result,
            run_id="run-pe-1",
            terminal_status="succeeded",
            project_repo_id="repo-1",
            extra_metadata={"project_code": "RAVEN"},
        )
    )

    row = _fetch_one("ai_usage:project_expert_run:run-pe-1")
    assert row.project_repo_id == "repo-1"
    assert row.metadata_json is not None
    assert '"project_code": "RAVEN"' in row.metadata_json
    # tool_call_count is harvested from trace_summary.
    assert '"tool_call_count": 4' in row.metadata_json


def test_package_search_records_result_count_metadata(metrics_db):
    """Package search records a sanitized ``result_count`` and no prompt/answer text."""
    asyncio.run(
        ms.record_ai_usage(
            source="package_search_agent",
            idempotency_key="ai_usage:package_search:req-1",
            agent_kind="package",
            provider="anthropic",
            model="claude-sonnet-4-6",
            status="succeeded",
            usage={"input_tokens": 15, "output_tokens": 25},
            metadata={
                "result_count": 7,
                # these must never persist:
                "prompt": "find me firmware",
                "assistant_answer": "here are 7 packages",
            },
        )
    )

    row = _fetch_one("ai_usage:package_search:req-1")
    assert row.agent_kind == "package"
    assert row.total_tokens == 40
    assert row.metadata_json is not None
    assert '"result_count": 7' in row.metadata_json
    assert "firmware" not in row.metadata_json
    assert "assistant_answer" not in row.metadata_json


def test_title_generator_records_with_caller_context(metrics_db):
    """Title generator records token usage with caller-provided user/session."""
    asyncio.run(
        ms.record_ai_usage(
            source="title_generator",
            idempotency_key="ai_usage:title:msg-1",
            agent_kind="title_generator",
            provider="anthropic",
            model="claude-haiku-4-5",
            status="succeeded",
            usage={"input_tokens": 30, "output_tokens": 6},
            user_id="user-9",
            session_id="sess-9",
        )
    )

    row = _fetch_one("ai_usage:title:msg-1")
    assert row.agent_kind == "title_generator"
    assert row.user_id == "user-9"
    assert row.session_id == "sess-9"
    assert row.total_tokens == 36
