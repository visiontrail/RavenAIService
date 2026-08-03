"""Human-in-the-loop 决策协调器（PermissionBroker）。

放在 ``app/agents/`` 顶层而不是某个 agent 目录下，因为它同时服务两类 HITL：

- **工具审批**（``device_agent/permissions.py`` 的 ``can_use_tool``）；
- **澄清提问**（``app/agents/clarification.py`` 的 ``AskUserQuestion``）——
  后者对全部对话型 Agent 生效，不再是 DeviceAgent 专属。

保持独立模块还能切断 ``clarification → device_agent → prompts → clarification``
的循环导入。``device_agent/permissions.py`` 仍 re-export ``PermissionBroker``，
旧 import 路径不受影响。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)

RiskLevel = Literal["read", "write", "destructive"]


@dataclass
class _PendingDecision:
    future: "asyncio.Future[Dict[str, Any]]"
    tool_name: str
    risk: RiskLevel
    # Loop that owns ``future``. Captured at open() time because the waiter and
    # the resolver do not always live in the same loop — see PermissionBroker.
    loop: Optional[asyncio.AbstractEventLoop] = None


class PermissionBroker:
    """Per-run HITL 决策协调器。

    生命周期与一次 ``DeviceAgent.run_stream`` 对齐：broker 创建 → 注册到
    ``AIChatService.permission_broker_registry[session_id]`` → 在 ``finally``
    中 :meth:`close` 解除注册并取消所有挂起的 Future。

    线程模型：等待方（agent loop）与裁决方（HTTP 端点）**不保证在同一个 event
    loop 中**。DeviceAgent 跑在 FastAPI 主 loop 上，二者同 loop；而
    log_analysis / project_expert / package_search 通过
    ``asyncio.to_thread → run_sync → asyncio.run`` 在独立线程的独立 loop 中运行，
    此时 HTTP 端点调用 :meth:`resolve` 属于跨 loop 写入。``asyncio.Future`` 不是
    线程安全的，直接 ``set_result`` 不会唤醒对端 loop。因此 :meth:`open` 记录
    Future 所属 loop，:meth:`resolve` / :meth:`cancel` 在跨 loop 时改用
    ``loop.call_soon_threadsafe``。
    """

    def __init__(self) -> None:
        self._pending: Dict[str, _PendingDecision] = {}
        self._closed = False
        # Guards ``_pending`` against concurrent access from the agent thread
        # (open) and the HTTP thread (resolve/cancel).
        self._lock = threading.Lock()

    # ---- request lifecycle -------------------------------------------------

    def open(self, request_id: str, *, tool_name: str, risk: str) -> "asyncio.Future[Dict[str, Any]]":
        """登记一个新的待裁决请求，返回等待方应 await 的 Future。

        ``risk`` 通常是 :data:`RiskLevel` 之一；澄清提问（AskUserQuestion）复用同一
        broker 时传入 ``"clarify"`` 仅作标记，不参与风险分级。
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("PermissionBroker has been closed")
            if request_id in self._pending:
                raise ValueError(f"duplicate permission request_id={request_id}")
            loop = asyncio.get_event_loop()
            future: "asyncio.Future[Dict[str, Any]]" = loop.create_future()
            self._pending[request_id] = _PendingDecision(
                future=future,
                tool_name=tool_name,
                risk=risk,  # type: ignore[arg-type]
                loop=loop,
            )
        return future

    def open_clarification(self, request_id: str, *, tool_name: str = "AskUserQuestion") -> "asyncio.Future[Dict[str, Any]]":
        """澄清提问专用 open 包装：语义与 :meth:`open` 相同，``risk`` 固定为 ``"clarify"``。"""
        return self.open(request_id, tool_name=tool_name, risk="clarify")

    @staticmethod
    def _settle(entry: _PendingDecision, payload: Dict[str, Any]) -> bool:
        """Complete ``entry.future`` with ``payload``, from any thread/loop.

        When the caller is not running inside the loop that owns the future,
        the result is handed over via ``call_soon_threadsafe`` — a plain
        ``set_result`` from another thread does not wake the owning loop.
        """
        future = entry.future
        if future.done():
            return False

        owner = entry.loop
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:  # called from a plain (non-async) thread
            current = None

        # Direct set_result is correct when we are already on the owning loop,
        # and it is the *only* thing that can work when that loop is not running
        # (nothing would ever drain a call_soon_threadsafe callback).
        if owner is None or owner is current or not owner.is_running():
            try:
                future.set_result(payload)
            except asyncio.InvalidStateError:
                return False
            return True

        if owner.is_closed():
            return False

        def _apply() -> None:
            if not future.done():
                try:
                    future.set_result(payload)
                except asyncio.InvalidStateError:  # pragma: no cover - race
                    pass

        try:
            owner.call_soon_threadsafe(_apply)
        except RuntimeError:  # loop shut down between the check and the call
            return False
        return True

    def resolve(self, request_id: str, decision: Dict[str, Any]) -> bool:
        """HTTP 端点入口：把 ``{decision, updated_args?, message?}`` 塞回 Future。

        Returns:
            True：请求存在且成功 resolve；False：未知 request_id 或已被 resolve。
        """
        with self._lock:
            entry = self._pending.pop(request_id, None)
        if entry is None:
            return False
        return self._settle(entry, decision)

    def cancel(self, request_id: str, *, reason: str = "cancelled") -> bool:
        """取消一个挂起的请求（连接断开 / agent 整体超时时使用）。"""
        with self._lock:
            entry = self._pending.pop(request_id, None)
        if entry is None:
            return False
        return self._settle(entry, {"decision": "deny", "reason": reason})

    def close(self) -> None:
        """Run 结束时清理：把所有未 resolve 的 Future 标记为 deny。"""
        with self._lock:
            self._closed = True
            pending = list(self._pending.keys())
        for rid in pending:
            self.cancel(rid, reason="run_complete")

    def has(self, request_id: str) -> bool:
        return request_id in self._pending

    def __len__(self) -> int:
        return len(self._pending)


__all__ = ["PermissionBroker", "RiskLevel"]
