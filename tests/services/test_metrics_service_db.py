"""DB-backed tests for ``app/services/metrics_service.py``.

Covered tasks (openspec/changes/add-system-user-metrics/tasks.md):

- 7.2 idempotency: the same ``idempotency_key`` never produces a second row and
  never double-counts token totals, whether replayed serially or concurrently.
- 7.7 resilience: a metrics insertion failure (database unavailable / bad input)
  is swallowed — ``record_*`` never raises into the caller and instead bumps the
  ``raven_metrics_record_failures_total`` Prometheus counter.

Unlike ``test_metrics_service.py`` (pure helpers), these spin up a throwaway
SQLite database and drive the real async insert path through ``db_manager``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from app.config import settings
from app.models.database import Base, db_manager
from app.models.metrics import MetricEvent
from app.services import metrics_service as ms
from app.utils import metrics as prom
from sqlalchemy import func, select


@pytest.fixture
def metrics_db():
    """Point ``db_manager`` at a fresh temp SQLite file with only metric_events.

    Restores the prior database url + manager state on teardown so the singleton
    does not leak across tests.
    """
    fd, path = tempfile.mkstemp(prefix="metrics-db-", suffix=".sqlite")
    os.close(fd)

    prev_url = settings.database_url
    prev_engine = db_manager.engine
    prev_factory = db_manager.session_factory

    settings.database_url = f"sqlite+aiosqlite:///{path}"
    db_manager.initialize()

    async def _create() -> None:
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all, tables=[MetricEvent.__table__]
            )

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


def _count_rows(key: str) -> int:
    async def _run() -> int:
        async with db_manager.session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.count()).where(
                            MetricEvent.idempotency_key == key
                        )
                    )
                ).scalar()
                or 0
            )

    return asyncio.run(_run())


def _sum_total_tokens(source: str) -> int:
    async def _run() -> int:
        async with db_manager.session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.coalesce(func.sum(MetricEvent.total_tokens), 0)).where(
                            MetricEvent.source == source
                        )
                    )
                ).scalar()
                or 0
            )

    return asyncio.run(_run())


# ==================== 7.2 idempotency ====================


def test_duplicate_idempotency_key_inserts_one_row(metrics_db):
    key = "ai_usage:general_run:run-7-2-a"
    usage = {"input_tokens": 100, "output_tokens": 50}

    async def _record_twice() -> None:
        await ms.record_ai_usage(
            source="general_agent",
            idempotency_key=key,
            agent_kind="general",
            provider="anthropic",
            model="claude-sonnet-4-6",
            status="succeeded",
            usage=usage,
        )
        # Replay with the SAME key — must be a no-op insert.
        await ms.record_ai_usage(
            source="general_agent",
            idempotency_key=key,
            agent_kind="general",
            provider="anthropic",
            model="claude-sonnet-4-6",
            status="succeeded",
            usage=usage,
        )

    asyncio.run(_record_twice())

    assert _count_rows(key) == 1
    # 150 tokens recorded once, not 300.
    assert _sum_total_tokens("general_agent") == 150


def test_concurrent_same_key_inserts_one_row(metrics_db):
    key = "ai_usage:general_run:run-7-2-b"

    async def _race() -> None:
        await asyncio.gather(
            *(
                ms.record_ai_usage(
                    source="race_agent",
                    idempotency_key=key,
                    agent_kind="general",
                    status="succeeded",
                    usage={"input_tokens": 10, "output_tokens": 10},
                )
                for _ in range(5)
            )
        )

    asyncio.run(_race())

    assert _count_rows(key) == 1
    assert _sum_total_tokens("race_agent") == 20


def test_duplicate_does_not_double_count_prometheus(metrics_db):
    if not prom.is_prometheus_available():
        pytest.skip("prometheus_client not installed")
    key = "ai_usage:general_run:run-7-2-c"

    def invocations() -> float:
        for sample in prom.raven_ai_invocations_total.collect()[0].samples:
            if (
                sample.labels.get("source") == "promdup_agent"
                and sample.labels.get("status") == "succeeded"
                and sample.name.endswith("_total")
            ):
                return sample.value
        return 0.0

    before = invocations()

    async def _record_twice() -> None:
        for _ in range(2):
            await ms.record_ai_usage(
                source="promdup_agent",
                idempotency_key=key,
                agent_kind="general",
                status="succeeded",
                usage={"input_tokens": 1},
            )

    asyncio.run(_record_twice())

    # Prometheus is only bumped on the first (real) insert.
    assert invocations() == before + 1


# ==================== 7.7 resilience ====================


def test_record_ai_usage_swallows_db_unavailable(monkeypatch):
    """No DB initialized → record_ai_usage must not raise; failure is counted."""
    monkeypatch.setattr(db_manager, "session_factory", None, raising=False)

    failures_before = 0.0
    if prom.is_prometheus_available():
        for sample in prom.raven_metrics_record_failures_total.collect()[0].samples:
            if (
                sample.labels.get("source") == "down_agent"
                and sample.name.endswith("_total")
            ):
                failures_before = sample.value
                break

    async def _run() -> None:
        # Must complete without raising even though the DB is unavailable.
        await ms.record_ai_usage(
            source="down_agent",
            idempotency_key="ai_usage:general_run:run-7-7-a",
            agent_kind="general",
            status="succeeded",
            usage={"input_tokens": 5},
        )

    asyncio.run(_run())

    if prom.is_prometheus_available():
        failures_after = 0.0
        for sample in prom.raven_metrics_record_failures_total.collect()[0].samples:
            if (
                sample.labels.get("source") == "down_agent"
                and sample.name.endswith("_total")
            ):
                failures_after = sample.value
                break
        assert failures_after == failures_before + 1


def test_record_business_event_swallows_db_unavailable(monkeypatch):
    monkeypatch.setattr(db_manager, "session_factory", None, raising=False)

    async def _run() -> None:
        await ms.record_business_event(
            event_type="log_activity",
            source="log_upload",
            idempotency_key="log_activity:log-7-7-b",
            status="succeeded",
            metadata={"log_type": "syslog"},
        )

    # The only assertion that matters: it returns instead of propagating.
    asyncio.run(_run())


def test_record_agent_run_usage_swallows_bad_result(monkeypatch):
    """A malformed terminal result is swallowed (best-effort recording)."""
    monkeypatch.setattr(db_manager, "session_factory", None, raising=False)

    async def _run() -> None:
        await ms.record_agent_run_usage(
            source="general_agent",
            agent_kind="general",
            result={"token_usage": "not-a-dict", "duration_seconds": "weird"},
            run_id="run-7-7-c",
            terminal_status="succeeded",
        )

    asyncio.run(_run())
