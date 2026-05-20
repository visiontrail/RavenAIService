"""Prometheus metrics for the agent trace pipeline.

This module exposes two metrics that operate teams watch:

- ``ai_analysis_trace_events_emitted_total{kind=...}`` — Counter incremented
  once per ``AgentTraceEvent`` that passes through ``safe_emit``. The
  ``kind`` label is the event ``type`` (``step_start``, ``step_delta``,
  ``run_complete``, etc.) so a sudden spike in one kind (e.g. runaway
  ``thinking_delta``) is visible without crawling logs.

- ``ai_analysis_trace_redis_bytes`` — Gauge set to the most recent
  observed byte count of an ``ai_analysis:trace:{task_id}`` Redis list.
  We deliberately do NOT label by ``task_id`` (high cardinality), so the
  gauge is "size of the buffer last touched" — useful for catching one
  task that grows pathologically large; pair with an alert at e.g. 8 MB.

``prometheus_client`` is soft-imported. If the dependency is missing the
module falls back to no-op stubs so importing this file is always safe
(e.g. unit tests, minimal images). The ``/metrics`` endpoint returns
``503`` in that mode so the operator sees an explicit signal rather than
silently empty scrapes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


try:
    from prometheus_client import (  # type: ignore[import-not-found]
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        generate_latest,
    )

    _HAS_PROMETHEUS = True
except Exception:  # noqa: BLE001
    _HAS_PROMETHEUS = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest() -> bytes:  # type: ignore[misc]
        return b""


class _NoOpMetric:
    """Stand-in for Counter/Gauge when prometheus_client is unavailable."""

    def labels(self, *_args: Any, **_kwargs: Any) -> "_NoOpMetric":
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


if _HAS_PROMETHEUS:
    ai_analysis_trace_events_emitted_total = Counter(
        "ai_analysis_trace_events_emitted_total",
        "Number of AgentTraceEvent payloads emitted via safe_emit, by event kind.",
        labelnames=("kind",),
    )
    ai_analysis_trace_redis_bytes = Gauge(
        "ai_analysis_trace_redis_bytes",
        "Bytes of the most-recently-written ai_analysis:trace:{task_id} Redis list.",
    )
else:
    ai_analysis_trace_events_emitted_total = _NoOpMetric()  # type: ignore[assignment]
    ai_analysis_trace_redis_bytes = _NoOpMetric()  # type: ignore[assignment]


def record_trace_event_emitted(kind: str) -> None:
    """Bump the per-kind emitted counter (single chokepoint, never raises)."""
    try:
        ai_analysis_trace_events_emitted_total.labels(kind=kind or "unknown").inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: trace counter increment failed: %s", exc)


def record_trace_redis_bytes(bytes_count: int) -> None:
    """Set the last-observed Redis buffer size in bytes."""
    if bytes_count < 0:
        return
    try:
        ai_analysis_trace_redis_bytes.set(float(bytes_count))
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: trace bytes gauge set failed: %s", exc)


def is_prometheus_available() -> bool:
    return _HAS_PROMETHEUS


def render_latest() -> bytes:
    """Render the Prometheus text exposition for all collectors."""
    return generate_latest()
