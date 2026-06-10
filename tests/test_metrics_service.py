"""Unit tests for the pure helpers in ``app/services/metrics_service.py`` plus the
Prometheus bridge in ``app/utils/metrics.py``.

Covered tasks (openspec/changes/add-system-user-metrics/tasks.md):

- 7.1 token normalization, total-token math, metadata sanitization, pricing
  estimates, and missing-pricing behavior.
- 7.3 (partial) new Prometheus counters/histograms, no-op fallback, the
  metrics-failure counter, and the forbidden high-cardinality label assertion.
- 6.1 metadata allowlist enforcement (prompts / answers / headers never persist).
- 6.2 Prometheus collectors never expose user/owner/session/run/task/log/
  package/project identifiers as labels.

These are all pure / in-process: no database is required.
"""

from __future__ import annotations

import pytest

from app.services import metrics_service as ms
from app.utils import metrics as prom


# ==================== 7.1 token normalization ====================


def test_normalize_tokens_missing_fields_default_to_zero():
    result = ms.normalize_tokens(None)
    assert result == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_normalize_tokens_maps_aliases():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 2,
    }
    assert ms.normalize_tokens(usage) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 3,
        "cache_write_tokens": 2,
    }


def test_normalize_tokens_ignores_unknown_keys_and_negatives():
    usage = {"input_tokens": -4, "bogus": 99, "output_tokens": "7"}
    # negative clamped to 0, unknown dropped, numeric string coerced
    assert ms.normalize_tokens(usage) == {
        "input_tokens": 0,
        "output_tokens": 7,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_normalize_tokens_handles_non_dict():
    assert ms.normalize_tokens(["not", "a", "dict"]) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def test_normalize_tokens_handles_object_usage_payload():
    class Usage:
        input_tokens = 12
        output_tokens = 4
        cache_read_input_tokens = 6
        cache_creation_input_tokens = 2

    assert ms.normalize_tokens(Usage()) == {
        "input_tokens": 12,
        "output_tokens": 4,
        "cache_read_tokens": 6,
        "cache_write_tokens": 2,
    }


def test_compute_total_tokens_sums_all_four():
    tokens = {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 4,
        "cache_write_tokens": 8,
    }
    assert ms.compute_total_tokens(tokens) == 15


def test_compute_total_tokens_tolerates_missing_keys():
    assert ms.compute_total_tokens({"input_tokens": 5}) == 5


# ==================== 7.1 / 6.1 metadata sanitization ====================


def test_sanitize_metadata_keeps_only_allowlisted_keys():
    md = {
        "tool_call_count": 3,
        "trace_event_count": 42,
        "log_type": "syslog",
        "result_count": 7,
        "project_code": "abc",
        "error_kind": "timeout",
        "historical": True,
    }
    clean = ms.sanitize_metadata(md)
    assert clean == md


def test_sanitize_metadata_drops_sensitive_keys():
    # prompts, answers, headers, cookies, urls, tool I/O must never survive.
    md = {
        "prompt": "secret user prompt",
        "assistant_answer": "secret answer",
        "Authorization": "Bearer abc",
        "Cookie": "session=xyz",
        "repo_url": "https://x:token@github.com/a/b",
        "tool_input": {"k": "v"},
        "tool_call_count": 9,
    }
    clean = ms.sanitize_metadata(md)
    assert clean == {"tool_call_count": 9}


def test_sanitize_metadata_drops_nested_blobs_for_allowlisted_key():
    # even an allowlisted key may not carry a nested blob value.
    md = {"result_count": {"nested": "blob"}}
    assert ms.sanitize_metadata(md) is None


def test_sanitize_metadata_truncates_long_strings():
    long_value = "x" * 500
    clean = ms.sanitize_metadata({"project_code": long_value})
    assert clean is not None
    assert len(clean["project_code"]) == 128


def test_sanitize_metadata_returns_none_when_empty():
    assert ms.sanitize_metadata({}) is None
    assert ms.sanitize_metadata(None) is None
    assert ms.sanitize_metadata({"only_bad_key": 1}) is None


# ==================== 7.1 pricing estimates ====================


@pytest.fixture
def pricing(monkeypatch):
    """Configure a deterministic price table for one provider/model."""
    monkeypatch.setattr(
        ms.settings,
        "ai_metrics_pricing_json",
        '{"anthropic":{"claude-sonnet-4-6":{'
        '"input_per_million":3.0,"output_per_million":15.0,'
        '"cache_read_per_million":0.3,"cache_write_per_million":3.75}}}',
        raising=False,
    )


def test_estimate_cost_with_configured_pricing(pricing):
    tokens = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    # 1M input @ $3 + 1M output @ $15 = $18 -> 18_000_000 micro-USD
    cost = ms.estimate_cost_microusd("anthropic", "claude-sonnet-4-6", tokens)
    assert cost == 18_000_000


def test_estimate_cost_missing_pricing_returns_none(pricing):
    tokens = {"input_tokens": 100, "output_tokens": 100,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    # provider configured but model is unknown -> None
    assert ms.estimate_cost_microusd("anthropic", "unknown-model", tokens) is None
    # provider not configured -> None
    assert ms.estimate_cost_microusd("deepseek", "claude-sonnet-4-6", tokens) is None


def test_estimate_cost_no_pricing_configured_returns_none(monkeypatch):
    monkeypatch.setattr(ms.settings, "ai_metrics_pricing_json", None, raising=False)
    tokens = {"input_tokens": 100, "output_tokens": 100,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert ms.estimate_cost_microusd("anthropic", "claude-sonnet-4-6", tokens) is None


def test_estimate_cost_requires_provider_and_model(pricing):
    tokens = {"input_tokens": 100, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert ms.estimate_cost_microusd(None, "claude-sonnet-4-6", tokens) is None
    assert ms.estimate_cost_microusd("anthropic", None, tokens) is None


def test_estimate_cost_zero_tokens_returns_none(pricing):
    tokens = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    # no priced tokens matched -> None (so API surfaces cost_estimated=false)
    assert ms.estimate_cost_microusd("anthropic", "claude-sonnet-4-6", tokens) is None


# ==================== 6.2 / 7.3 forbidden high-cardinality labels ====================

# Identifiers that must NEVER appear as Prometheus labels (design Decision 2).
_FORBIDDEN_LABELS = frozenset(
    {
        "user_id",
        "username",
        "owner_scope",
        "session_id",
        "run_id",
        "task_id",
        "log_id",
        "project_repo_id",
    }
)

_NEW_COLLECTORS = (
    "raven_ai_tokens_total",
    "raven_ai_invocations_total",
    "raven_ai_invocation_duration_seconds",
    "raven_ai_errors_total",
    "raven_http_requests_total",
    "raven_http_request_duration_seconds",
    "raven_log_uploads_total",
    "raven_log_uploaded_bytes_total",
    "raven_package_activity_total",
    "raven_device_connections",
    "raven_metrics_record_failures_total",
)


@pytest.mark.skipif(
    not prom.is_prometheus_available(), reason="prometheus_client not installed"
)
def test_no_collector_exposes_high_cardinality_identifier_label():
    for name in _NEW_COLLECTORS:
        collector = getattr(prom, name)
        label_names = set(getattr(collector, "_labelnames", ()))
        leaked = label_names & _FORBIDDEN_LABELS
        assert not leaked, f"{name} exposes forbidden labels: {leaked}"


# ==================== 7.3 no-op fallback + failure counter ====================


def _sample_value(collector, predicate) -> float:
    for sample in collector.collect()[0].samples:
        if predicate(sample):
            return sample.value
    return 0.0


@pytest.mark.skipif(
    not prom.is_prometheus_available(), reason="prometheus_client not installed"
)
def test_record_ai_usage_prometheus_increments_tokens_and_invocations():
    def tokens_for(token_type):
        return _sample_value(
            prom.raven_ai_tokens_total,
            lambda s: s.labels.get("source") == "unit_test"
            and s.labels.get("token_type") == token_type
            and s.name.endswith("_total"),
        )

    before_input = tokens_for("input")
    before_inv = _sample_value(
        prom.raven_ai_invocations_total,
        lambda s: s.labels.get("source") == "unit_test"
        and s.labels.get("status") == "succeeded"
        and s.name.endswith("_total"),
    )

    prom.record_ai_usage_prometheus(
        source="unit_test",
        agent_kind="general",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="succeeded",
        input_tokens=11,
        output_tokens=22,
        duration_ms=1500,
    )

    assert tokens_for("input") == before_input + 11
    after_inv = _sample_value(
        prom.raven_ai_invocations_total,
        lambda s: s.labels.get("source") == "unit_test"
        and s.labels.get("status") == "succeeded"
        and s.name.endswith("_total"),
    )
    assert after_inv == before_inv + 1


@pytest.mark.skipif(
    not prom.is_prometheus_available(), reason="prometheus_client not installed"
)
def test_record_ai_usage_prometheus_records_error_kind():
    before = _sample_value(
        prom.raven_ai_errors_total,
        lambda s: s.labels.get("source") == "unit_test_err"
        and s.labels.get("error_kind") == "timeout"
        and s.name.endswith("_total"),
    )
    prom.record_ai_usage_prometheus(
        source="unit_test_err",
        agent_kind="general",
        provider="anthropic",
        model="m",
        status="failed",
        error_kind="timeout",
    )
    after = _sample_value(
        prom.raven_ai_errors_total,
        lambda s: s.labels.get("source") == "unit_test_err"
        and s.labels.get("error_kind") == "timeout"
        and s.name.endswith("_total"),
    )
    assert after == before + 1


@pytest.mark.skipif(
    not prom.is_prometheus_available(), reason="prometheus_client not installed"
)
def test_metrics_failure_counter_increments():
    before = _sample_value(
        prom.raven_metrics_record_failures_total,
        lambda s: s.labels.get("source") == "unit_test_fail"
        and s.name.endswith("_total"),
    )
    prom.record_metrics_failure("unit_test_fail")
    after = _sample_value(
        prom.raven_metrics_record_failures_total,
        lambda s: s.labels.get("source") == "unit_test_fail"
        and s.name.endswith("_total"),
    )
    assert after == before + 1


def test_prometheus_helpers_never_raise_on_bad_input():
    # No-op fallback safety: even with None/garbage labels these must not raise,
    # regardless of whether prometheus_client is installed.
    prom.record_ai_usage_prometheus(
        source=None, agent_kind=None, provider=None, model=None, status=None,
        input_tokens=-5, duration_ms=-1,
    )
    prom.record_http_request(method=None, route=None, status_code=None, duration_seconds=-1)
    prom.record_log_upload(log_type=None, status=None, uploaded_bytes=-3)
    prom.record_package_activity(action=None, status=None)
    prom.set_device_connections({"online": 2, "offline": None})
    prom.record_metrics_failure(None)
