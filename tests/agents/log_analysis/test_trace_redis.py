"""Tests for app/services/agent_trace_redis.py.

Uses a hand-rolled fake redis client (no fakeredis dep) since we only
exercise ``rpush``, ``ltrim``, ``expire``, ``lrange``, ``delete`` and the
``pipeline()`` chain.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.services.agent_trace_redis import (
    MAX_TRACE_EVENTS,
    TRACE_TTL_SECONDS,
    TraceBuffer,
)


class _FakePipeline:
    def __init__(self, client: "_FakeRedis") -> None:
        self.client = client
        self._ops: List[tuple] = []

    def rpush(self, key: str, value: str) -> "_FakePipeline":
        self._ops.append(("rpush", key, value))
        return self

    def ltrim(self, key: str, start: int, end: int) -> "_FakePipeline":
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self) -> List[Any]:
        results: List[Any] = []
        for op in self._ops:
            if op[0] == "rpush":
                self.client.lists.setdefault(op[1], []).append(op[2])
                results.append(len(self.client.lists[op[1]]))
            elif op[0] == "ltrim":
                _, key, start, end = op
                lst = self.client.lists.get(key, [])
                # Redis LTRIM keeps inclusive [start, end]; negative
                # indices count from the end.
                if start < 0:
                    start = max(0, len(lst) + start)
                if end < 0:
                    end = len(lst) + end
                self.client.lists[key] = lst[start : end + 1]
                results.append(True)
            elif op[0] == "expire":
                _, key, seconds = op
                self.client.ttls[key] = seconds
                results.append(True)
        self._ops.clear()
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: Dict[str, List[str]] = {}
        self.ttls: Dict[str, int] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)

    def lrange(self, key: str, start: int, end: int) -> List[str]:
        lst = list(self.lists.get(key, []))
        if end == -1:
            end = len(lst) - 1
        return lst[start : end + 1]

    def delete(self, key: str) -> int:
        existed = key in self.lists
        self.lists.pop(key, None)
        self.ttls.pop(key, None)
        return 1 if existed else 0


@pytest.fixture
def buffer():
    return TraceBuffer(redis_client=_FakeRedis())


def _make_event(seq: int, type_: str = "step_start") -> Dict[str, Any]:
    return {
        "type": type_,
        "task_id": "t",
        "seq": seq,
        "timestamp": 100.0 + seq,
        "step_id": f"step-{seq}",
    }


class TestWrite:
    def test_pipeline_appends_with_ttl_and_trim(self, buffer):
        buffer.write("t", _make_event(1))
        fake = buffer.client
        key = "ai_analysis:trace:t"
        assert len(fake.lists[key]) == 1
        assert fake.ttls[key] == TRACE_TTL_SECONDS
        # Round-trip JSON
        assert json.loads(fake.lists[key][0])["seq"] == 1

    def test_trim_caps_list_size(self, buffer):
        # Push MAX + 50 events; expect the oldest 50 to be dropped.
        for i in range(1, MAX_TRACE_EVENTS + 51):
            buffer.write("t", _make_event(i))
        events = buffer.read_all("t")
        assert len(events) == MAX_TRACE_EVENTS
        # First retained event is seq=51 (the first 50 were trimmed away).
        assert events[0]["seq"] == 51
        assert events[-1]["seq"] == MAX_TRACE_EVENTS + 50


class TestRead:
    def test_read_all_empty_for_missing_key(self, buffer):
        assert buffer.read_all("nonexistent") == []

    def test_read_all_returns_in_order(self, buffer):
        for i in range(1, 6):
            buffer.write("t", _make_event(i))
        events = buffer.read_all("t")
        assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]

    def test_iter_new_events_filters_by_seq(self, buffer):
        for i in range(1, 6):
            buffer.write("t", _make_event(i))
        new = list(buffer.iter_new_events("t", from_seq=3))
        assert [e["seq"] for e in new] == [4, 5]

    def test_iter_new_events_from_zero_returns_all(self, buffer):
        for i in range(1, 4):
            buffer.write("t", _make_event(i))
        new = list(buffer.iter_new_events("t", from_seq=0))
        assert [e["seq"] for e in new] == [1, 2, 3]


class TestFaultTolerance:
    def test_write_swallows_redis_errors(self):
        class _Boom:
            def pipeline(self):
                raise RuntimeError("redis down")

        buffer = TraceBuffer(redis_client=_Boom())
        # Should not raise.
        buffer.write("t", _make_event(1))

    def test_read_returns_empty_on_redis_error(self):
        class _Boom:
            def lrange(self, *args, **kwargs):
                raise RuntimeError("redis down")

        buffer = TraceBuffer(redis_client=_Boom())
        assert buffer.read_all("t") == []

    def test_no_client_is_noop(self):
        buffer = TraceBuffer(redis_client=None)
        # Force the lazy-build path to fail by patching the import inside.
        # Easier: simulate by explicitly clearing the built flag — the
        # public surface still must not crash on missing client.
        buffer._client = None
        buffer._client_built = True  # short-circuit lazy build
        buffer.write("t", _make_event(1))  # no-op
        assert buffer.read_all("t") == []


class TestDelete:
    def test_delete_removes_key(self, buffer):
        buffer.write("t", _make_event(1))
        assert buffer.read_all("t")
        buffer.delete("t")
        assert buffer.read_all("t") == []
