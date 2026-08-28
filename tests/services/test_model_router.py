"""Tests for the primary/backup endpoint router.

No live Redis: a fake client stands in for it (same seam
``agent_trace_redis.TraceBuffer(redis_client=...)`` uses), so the k-of-n window,
the TTL breaker and the half-open probe token are all exercised deterministically
— including the path where Redis is unreachable entirely.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import model_router
from app.services import runtime_settings_service


class FakeRedis:
    """Minimal in-memory stand-in for the commands the router uses."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}
        self.fail = False  # flip to simulate an outage mid-test

    def _check(self) -> None:
        if self.fail:
            raise RuntimeError("redis is down")

    # -- string ops --
    def set(self, key, value, ex=None, nx=False):  # noqa: A002
        self._check()
        if nx and key in self.strings:
            return None
        self.strings[key] = str(value)
        return True

    def get(self, key):
        self._check()
        return self.strings.get(key)

    def exists(self, key):
        self._check()
        return 1 if key in self.strings else 0

    def delete(self, key):
        self._check()
        self.strings.pop(key, None)
        self.lists.pop(key, None)
        return 1

    def incr(self, key):
        self._check()
        value = int(self.strings.get(key, "0")) + 1
        self.strings[key] = str(value)
        return value

    # -- list ops --
    def lrange(self, key, start, end):
        self._check()
        items = self.lists.get(key, [])
        return items[start : (None if end == -1 else end + 1)]

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._ops: list = []

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        self._client._check()
        for op in self._ops:
            if op[0] == "lpush":
                self._client.lists.setdefault(op[1], []).insert(0, op[2])
            elif op[0] == "ltrim":
                _, key, start, end = op
                items = self._client.lists.get(key, [])
                self._client.lists[key] = items[start : end + 1]
        self._ops.clear()
        return []


@pytest.fixture
def fake_redis():
    client = FakeRedis()
    model_router.reset_store_for_tests(client)
    yield client
    model_router.reset_store_for_tests(None)


@pytest.fixture
def routed(monkeypatch, tmp_path):
    """Routing on, both slots configured, deterministic thresholds."""
    runtime_path = tmp_path / "runtime-settings.json"
    monkeypatch.setattr(settings, "runtime_settings_path", str(runtime_path))
    monkeypatch.setattr(runtime_settings_service, "_CACHE", None)
    monkeypatch.setattr(runtime_settings_service, "_CACHE_MTIME", 0.0)
    monkeypatch.setattr(runtime_settings_service, "_CACHE_PATH", None)

    monkeypatch.setattr(settings, "model_router_enabled", True)
    monkeypatch.setattr(settings, "model_router_window_size", 4)
    monkeypatch.setattr(settings, "model_router_trip_threshold", 3)
    monkeypatch.setattr(settings, "model_router_min_samples", 3)
    monkeypatch.setattr(settings, "model_router_hard_failure_trip", 2)
    monkeypatch.setattr(settings, "model_router_cooldown_seconds", 60)
    monkeypatch.setattr(settings, "model_router_slow_ttft_ms", 5000)

    monkeypatch.setattr(settings, "anthropic_provider", "yinhe")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-primary")
    monkeypatch.setattr(settings, "anthropic_api_keys", [])
    monkeypatch.setattr(settings, "anthropic_base_url", "")
    monkeypatch.setattr(settings, "anthropic_model", "")
    monkeypatch.setattr(settings, "anthropic_small_fast_model", "")

    monkeypatch.setattr(settings, "anthropic_backup_enabled", True)
    monkeypatch.setattr(settings, "anthropic_backup_provider", "deepseek")
    monkeypatch.setattr(settings, "anthropic_backup_api_key", "sk-backup")
    monkeypatch.setattr(settings, "anthropic_backup_base_url", "")
    monkeypatch.setattr(settings, "anthropic_backup_model", "")
    monkeypatch.setattr(settings, "anthropic_backup_small_fast_model", "")


def slots(choices):
    return [c.slot for c in choices]


# ─────────────────────────── Candidate selection ───────────────────────────


def test_primary_first_when_healthy(fake_redis, routed):
    assert slots(model_router.candidates()) == ["primary", "backup"]


def test_resolves_endpoint_from_provider_profile(fake_redis, routed):
    primary = model_router.candidates()[0]
    assert primary.provider == "yinhe"
    assert primary.base_url == "http://oneapi.yhroot.com"
    assert primary.model == "yinhe-thinking"
    assert primary.api_key == "sk-primary"
    # The backup must carry its own key, never the primary's.
    assert model_router.candidates()[1].api_key == "sk-backup"


def test_primary_pool_round_robins_through_redis_cursor(fake_redis, routed, monkeypatch):
    monkeypatch.setattr(
        settings, "anthropic_api_keys", ["sk-pool-a", "sk-pool-b", "sk-pool-c"]
    )

    choices = [model_router.candidates()[0] for _ in range(5)]

    assert [choice.api_key for choice in choices] == [
        "sk-pool-a",
        "sk-pool-b",
        "sk-pool-c",
        "sk-pool-a",
        "sk-pool-b",
    ]
    assert all(choice.api_key_count == 3 for choice in choices)
    assert len({choice.api_key_id for choice in choices}) == 3
    assert all(not choice.api_key_id.startswith("sk-") for choice in choices)


def test_primary_pool_falls_back_to_local_cursor_when_redis_is_down(
    fake_redis, routed, monkeypatch
):
    monkeypatch.setattr(settings, "anthropic_api_keys", ["sk-a", "sk-b"])
    fake_redis.fail = True

    assert [model_router.candidates()[0].api_key for _ in range(4)] == [
        "sk-a",
        "sk-b",
        "sk-a",
        "sk-b",
    ]


def test_backup_remains_single_key_when_primary_has_pool(fake_redis, routed, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_keys", ["sk-a", "sk-b"])

    backup = model_router.candidates()[1]

    assert backup.api_key == "sk-backup"
    assert backup.api_key_count == 1


def test_routing_disabled_yields_primary_only(fake_redis, routed, monkeypatch):
    monkeypatch.setattr(settings, "model_router_enabled", False)
    assert slots(model_router.candidates()) == ["primary"]


def test_observe_only_mode_measures_but_never_trips(fake_redis, routed, monkeypatch):
    """Disabled = no failover, but the window must keep filling.

    Thresholds can only be tuned against real TTFT data, and there is no way to
    collect it without running the measurement path — so the switch gates
    routing, not observation.
    """
    monkeypatch.setattr(settings, "model_router_enabled", False)

    for _ in range(6):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)

    store = model_router.get_store()
    assert store.samples("primary", window_size=4) == ["1"] * 4  # measured
    assert store.breaker_open("primary") is False                # but never routed away
    assert slots(model_router.candidates()) == ["primary"]


def test_backup_disabled_yields_primary_only(fake_redis, routed, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_backup_enabled", False)
    assert slots(model_router.candidates()) == ["primary"]


def test_backup_without_key_is_not_a_candidate(fake_redis, routed, monkeypatch):
    """A half-configured backup must never become a failover dead end."""
    monkeypatch.setattr(settings, "anthropic_backup_api_key", "")
    assert slots(model_router.candidates()) == ["primary"]


def test_capability_filter_excludes_incompatible_backup(fake_redis, routed, monkeypatch):
    # yinhe has no image support either, so ask for something only some
    # providers have and confirm the mismatch removes the candidate.
    monkeypatch.setattr(settings, "anthropic_backup_provider", "deepseek")
    # deepseek: supports_image_input=False; anthropic: True.
    assert slots(model_router.candidates(require_image=True)) == []

    monkeypatch.setattr(settings, "anthropic_provider", "anthropic")
    assert slots(model_router.candidates(require_image=True)) == ["primary"]


def test_small_fast_requirement_excludes_slot_without_one(fake_redis, routed, monkeypatch):
    """general_agent refuses to run without a small/fast model.

    Under routing that must drop the candidate, not fail the whole run.
    """
    monkeypatch.setattr(settings, "anthropic_backup_provider", "custom")
    monkeypatch.setattr(settings, "anthropic_backup_base_url", "https://x.test")
    monkeypatch.setattr(settings, "anthropic_backup_model", "m")
    # custom's profile has default_small_fast_model=None and none is configured.
    assert slots(model_router.candidates(require_small_fast=True)) == ["primary"]


# ─────────────────────────── Window and breaker ────────────────────────────


def test_trips_after_k_of_n_bad_calls(fake_redis, routed):
    for _ in range(2):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert model_router.get_store().breaker_open("primary") is False

    model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert model_router.get_store().breaker_open("primary") is True


def test_does_not_trip_below_min_samples(fake_redis, routed, monkeypatch):
    monkeypatch.setattr(settings, "model_router_min_samples", 4)
    for _ in range(3):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert model_router.get_store().breaker_open("primary") is False


def test_slow_response_counts_as_bad(fake_redis, routed):
    """A fast-enough reply is good; an over-threshold one is the peak-hour case."""
    for _ in range(3):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_OK, ttft_ms=100)
    assert model_router.get_store().breaker_open("primary") is False

    for _ in range(3):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_OK, ttft_ms=9000)
    assert model_router.get_store().breaker_open("primary") is True


def test_hard_failures_trip_faster(fake_redis, routed):
    """Connection refused needs 2, not the 3 a slow response needs."""
    model_router.record_outcome("primary", outcome=model_router.OUTCOME_HARD_FAILURE)
    assert model_router.get_store().breaker_open("primary") is False
    model_router.record_outcome("primary", outcome=model_router.OUTCOME_HARD_FAILURE)
    assert model_router.get_store().breaker_open("primary") is True


def test_backup_never_trips_a_breaker(fake_redis, routed):
    """Tripping the backup would leave nowhere to route."""
    for _ in range(6):
        model_router.record_outcome("backup", outcome=model_router.OUTCOME_TIMEOUT)
    assert model_router.get_store().breaker_open("backup") is False


# ─────────────────────────── Half-open recovery ────────────────────────────


def test_open_breaker_admits_exactly_one_probe(fake_redis, routed):
    model_router.get_store().open_breaker("primary", cooldown=60)

    first = slots(model_router.candidates())
    rest = [slots(model_router.candidates()) for _ in range(4)]

    # The token winner probes the primary; everyone else is served by backup.
    assert first == ["primary", "backup"]
    assert all(order == ["backup", "primary"] for order in rest)


def test_successful_probe_closes_breaker_and_clears_window(fake_redis, routed):
    for _ in range(3):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert model_router.get_store().breaker_open("primary") is True

    model_router.record_outcome("primary", outcome=model_router.OUTCOME_OK, ttft_ms=120)

    store = model_router.get_store()
    assert store.breaker_open("primary") is False
    # Stale bad samples must not immediately re-trip the recovered slot.
    assert store.samples("primary", window_size=4) == []


def test_failed_probe_keeps_breaker_open(fake_redis, routed):
    store = model_router.get_store()
    store.open_breaker("primary", cooldown=60)
    model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert store.breaker_open("primary") is True


def test_open_breaker_without_backup_is_cleared(fake_redis, routed, monkeypatch):
    """An open breaker with nowhere to go would strand every request."""
    model_router.get_store().open_breaker("primary", cooldown=60)
    monkeypatch.setattr(settings, "anthropic_backup_enabled", False)

    assert slots(model_router.candidates()) == ["primary"]
    assert model_router.get_store().breaker_open("primary") is False


def test_no_trip_while_no_backup_is_configured(fake_redis, routed, monkeypatch):
    """Routing on but no backup yet = the bake period. Measure, stay quiet.

    Tripping here would log "routing to backup" when there is no backup, and
    ``candidates`` would clear the breaker on the very next call anyway.
    """
    monkeypatch.setattr(settings, "anthropic_backup_enabled", False)

    for _ in range(6):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)

    store = model_router.get_store()
    assert store.samples("primary", window_size=4) == ["1"] * 4  # still measured
    assert store.breaker_open("primary") is False
    assert slots(model_router.candidates()) == ["primary"]


# ─────────────────────────── Redis degradation ─────────────────────────────


def test_redis_outage_degrades_without_raising(fake_redis, routed):
    fake_redis.fail = True

    # Every path must stay usable with Redis unreachable.
    assert slots(model_router.candidates()) == ["primary", "backup"]
    model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert isinstance(model_router.health_snapshot(), dict)


def test_local_fallback_still_trips(fake_redis, routed):
    """With no Redis the window is per-process, but it must still work."""
    model_router.reset_store_for_tests(None)
    store = model_router.get_store()
    # Force the lazy client to resolve to None instead of a real connection.
    store._client = None
    store._client_built = True

    for _ in range(3):
        model_router.record_outcome("primary", outcome=model_router.OUTCOME_TIMEOUT)
    assert store.breaker_open("primary") is True


# ─────────────────────────── Admin snapshot ────────────────────────────────


def test_health_snapshot_reports_serving_slot(fake_redis, routed):
    snap = model_router.health_snapshot()
    assert snap["enabled"] is True
    assert snap["serving_slot"] == "primary"
    assert snap["slots"]["primary"]["configured"] is True
    assert snap["slots"]["backup"]["provider"] == "deepseek"

    model_router.get_store().open_breaker("primary", cooldown=60)
    snap = model_router.health_snapshot()
    assert snap["primary_breaker_open"] is True
    assert snap["serving_slot"] == "backup"
    assert isinstance(snap["breaker_opened_at"], int)
