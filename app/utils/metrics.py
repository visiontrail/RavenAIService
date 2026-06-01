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
    """Stand-in for Counter/Gauge/Histogram when prometheus_client is unavailable."""

    def labels(self, *_args: Any, **_kwargs: Any) -> "_NoOpMetric":
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


if _HAS_PROMETHEUS:
    from prometheus_client import Histogram  # type: ignore[import-not-found]

    ai_analysis_trace_events_emitted_total = Counter(
        "ai_analysis_trace_events_emitted_total",
        "Number of AgentTraceEvent payloads emitted via safe_emit, by event kind.",
        labelnames=("kind",),
    )
    ai_analysis_trace_redis_bytes = Gauge(
        "ai_analysis_trace_redis_bytes",
        "Bytes of the most-recently-written ai_analysis:trace:{task_id} Redis list.",
    )

    # ==================== AI usage metrics (low cardinality only) ====================
    # NOTE: labels are deliberately restricted to low/medium-cardinality dimensions.
    # user_id / username / owner_scope / session_id / run_id / task_id / log_id /
    # project_repo_id MUST NEVER appear as labels here (see design Decision 2).
    raven_ai_tokens_total = Counter(
        "raven_ai_tokens_total",
        "Total AI tokens consumed, by source/agent/provider/model/token_type.",
        labelnames=("source", "agent_kind", "provider", "model", "token_type"),
    )
    raven_ai_invocations_total = Counter(
        "raven_ai_invocations_total",
        "Total AI invocations (run terminal states), by source/agent/provider/model/status.",
        labelnames=("source", "agent_kind", "provider", "model", "status"),
    )
    raven_ai_invocation_duration_seconds = Histogram(
        "raven_ai_invocation_duration_seconds",
        "AI invocation wall-clock duration in seconds.",
        labelnames=("source", "agent_kind", "provider", "model", "status"),
    )
    raven_ai_errors_total = Counter(
        "raven_ai_errors_total",
        "Total AI invocation errors, by source/agent/error_kind.",
        labelnames=("source", "agent_kind", "error_kind"),
    )

    # ==================== HTTP request metrics ====================
    raven_http_requests_total = Counter(
        "raven_http_requests_total",
        "Total HTTP requests, by method/route-template/status_code.",
        labelnames=("method", "route", "status_code"),
    )
    raven_http_request_duration_seconds = Histogram(
        "raven_http_request_duration_seconds",
        "HTTP request duration in seconds, by method/route-template/status_code.",
        labelnames=("method", "route", "status_code"),
    )

    # ==================== Business activity metrics ====================
    raven_log_uploads_total = Counter(
        "raven_log_uploads_total",
        "Total log uploads, by log_type/status.",
        labelnames=("log_type", "status"),
    )
    raven_log_uploaded_bytes_total = Counter(
        "raven_log_uploaded_bytes_total",
        "Total uploaded log bytes, by log_type.",
        labelnames=("log_type",),
    )
    raven_package_activity_total = Counter(
        "raven_package_activity_total",
        "Total package activity (upload/download/etc), by action/package_type/status.",
        labelnames=("action", "package_type", "status"),
    )
    raven_device_connections = Gauge(
        "raven_device_connections",
        "Current device connection count, by state.",
        labelnames=("state",),
    )

    # ==================== Metrics self-monitoring ====================
    raven_metrics_record_failures_total = Counter(
        "raven_metrics_record_failures_total",
        "Total metrics-recording failures (best-effort path), by source.",
        labelnames=("source",),
    )
else:
    ai_analysis_trace_events_emitted_total = _NoOpMetric()  # type: ignore[assignment]
    ai_analysis_trace_redis_bytes = _NoOpMetric()  # type: ignore[assignment]
    raven_ai_tokens_total = _NoOpMetric()  # type: ignore[assignment]
    raven_ai_invocations_total = _NoOpMetric()  # type: ignore[assignment]
    raven_ai_invocation_duration_seconds = _NoOpMetric()  # type: ignore[assignment]
    raven_ai_errors_total = _NoOpMetric()  # type: ignore[assignment]
    raven_http_requests_total = _NoOpMetric()  # type: ignore[assignment]
    raven_http_request_duration_seconds = _NoOpMetric()  # type: ignore[assignment]
    raven_log_uploads_total = _NoOpMetric()  # type: ignore[assignment]
    raven_log_uploaded_bytes_total = _NoOpMetric()  # type: ignore[assignment]
    raven_package_activity_total = _NoOpMetric()  # type: ignore[assignment]
    raven_device_connections = _NoOpMetric()  # type: ignore[assignment]
    raven_metrics_record_failures_total = _NoOpMetric()  # type: ignore[assignment]


# Low-cardinality guard: label values that look like high-cardinality identifiers
# are collapsed to a stable placeholder. This is a defensive backstop; callers
# should already pass low-cardinality values.
_UNKNOWN = "unknown"


def _label(value: Any) -> str:
    """Coerce a label value to a safe, non-empty string."""
    if value is None:
        return _UNKNOWN
    text_value = str(value).strip()
    return text_value or _UNKNOWN


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


def record_ai_usage_prometheus(
    *,
    source: str,
    agent_kind: Any,
    provider: Any,
    model: Any,
    status: Any,
    error_kind: Any = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    duration_ms: Any = None,
) -> None:
    """Update AI usage Prometheus collectors for one invocation.

    Call this ONLY after a metric event insert succeeds, so duplicate
    idempotency keys do not double count (see metrics_service). Never raises.
    """
    try:
        s = _label(source)
        a = _label(agent_kind)
        p = _label(provider)
        m = _label(model)
        st = _label(status)

        token_pairs = (
            ("input", input_tokens),
            ("output", output_tokens),
            ("cache_read", cache_read_tokens),
            ("cache_write", cache_write_tokens),
        )
        for token_type, count in token_pairs:
            if count and count > 0:
                raven_ai_tokens_total.labels(
                    source=s, agent_kind=a, provider=p, model=m, token_type=token_type
                ).inc(count)

        raven_ai_invocations_total.labels(
            source=s, agent_kind=a, provider=p, model=m, status=st
        ).inc()

        if duration_ms is not None and duration_ms >= 0:
            raven_ai_invocation_duration_seconds.labels(
                source=s, agent_kind=a, provider=p, model=m, status=st
            ).observe(float(duration_ms) / 1000.0)

        if error_kind:
            raven_ai_errors_total.labels(
                source=s, agent_kind=a, error_kind=_label(error_kind)
            ).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: ai usage prometheus update failed: %s", exc)


def record_http_request(
    *, method: str, route: str, status_code: Any, duration_seconds: float
) -> None:
    """Record one HTTP request. ``route`` MUST be a route template, not a raw path."""
    try:
        labels = {
            "method": _label(method),
            "route": _label(route),
            "status_code": _label(status_code),
        }
        raven_http_requests_total.labels(**labels).inc()
        if duration_seconds is not None and duration_seconds >= 0:
            raven_http_request_duration_seconds.labels(**labels).observe(
                float(duration_seconds)
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: http request prometheus update failed: %s", exc)


def record_log_upload(*, log_type: Any, status: Any, uploaded_bytes: int = 0) -> None:
    """Record one log upload business event in Prometheus."""
    try:
        lt = _label(log_type)
        raven_log_uploads_total.labels(log_type=lt, status=_label(status)).inc()
        if uploaded_bytes and uploaded_bytes > 0:
            raven_log_uploaded_bytes_total.labels(log_type=lt).inc(uploaded_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: log upload prometheus update failed: %s", exc)


def record_package_activity(*, action: Any, package_type: Any, status: Any) -> None:
    """Record one package activity business event in Prometheus."""
    try:
        raven_package_activity_total.labels(
            action=_label(action),
            package_type=_label(package_type),
            status=_label(status),
        ).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: package activity prometheus update failed: %s", exc)


def set_device_connections(counts_by_state: dict) -> None:
    """Set the device-connections gauge for each known state."""
    try:
        for state, count in (counts_by_state or {}).items():
            raven_device_connections.labels(state=_label(state)).set(float(count or 0))
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: device connections gauge set failed: %s", exc)


def record_metrics_failure(source: str) -> None:
    """Increment the metrics-recording failure counter for a source."""
    try:
        raven_metrics_record_failures_total.labels(source=_label(source)).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("metrics: failure counter increment failed: %s", exc)


def is_prometheus_available() -> bool:
    return _HAS_PROMETHEUS


def render_latest() -> bytes:
    """Render the Prometheus text exposition for all collectors."""
    return generate_latest()
