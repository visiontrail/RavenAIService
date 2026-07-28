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


# ==================== OCR sub-event merging ====================
#
# Image OCR preprocesses an agent run and is metered under that run's ``run_id``.
# ``list_metric_events`` folds it into the parent row so the admin audit feed
# shows one user request as one line.


def _record_pair(*, run_id: str, agent_kind: str, ocr_images: int = 2) -> None:
    """Record an agent-run event plus the OCR call that preprocessed it."""

    async def _run() -> None:
        await ms.record_ai_usage(
            source="ocr",
            agent_kind="ocr",
            provider="dashscope",
            model="qwen-vl-max",
            status="succeeded",
            usage={"input_tokens": 80, "output_tokens": 40},
            run_id=run_id,
            session_id=f"sess-{run_id}",
            idempotency_key=f"ai_usage:ocr:{run_id}",
            metadata={"image_count": ocr_images},
        )
        await ms.record_ai_usage(
            source="project_expert",
            agent_kind=agent_kind,
            provider="anthropic",
            model="claude-sonnet-4-6",
            status="succeeded",
            usage={"input_tokens": 400, "output_tokens": 100},
            run_id=run_id,
            session_id=f"sess-{run_id}",
            idempotency_key=f"ai_usage:{agent_kind}:{run_id}",
        )

    asyncio.run(_run())


def _list_events(**kwargs):
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    return asyncio.run(
        ms.list_metric_events(
            from_time=now - timedelta(hours=1),
            to_time=now + timedelta(hours=1),
            **kwargs,
        )
    )


def test_ocr_event_folds_into_its_parent_run(metrics_db):
    _record_pair(run_id="run-ocr-1", agent_kind="project_expert")

    result = _list_events()

    # One request, one row — the OCR event does not get its own line.
    assert result["total"] == 1
    (row,) = result["events"]
    assert row["agent_kind"] == "project_expert"
    assert row["total_tokens"] == 500
    (ocr,) = row["ocr_events"]
    assert ocr["agent_kind"] == "ocr"
    assert ocr["total_tokens"] == 120
    assert ocr["image_count"] == 2


def test_ocr_event_without_a_parent_run_still_lists(metrics_db):
    """An unpaired OCR event stays visible: merging must not drop usage."""

    async def _run() -> None:
        await ms.record_ai_usage(
            source="ocr",
            agent_kind="ocr",
            provider="dashscope",
            model="qwen-vl-max",
            status="failed",
            error_kind="timeout",
            usage=None,
            run_id="run-orphan",
            idempotency_key="ai_usage:ocr:run-orphan",
        )

    asyncio.run(_run())

    result = _list_events()
    assert result["total"] == 1
    assert result["events"][0]["agent_kind"] == "ocr"
    assert result["events"][0]["ocr_events"] == []


def test_legacy_ocr_event_without_run_id_still_lists(metrics_db):
    """Rows written before OCR and its run shared an id have no ``run_id``."""

    async def _run() -> None:
        await ms.record_ai_usage(
            source="ocr",
            agent_kind="ocr",
            provider="dashscope",
            model="qwen-vl-max",
            status="succeeded",
            usage={"input_tokens": 10, "output_tokens": 5},
            idempotency_key="ai_usage:ocr:legacy",
        )

    asyncio.run(_run())

    result = _list_events()
    assert result["total"] == 1
    assert result["events"][0]["agent_kind"] == "ocr"


def test_source_ocr_filter_turns_merging_off(metrics_db):
    """Filtering for ``source="ocr"`` audits OCR on its own, merged or not."""
    _record_pair(run_id="run-ocr-2", agent_kind="log_analysis")

    result = _list_events(source="ocr")

    assert result["total"] == 1
    assert result["events"][0]["agent_kind"] == "ocr"


def test_event_without_images_has_no_ocr_children(metrics_db):
    async def _run() -> None:
        await ms.record_ai_usage(
            source="general_agent",
            agent_kind="general",
            provider="anthropic",
            model="claude-sonnet-4-6",
            status="succeeded",
            usage={"input_tokens": 20, "output_tokens": 10},
            run_id="run-plain",
            idempotency_key="ai_usage:general:run-plain",
        )

    asyncio.run(_run())

    result = _list_events()
    assert result["total"] == 1
    assert result["events"][0]["ocr_events"] == []


def test_merged_total_reflects_pagination(metrics_db):
    """The hidden OCR rows must not inflate ``total`` or skew page offsets."""
    for index in range(3):
        _record_pair(run_id=f"run-page-{index}", agent_kind="project_expert")

    result = _list_events(page=1, per_page=2)

    # 6 rows exist; 3 are merged away, so the feed pages over 3.
    assert result["total"] == 3
    assert len(result["events"]) == 2
    assert all(len(e["ocr_events"]) == 1 for e in result["events"])


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
