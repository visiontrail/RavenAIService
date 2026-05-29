"""GeneralAgent —— 默认通用对话 Agent（无工具调用，仅回答系统使用问题）。

当用户未选择任何特定 Agent 类型时走此路径。使用 ``ANTHROPIC_SMALL_FAST_MODEL``
模型，通过中文系统提示词限定模型回答范围为"系统如何使用"相关问题。

后续可在此基础上扩展默认 Agent 的功能（工具、知识库等）。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AGENT_KEY = "general_agent"

SYSTEM_PROMPT = """\
你是 Raven AI 系统的智能助手。你的职责是帮助用户了解和使用本系统的各项功能。

你可以回答的问题范围包括：
- 系统功能介绍与使用方法
- 设备管理与设备联动操作指南
- 日志分析功能的使用说明
- 包管理（Package）功能的使用方式
- 对话历史与会话管理
- 系统配置与常见问题排查

回答规则：
1. 使用中文回答所有问题。
2. 回答应简洁、准确、易于理解。
3. 如果用户的问题超出了系统使用范围（例如与本系统无关的通用知识问答），请礼貌地告知用户你是系统使用助手，并引导用户选择合适的功能模块：
   - 如需进行设备操作，请选择"设备操作"功能。
   - 如需进行日志分析，请选择"日志分析"功能。
4. 不要编造系统中不存在的功能。
5. 保持友好、专业的语气。
"""

# Sentinel pushed into the event queue to signal "no more events".
_SENTINEL: Any = object()

# 这是一个纯对话 Agent，不应使用任何工具。但 claude-agent-sdk 的 ``allowed_tools``
# 只是「自动批准」列表，并不会限制内置工具的可用性；叠加 ``bypassPermissions`` 后，
# CLI 自带的 Read/Bash/Grep 等工具仍可被模型调用。面对不相关的技术问题时，模型会
# 反复尝试用工具「检索/求证」，直至耗尽 max_turns 并由 SDK 抛错。故显式禁用全部内置
# 工具，使其只能直接以文本作答（单轮完成）。
_DISABLED_TOOLS: List[str] = [
    "Bash",
    "BashOutput",
    "KillBash",
    "Edit",
    "MultiEdit",
    "Write",
    "Read",
    "NotebookEdit",
    "NotebookRead",
    "Glob",
    "Grep",
    "LS",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
    "ExitPlanMode",
]

# 当模型未能产出有效文本（例如仍触达轮次上限）时使用的兜底回答。
_FALLBACK_ANSWER = (
    "我是 Raven AI 的系统使用助手，主要帮助你了解和使用本系统的各项功能。"
    "你的问题可能超出了系统使用范围，或需要更专门的能力支持：\n"
    "- 如需进行设备操作，请选择「设备操作」功能。\n"
    "- 如需进行日志分析，请选择「日志分析」功能。\n"
    "- 如需查询包信息，请选择「检索包」功能。\n"
    "请告诉我你想了解的系统功能，我会尽力帮助你。"
)


def _is_recoverable_turn_limit(exc: Exception) -> bool:
    """SDK 因达到最大轮次而抛出的「错误结果」属于可恢复情况。

    这类场景下模型通常已生成部分文本，应当回退到已收集内容而非整体失败。
    """
    msg = str(exc).lower()
    return "maximum number of turns" in msg or "max turns" in msg


@dataclass
class GeneralAgentContext:
    """单次 GeneralAgent.run_stream 输入。"""

    session_id: str
    user_message: str
    history: List[Dict[str, str]] = field(default_factory=list)
    system_prompt_override: Optional[str] = None
    run_id: Optional[str] = None
    owner_scope: Optional[str] = None


def _format_history_block(history: List[Dict[str, str]], max_turns: int) -> str:
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


def _resolve_small_fast_model() -> Optional[str]:
    from app.agents.anthropic_client import PROVIDER_PROFILES
    from app.config import settings

    if settings.anthropic_small_fast_model:
        return settings.anthropic_small_fast_model
    profile = PROVIDER_PROFILES.get(settings.anthropic_provider)
    if profile and profile.default_small_fast_model:
        return profile.default_small_fast_model
    return None


def _extract_text_from_messages(messages: list[Any]) -> str:
    out_parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                out_parts.append(text)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                out_parts.append(str(block["text"]))
    return "".join(out_parts)


class GeneralAgent:
    """默认通用对话 Agent：无工具，使用小/快模型回答系统使用问题。"""

    async def run_stream(self, ctx: GeneralAgentContext) -> AsyncIterator[Dict[str, Any]]:
        from app.agents.anthropic_client import AnthropicConfigurationError, build_options
        from app.config import settings

        try:
            from claude_agent_sdk import query as sdk_query
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
            ) from exc

        session_id = ctx.session_id or ""
        run_id = ctx.run_id or session_id or "general-agent"

        model = _resolve_small_fast_model()
        effective_model = model or "unknown"

        yield {
            "type": "run_start",
            "task_id": run_id,
            "model": effective_model,
            "agent_key": AGENT_KEY,
        }

        system_prompt = _compose_system_prompt(SYSTEM_PROMPT, ctx.system_prompt_override)

        max_history_turns = int(getattr(settings, "anthropic_max_history_turns", 10))
        history_block = _format_history_block(ctx.history, max_history_turns)

        user_prompt = ctx.user_message
        if history_block:
            user_prompt = f"<conversation_history>\n{history_block}\n</conversation_history>\n\n{ctx.user_message}"

        max_tokens = int(getattr(settings, "anthropic_small_fast_max_tokens", 1024))
        timeout_s = int(
            getattr(settings, "anthropic_small_fast_request_timeout_seconds", 30)
        )

        answer_text = ""
        try:
            with tempfile.TemporaryDirectory(prefix="general-agent-") as tmpdir:
                options = build_options(
                    system_prompt=system_prompt,
                    allowed_tools=[],
                    disallowed_tools=_DISABLED_TOOLS,
                    cwd=tmpdir,
                    max_turns=4,
                    permission_mode="bypassPermissions",
                    model=model,
                    max_tokens=max_tokens,
                    request_timeout_seconds=timeout_s,
                )

                # 收集到外层列表，确保即便 SDK 在中途抛错也能保留已产出的消息。
                collected: list[Any] = []

                async def _drive() -> None:
                    async for message in sdk_query(prompt=user_prompt, options=options):
                        collected.append(message)

                try:
                    await asyncio.wait_for(_drive(), timeout=max(timeout_s + 5, 10))
                except Exception as exc:  # noqa: BLE001
                    # 达到最大轮次属于可恢复：回退到已收集到的文本，避免整体失败。
                    if _is_recoverable_turn_limit(exc):
                        logger.warning(
                            "GeneralAgent: SDK 达到最大轮次，回退到已生成文本: %s", exc
                        )
                    else:
                        raise

                answer_text = _extract_text_from_messages(collected)

        except AnthropicConfigurationError as exc:
            yield {
                "type": "error",
                "task_id": run_id,
                "error_kind": "anthropic_misconfigured",
                "message": str(exc),
            }
            return
        except asyncio.TimeoutError:
            yield {
                "type": "error",
                "task_id": run_id,
                "error_kind": "timeout",
                "message": "GeneralAgent 响应超时",
            }
            return
        except Exception as exc:
            logger.exception("GeneralAgent: SDK query failed: %s", exc)
            yield {
                "type": "error",
                "task_id": run_id,
                "error_kind": type(exc).__name__,
                "message": str(exc),
            }
            return

        if not answer_text.strip():
            logger.warning(
                "GeneralAgent: 模型未产出有效文本，使用兜底回答 (session=%s)", session_id
            )
            answer_text = _FALLBACK_ANSWER

        yield {
            "type": "run_complete",
            "task_id": run_id,
            "final_text": answer_text,
            "model": effective_model,
        }

    async def run(self, ctx: GeneralAgentContext) -> Tuple[List[Dict[str, Any]], str, str]:
        events: List[Dict[str, Any]] = []
        final_text = ""
        model = ""
        async for ev in self.run_stream(ctx):
            events.append(ev)
            if ev.get("type") == "run_start" and ev.get("model"):
                model = str(ev.get("model") or "")
            if ev.get("type") == "run_complete" and ev.get("final_text"):
                final_text = str(ev.get("final_text") or "")
        return events, final_text, model


__all__ = ["GeneralAgent", "GeneralAgentContext", "AGENT_KEY"]
