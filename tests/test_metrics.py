"""Tests for ``app/utils/metrics.py`` and the ``/metrics`` endpoint.

Goals:
- Verify ``safe_emit`` increments the per-kind counter regardless of
  whether the emitter raises or is missing.
- Verify the Redis-bytes gauge accepts a write and rejects negatives.
- Exercise the ``/metrics`` route handler and confirm it returns text
  exposition when prometheus_client is available, or 503 otherwise.

We avoid reloading the metrics module (registering a Counter twice
raises a Prometheus ``Duplicated timeseries`` error). The module-level
collectors are tested in place using their public ``collect()`` API to
compare before/after sample values.
"""

from __future__ import annotations

import asyncio

import pytest

from app.utils import metrics as metrics_module


def _counter_value(kind: str) -> float:
    samples = list(
        metrics_module.ai_analysis_trace_events_emitted_total.collect()[0].samples
    )
    for s in samples:
        if s.labels.get("kind") == kind and s.name.endswith("_total"):
            return s.value
    return 0.0


def _gauge_value() -> float:
    samples = list(metrics_module.ai_analysis_trace_redis_bytes.collect()[0].samples)
    for s in samples:
        if s.name == "ai_analysis_trace_redis_bytes":
            return s.value
    return 0.0


@pytest.fixture(autouse=True)
def _require_prometheus():
    if not metrics_module.is_prometheus_available():
        pytest.skip("prometheus_client not installed")


def test_record_trace_event_emitted_increments_counter_per_kind():
    before_start = _counter_value("step_start")
    before_end = _counter_value("step_end")
    metrics_module.record_trace_event_emitted("step_start")
    metrics_module.record_trace_event_emitted("step_start")
    metrics_module.record_trace_event_emitted("step_end")
    assert _counter_value("step_start") == before_start + 2
    assert _counter_value("step_end") == before_end + 1


def test_record_trace_event_emitted_handles_empty_kind():
    before = _counter_value("unknown")
    metrics_module.record_trace_event_emitted("")
    metrics_module.record_trace_event_emitted("")
    assert _counter_value("unknown") == before + 2


def test_record_trace_redis_bytes_sets_gauge_value():
    metrics_module.record_trace_redis_bytes(4321)
    assert _gauge_value() == 4321
    metrics_module.record_trace_redis_bytes(7777)
    assert _gauge_value() == 7777


def test_record_trace_redis_bytes_ignores_negative():
    metrics_module.record_trace_redis_bytes(1000)
    metrics_module.record_trace_redis_bytes(-5)
    # Gauge stays at the prior positive value.
    assert _gauge_value() == 1000


def test_safe_emit_increments_metric_counter():
    from app.agents.log_analysis.trace import safe_emit

    before = _counter_value("thinking_delta")
    safe_emit(None, {"type": "thinking_delta", "task_id": "t", "seq": 1, "timestamp": 0.0})
    assert _counter_value("thinking_delta") == before + 1


def test_safe_emit_increments_metric_even_when_emitter_raises():
    from app.agents.log_analysis.trace import safe_emit

    def boom(_event):
        raise RuntimeError("nope")

    before = _counter_value("error")
    safe_emit(boom, {"type": "error", "task_id": "t", "seq": 1, "timestamp": 0.0})
    assert _counter_value("error") == before + 1


def test_metrics_endpoint_returns_prometheus_exposition():
    from app.api.metrics import prometheus_metrics

    # Ensure the counter has at least one sample to render.
    metrics_module.record_trace_event_emitted("run_start")
    response = asyncio.run(prometheus_metrics())
    assert response.status_code == 200
    body = bytes(response.body)
    assert b"ai_analysis_trace_events_emitted_total" in body
    assert response.media_type.startswith("text/plain")


def test_metrics_module_render_latest_includes_counter_name():
    metrics_module.record_trace_event_emitted("step_start")
    raw = metrics_module.render_latest()
    assert b"ai_analysis_trace_events_emitted_total" in raw
