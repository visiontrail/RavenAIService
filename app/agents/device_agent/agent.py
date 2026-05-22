"""DeviceAgent —— 基于 Claude Agent SDK 的设备联动对话智能体主入口。

驱动 ``claude_agent_sdk.query()`` agent loop，将 SDK 消息流翻译为 :class:`AgentTraceEvent`
异步推给调用方（chat SSE / 非流式调用）。设计要点：

- 复用 ``app.agents.log_analysis.agent`` 的 ``_RunState`` / ``_emit_for_message`` 同款翻译
  机制（直接 import，不重复实现），保持与 LogAnalysisAgent 同构。
- 远端设备 MCP 工具 → in-process SDK 工具映射在 :mod:`mcp_tools` 实现，本类只组装。
- HITL ``can_use_tool`` 与 ``PostToolUse`` hook 分别在 :mod:`permissions` 与
  :mod:`post_tool_hook` 实现，本类负责创建 :class:`PermissionBroker` 并把它注册到外部
  ``broker_registry``（一般是 ``AIChatService.permission_broker_registry``）。
- workspace 仅在请求开始时按 session_id 准备临时目录，结束时幂等清理。

可调用入口：

- :py:meth:`DeviceAgent.run_stream` —— async generator，按 SDK 消息粒度 yield trace 事件
- :py:meth:`DeviceAgent.run`        —— 同步包装，聚合所有事件后返回 ``(events, final_text, model)``
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from app.agents.device_agent.mcp_tools import build_device_mcp_server
from app.agents.device_agent.permissions import PermissionBroker, make_can_use_tool
from app.agents.device_agent.post_tool_hook import build_post_tool_use_hook
from app.agents.device_agent.prompts import (
    get_prompts,
    get_risk_rules,
    render_user_prompt,
)
from app.agents.device_agent.trace import (
    AgentTraceEvent,
    SeqCounter,
    build_event,
    coerce_excerpt,
    mask_tokens,
    summarize,
)
from app.agents.device_agent import workspace as workspace_mod
from app.agents.log_analysis.agent import (
    _RunState,
    _close_any_active_steps,
    _emit_for_message,
)
from app.agents.log_analysis.trace import (
    DEFAULT_EXCERPT_MAX_BYTES,
    ERROR,
    RUN_COMPLETE,
    RUN_START,
)

logger = logging.getLogger(__name__)

AGENT_KEY = "device_agent"

# Sentinel pushed into the event queue to signal "no more events".
_SENTINEL: Any = object()


# ─────────────────────── Run Context ───────────────────────────────


@dataclass
class DeviceAgentContext:
    """单次 ``DeviceAgent.run_stream`` 输入。"""

    session_id: str
    user_message: str
    target_device_id: str
    target_device_name: Optional[str] = None
    # 最近 N 轮历史，按时间顺序，每条 ``{"role": "user"|"assistant", "content": str}``。
    # 由 ``AIChatService`` 从 ``chat_history_service`` 拉取后传入，已含本次用户消息之前
    # 的全部上下文；不要重复追加当前 user_message。
    history: List[Dict[str, str]] = field(default_factory=list)
    # 调用方可传入额外的 system prompt 段，会拼到 yaml ``system_prompt`` 之后。
    system_prompt_override: Optional[str] = None
    scene_hint: Optional[str] = None
    # 本轮 ``ChatAgentRun.id``；trace ``task_id`` 与 workspace 目录都基于它，保证不同 run
    # 的事件序列互不串扰。未提供时按 session_id 兜底（兼容单元测试 / 旧调用方）。
    run_id: Optional[str] = None
    # 归属作用域（user:<id> 或 anon:<token>）。 与 ``ChatRunJob.owner_scope`` 一致，
    # 用于工作区物理隔离，确保不同用户即使提交相同 session_id 也不共享 ``.claude/skills``。
    owner_scope: Optional[str] = None
    # broker 注册回调：``register(run_id, broker)`` / ``unregister(run_id)``。由
    # :class:`ChatRunService` 注入，使 HITL 端点可以按 ``run_id`` 找到 broker。
    # 为空时退化为本地 broker_registry 字典。
    broker_register: Optional[Callable[[str, PermissionBroker], None]] = None
    broker_unregister: Optional[Callable[[str], None]] = None
    # 共享 broker 注册表（旧字典风格）：``{session_id_or_run_id: PermissionBroker}``。
    # 当 ``broker_register`` 未提供时使用；保留兼容旧 ``AIChatService`` 调用方。
    broker_registry: Optional[Dict[str, PermissionBroker]] = None


# ─────────────────────── Helpers ───────────────────────────────────


def _format_history_block(history: List[Dict[str, str]], max_turns: int) -> str:
    """把历史消息拼成 ``[role] content`` 行格式。

    保留最近 ``max_turns`` 轮（一个 user/assistant 对算一轮，按数量 *2 截取）。
    """
    if not history:
        return ""
    limit = max(0, int(max_turns)) * 2 if max_turns else len(history)
    if limit and len(history) > limit:
        history = history[-limit:]
    lines: List[str] = []
    for entry in history:
        role = str(entry.get("role") or "user").strip().lower()
        if role in ("ai", "assistant"):
            role = "assistant"
        elif role == "system":
            role = "system"
        else:
            role = "user"
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{role}] {content}")
    return "\n\n".join(lines)


def _compose_system_prompt(base: str, override: Optional[str]) -> str:
    parts = [s for s in (base.strip() if base else "", override.strip() if override else "") if s]
    return "\n\n".join(parts) if parts else ""


def _resolve_device(target_device_id: str) -> Any:
    """同步入口：拉取 ``DeviceInfo``。失败时返回 ``None`` 让调用方走 graceful path。"""
    from app.services.device_link_service import device_link_manager

    try:
        # device_link_manager.get_device 是 async；调用方在 async 上下文中 await
        return device_link_manager.get_device(target_device_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DeviceAgent: failed to load device %s: %s", target_device_id, exc)
        return None


# ─────────────────────── Agent ─────────────────────────────────────


class DeviceAgent:
    """基于 Claude Agent SDK 的设备联动对话 agent。"""

    async def run_stream(self, ctx: DeviceAgentContext) -> AsyncIterator[AgentTraceEvent]:
        """驱动一次对话 ``query()`` 调用，按事件粒度 yield trace。

        生命周期：
        1. provider 检查（DeepSeek 拒绝）
        2. 创建 workspace + 物化 skills
        3. 拉取设备 + 构建 device MCP server + tool_meta_map
        4. 创建 PermissionBroker，注册到 broker_registry
        5. 构造 can_use_tool / post_tool_hook
        6. ``build_options(...)`` + ``async for message in query(...)``
        7. ``finally``: close broker, cleanup workspace
        """
        # Lazy imports keep CLI tools (alembic, etc.) loadable without the SDK.
        from app.agents.anthropic_client import (
            AnthropicConfigurationError,
            PROVIDER_PROFILES,
            build_options,
        )
        from app.config import settings

        try:
            from claude_agent_sdk import query  # noqa: F401
        except ImportError as exc:  # pragma: no cover - guarded at import time elsewhere
            raise RuntimeError(
                "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
            ) from exc

        session_id = ctx.session_id or ""
        # ``task_id`` is what every trace event carries; using ``run_id`` keeps
        # the seq spaces of concurrent runs in the same session isolated. Fall
        # back to ``session_id`` to remain backward-compatible with callers that
        # do not (yet) provide a run_id (unit tests, legacy chat endpoint).
        run_id = ctx.run_id or session_id or "device-agent"
        task_id = run_id
        broker_key = ctx.run_id or session_id

        # Event queue: producer = _drive_loop coroutine, consumer = this generator.
        queue: "asyncio.Queue[AgentTraceEvent]" = asyncio.Queue()

        def emit(event: AgentTraceEvent) -> None:
            try:
                queue.put_nowait(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DeviceAgent: queue put failed: %s", exc)

        seq_counter = SeqCounter()
        state = _RunState(task_id=task_id, emitter=emit)

        provider = settings.anthropic_provider
        profile = PROVIDER_PROFILES.get(provider)
        effective_model = (
            settings.anthropic_model
            or (profile.default_model if profile else "unknown")
        )

        # Emit run_start immediately so the UI sees the agent starting.
        emit(
            build_event(
                RUN_START,
                task_id=task_id,
                seq_counter=seq_counter,
                model=effective_model,
                provider=str(provider),
            )
        )

        # --- Provider capability gate ---------------------------------------
        if profile is None or not profile.supports_mcp_server_tools:
            emit(
                build_event(
                    ERROR,
                    task_id=task_id,
                    seq_counter=seq_counter,
                    error_kind="provider_no_mcp_support",
                    message=(
                        f"Active Anthropic provider '{provider}' does not support MCP server "
                        "tools; DeviceAgent cannot start. Switch to a provider with "
                        "supports_mcp_server_tools=True (e.g. 'anthropic')."
                    ),
                )
            )
            # Drain immediately and return.
            while not queue.empty():
                yield queue.get_nowait()
            return

        # --- Workspace + skills materialization -----------------------------
        workspace_path = None
        broker: Optional[PermissionBroker] = None
        runner: Optional[asyncio.Task] = None
        start_ts = time.monotonic()
        try:
            workspace_path = workspace_mod.prepare_session(
                session_id, run_id=ctx.run_id, owner_scope=ctx.owner_scope
            )

            materialized: List[str] = []
            try:
                from app.services import skills_service

                materialized = skills_service.materialize_enabled_skills(
                    AGENT_KEY, str(workspace_path)
                )
                if materialized:
                    logger.info(
                        "DeviceAgent: loaded %d skill(s): %s",
                        len(materialized),
                        ", ".join(materialized),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("DeviceAgent: failed to materialize skills: %s", exc)

            setting_sources = ["project"] if materialized else None

            # --- Resolve device + build MCP server --------------------------
            from app.services.device_link_service import device_link_manager

            try:
                device = await device_link_manager.get_device(ctx.target_device_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DeviceAgent: failed to resolve device %s: %s",
                    ctx.target_device_id,
                    exc,
                )
                device = None

            mcp_server, allowed_tools, tool_meta_map = build_device_mcp_server(
                device,
                session_id=session_id,
                target_device_id=ctx.target_device_id,
                emit=emit,
                seq_counter=seq_counter,
                task_id=task_id,
            )

            # Skill tool is always allowed so user-uploaded skills are discoverable.
            full_allowed = list(allowed_tools) + ["Skill"]

            # --- HITL broker + can_use_tool ---------------------------------
            broker = PermissionBroker()
            if ctx.broker_register is not None:
                try:
                    ctx.broker_register(run_id, broker)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("DeviceAgent: broker_register failed: %s", exc)
            elif ctx.broker_registry is not None and broker_key:
                ctx.broker_registry[broker_key] = broker

            risk_rules = get_risk_rules(ctx.scene_hint)
            timeout_s = float(
                getattr(settings, "device_agent_permission_timeout_seconds", 120)
            )
            can_use_tool = make_can_use_tool(
                broker,
                tool_meta_map,
                risk_rules,
                timeout_seconds=timeout_s,
                emit=emit,
                seq_counter=seq_counter,
                task_id=task_id,
                run_id=run_id,
                session_id=session_id,
            )

            # --- PostToolUse hook -------------------------------------------
            excerpt_bytes = int(
                getattr(settings, "device_agent_result_excerpt_bytes", 16 * 1024)
            )
            max_bytes = int(
                getattr(settings, "device_agent_result_max_bytes", 256 * 1024)
            )
            post_hook = build_post_tool_use_hook(
                tool_meta_map,
                excerpt_bytes=excerpt_bytes,
                max_bytes=max_bytes,
                emit=emit,
                seq_counter=seq_counter,
                task_id=task_id,
            )

            # --- Compose prompts --------------------------------------------
            base_system, user_template = get_prompts(ctx.scene_hint)
            system_prompt = _compose_system_prompt(base_system, ctx.system_prompt_override)

            max_history_turns = int(
                getattr(settings, "anthropic_max_history_turns", 10)
            )
            history_block = _format_history_block(ctx.history, max_history_turns)
            user_prompt = render_user_prompt(
                user_template,
                user_message=ctx.user_message,
                history_block=history_block,
                target_device_id=ctx.target_device_id or "",
                target_device_name=ctx.target_device_name or "",
                session_id=session_id,
            )

            # --- Build options ----------------------------------------------
            try:
                options = build_options(
                    system_prompt=system_prompt,
                    allowed_tools=full_allowed,
                    cwd=str(workspace_path),
                    permission_mode="default",
                    mcp_servers={"device": mcp_server} if mcp_server is not None else None,
                    setting_sources=setting_sources,
                    can_use_tool=can_use_tool,
                    hooks={"PostToolUse": [post_hook]},
                )
            except AnthropicConfigurationError as exc:
                emit(
                    build_event(
                        ERROR,
                        task_id=task_id,
                        seq_counter=seq_counter,
                        error_kind="anthropic_misconfigured",
                        message=str(exc),
                    )
                )
                # Drain whatever was queued and stop.
                while not queue.empty():
                    yield queue.get_nowait()
                return

            # --- Drive query() in a background task -------------------------
            from claude_agent_sdk import query as sdk_query

            async def _drive() -> None:
                try:
                    async for message in sdk_query(prompt=user_prompt, options=options):
                        _emit_for_message(message, state=state)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("DeviceAgent: SDK query failed: %s", exc)
                    _close_any_active_steps(state, reason="error")
                    emit(
                        build_event(
                            ERROR,
                            task_id=task_id,
                            seq_counter=seq_counter,
                            error_kind=type(exc).__name__,
                            message=str(exc),
                        )
                    )
                finally:
                    queue.put_nowait(_SENTINEL)

            runner = asyncio.create_task(_drive())

            # --- Pump events to consumer ------------------------------------
            while True:
                event = await queue.get()
                if event is _SENTINEL:
                    break
                yield event

            # After SDK loop ends, decide whether to emit run_complete.
            final_text = state.final_text or ""
            # Don't emit run_complete if an error event was already emitted.
            had_error = any(
                isinstance(ev, dict) and ev.get("type") == ERROR for ev in state.trace_events
            )
            if not had_error:
                trace_summary = summarize(state.trace_events)
                complete = build_event(
                    RUN_COMPLETE,
                    task_id=task_id,
                    seq_counter=seq_counter,
                    trace_summary=trace_summary,
                    final_text=coerce_excerpt(
                        mask_tokens(final_text),
                        DEFAULT_EXCERPT_MAX_BYTES * 4,
                    ),
                )
                state.trace_events.append(complete)
                yield complete

            duration = time.monotonic() - start_ts
            logger.info(
                "DeviceAgent run_complete: session=%s model=%s duration_s=%.2f "
                "tokens_in=%d tokens_out=%d tools=%d",
                session_id,
                effective_model,
                duration,
                state.token_usage["input_tokens"],
                state.token_usage["output_tokens"],
                len(tool_meta_map),
            )
        except asyncio.CancelledError:
            # Consumer cancelled (e.g. SSE client disconnected) — propagate after cleanup.
            logger.info("DeviceAgent run_stream cancelled: session=%s", session_id)
            raise
        finally:
            if runner is not None and not runner.done():
                runner.cancel()
                try:
                    await runner
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            if broker is not None:
                broker.close()
                if ctx.broker_unregister is not None:
                    try:
                        ctx.broker_unregister(run_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("DeviceAgent: broker_unregister failed: %s", exc)
                elif ctx.broker_registry is not None and broker_key:
                    ctx.broker_registry.pop(broker_key, None)
            if workspace_path is not None:
                workspace_mod.cleanup(workspace_path)

    async def run(self, ctx: DeviceAgentContext) -> Tuple[List[AgentTraceEvent], str, str]:
        """Non-streaming wrapper: drain all events, return ``(events, final_text, model)``.

        Used by the non-streaming ``POST /chat`` endpoint when the front-end only needs
        the final text. The same trace events are still produced (and persisted in the
        returned list) so callers can render or log them after the fact.
        """
        events: List[AgentTraceEvent] = []
        final_text = ""
        model = ""
        async for ev in self.run_stream(ctx):
            events.append(ev)
            if isinstance(ev, dict):
                if ev.get("type") == RUN_START and ev.get("model"):
                    model = str(ev.get("model") or "")
                if ev.get("type") == RUN_COMPLETE and ev.get("final_text"):
                    final_text = str(ev.get("final_text") or "")
        return events, final_text, model


__all__ = ["DeviceAgent", "DeviceAgentContext", "AGENT_KEY"]
