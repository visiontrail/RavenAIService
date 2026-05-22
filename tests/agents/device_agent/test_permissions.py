"""Unit tests for app/agents/device_agent/permissions.py."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from app.agents.device_agent.mcp_tools import ToolMeta
from app.agents.device_agent.permissions import (
    PermissionBroker,
    classify_risk,
    make_can_use_tool,
)
from app.agents.device_agent.trace import (
    SeqCounter,
    TOOL_PERMISSION_REQUEST,
    TOOL_PERMISSION_RESOLVED,
)


def _meta(sdk_name: str, *, server: str = "task", tool: str = "list", risk=None) -> ToolMeta:
    return ToolMeta(
        sdk_name=sdk_name,
        server=server,
        tool=tool,
        description="",
        input_schema={"type": "object"},
        risk=risk,
    )


# ─────────────────────── classify_risk ────────────────────────────


class TestClassifyRisk:
    def test_meta_risk_wins(self):
        meta = _meta("mcp__device__task__delete", server="task", tool="delete", risk="read")
        assert classify_risk(meta.sdk_name, meta, [
            {"server": "*", "tool": "delete*", "risk": "destructive"},
        ]) == "read"

    def test_rules_match_when_meta_missing_risk(self):
        meta = _meta("mcp__device__task__upgrade", server="task", tool="upgrade")
        rules = [
            {"server": "*", "tool": "*list*", "risk": "read"},
            {"server": "*", "tool": "*upgrade*", "risk": "destructive"},
        ]
        assert classify_risk(meta.sdk_name, meta, rules) == "destructive"

    def test_first_matching_rule_wins(self):
        meta = _meta("mcp__device__task__list_status", server="task", tool="list_status")
        rules = [
            {"server": "*", "tool": "*list*", "risk": "read"},
            {"server": "*", "tool": "*status*", "risk": "write"},
        ]
        assert classify_risk(meta.sdk_name, meta, rules) == "read"

    def test_default_is_write(self):
        meta = _meta("mcp__device__task__unknown_op", server="task", tool="unknown_op")
        assert classify_risk(meta.sdk_name, meta, []) == "write"

    def test_works_without_meta(self):
        rules = [{"server": "*", "tool": "*list*", "risk": "read"}]
        assert classify_risk("mcp__device__task__list_bg", None, rules) == "read"
        assert classify_risk("mcp__device__task__delete", None, rules) == "write"


# ─────────────────────── PermissionBroker ─────────────────────────


class TestPermissionBroker:
    @pytest.mark.asyncio
    async def test_open_and_resolve(self):
        broker = PermissionBroker()
        future = broker.open("req-1", tool_name="x", risk="write")
        assert broker.has("req-1")

        async def resolver():
            await asyncio.sleep(0.01)
            assert broker.resolve("req-1", {"decision": "allow"}) is True

        asyncio.create_task(resolver())
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result == {"decision": "allow"}
        assert not broker.has("req-1")

    def test_resolve_unknown_returns_false(self):
        broker = PermissionBroker()
        assert broker.resolve("missing", {"decision": "allow"}) is False

    @pytest.mark.asyncio
    async def test_cancel_sets_deny(self):
        broker = PermissionBroker()
        future = broker.open("req-1", tool_name="x", risk="write")
        broker.cancel("req-1", reason="user_left")
        assert (await future) == {"decision": "deny", "reason": "user_left"}

    @pytest.mark.asyncio
    async def test_close_cancels_all_pending(self):
        broker = PermissionBroker()
        f1 = broker.open("a", tool_name="x", risk="write")
        f2 = broker.open("b", tool_name="y", risk="destructive")
        broker.close()
        assert (await f1)["decision"] == "deny"
        assert (await f2)["decision"] == "deny"
        with pytest.raises(RuntimeError):
            broker.open("c", tool_name="z", risk="write")


# ─────────────────────── can_use_tool ─────────────────────────────


class TestCanUseTool:
    def _make(self, broker, meta_map, rules, *, timeout=0.2):
        events: List[dict] = []
        seq = SeqCounter()
        cb = make_can_use_tool(
            broker,
            meta_map,
            rules,
            timeout_seconds=timeout,
            emit=events.append,
            seq_counter=seq,
            task_id="t1",
        )
        return cb, events

    @pytest.mark.asyncio
    async def test_read_short_circuits(self):
        meta = _meta("mcp__device__task__list", server="task", tool="list", risk="read")
        broker = PermissionBroker()
        cb, events = self._make(broker, {meta.sdk_name: meta}, [])
        result = await cb(meta.sdk_name, {"limit": 5}, None)
        assert result == {"behavior": "allow"}
        assert events == []  # 不发 request 事件

    @pytest.mark.asyncio
    async def test_destructive_full_flow(self):
        meta = _meta("mcp__device__task__delete", server="task", tool="delete", risk="destructive")
        broker = PermissionBroker()
        cb, events = self._make(broker, {meta.sdk_name: meta}, [], timeout=1.0)

        async def resolver():
            # 等 request 事件发出 → 模拟 HTTP 端点 resolve。
            for _ in range(50):
                if events:
                    break
                await asyncio.sleep(0.01)
            req_id = events[0]["request_id"]
            assert broker.resolve(req_id, {"decision": "allow"})

        asyncio.create_task(resolver())
        result = await cb(meta.sdk_name, {"id": 1}, None)
        assert result == {"behavior": "allow"}
        types = [e["type"] for e in events]
        assert types == [TOOL_PERMISSION_REQUEST, TOOL_PERMISSION_RESOLVED]
        assert events[1]["decision"] == "allow"

    @pytest.mark.asyncio
    async def test_updated_args_passthrough(self):
        meta = _meta("mcp__device__task__exec", server="task", tool="exec", risk="write")
        broker = PermissionBroker()
        cb, events = self._make(broker, {meta.sdk_name: meta}, [], timeout=1.0)

        async def resolver():
            for _ in range(50):
                if events:
                    break
                await asyncio.sleep(0.01)
            req_id = events[0]["request_id"]
            broker.resolve(req_id, {"decision": "allow", "updated_args": {"force": False}})

        asyncio.create_task(resolver())
        result = await cb(meta.sdk_name, {"force": True}, None)
        assert result == {"behavior": "allow", "updatedInput": {"force": False}}

    @pytest.mark.asyncio
    async def test_timeout_denies(self):
        meta = _meta("mcp__device__task__delete", server="task", tool="delete", risk="destructive")
        broker = PermissionBroker()
        cb, events = self._make(broker, {meta.sdk_name: meta}, [], timeout=0.05)
        result = await cb(meta.sdk_name, {}, None)
        assert result["behavior"] == "deny"
        assert "timeout" in result.get("message", "")
        types = [e["type"] for e in events]
        assert types == [TOOL_PERMISSION_REQUEST, TOOL_PERMISSION_RESOLVED]
        assert events[1]["reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_user_denies(self):
        meta = _meta("mcp__device__task__exec", server="task", tool="exec", risk="write")
        broker = PermissionBroker()
        cb, events = self._make(broker, {meta.sdk_name: meta}, [], timeout=1.0)

        async def resolver():
            for _ in range(50):
                if events:
                    break
                await asyncio.sleep(0.01)
            req_id = events[0]["request_id"]
            broker.resolve(req_id, {"decision": "deny", "message": "not safe right now"})

        asyncio.create_task(resolver())
        result = await cb(meta.sdk_name, {}, None)
        assert result == {"behavior": "deny", "message": "not safe right now"}
