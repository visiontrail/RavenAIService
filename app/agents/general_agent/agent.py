"""GeneralAgent —— 默认通用对话 Agent（无工具调用，仅回答系统使用问题）。

当用户未选择任何特定 Agent 类型时走此路径。使用 ``ANTHROPIC_SMALL_FAST_MODEL``
模型，通过中文系统提示词限定模型回答范围为"系统如何使用"相关问题。

后续可在此基础上扩展默认 Agent 的功能（工具、知识库等）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

AGENT_KEY = "general_agent"

# 允许出现在 [[SUGGESTED_AGENT:<key>]] 标记里的合法专门 Agent key。``none``
# 表示"无需切换"，解析时会被归一化为 ``None``。
VALID_SUGGESTED_AGENTS: frozenset[str] = frozenset(
    {"device", "log_analysis", "package_search", "project_expert"}
)

# 末行结构化建议标记的匹配正则（大小写不敏感，容忍空白）。
_SUGGESTED_AGENT_RE = re.compile(
    r"\[\[\s*SUGGESTED_AGENT\s*:\s*([a-zA-Z_]+)\s*\]\]", re.IGNORECASE
)

SYSTEM_PROMPT = """\
你是 Raven AI 系统的「系统使用助手」兼「Agent 路由引导助手」。你有两项职责：
1. 解答用户关于"如何使用 Raven AI 系统"的问题；
2. 当用户的请求其实需要某个专门 Agent 才能完成时，明确告知用户必须先在上方选择对应的 Agent，并指出是哪一个。
除此之外的任何问题一律不回答。

【本系统的专门 Agent 及其职责】
- 「设备操作」(device)：对设备下发指令、设备联动、远程控制/重启/查询设备状态等实际操作。
- 「日志分析」(log_analysis)：上传日志归档后分析日志、排查报错、定位故障原因。
- 「检索包」(package_search)：查询/检索软件包信息、包版本、包依赖关系。
- 「项目专家」(project_expert)：针对某个已登记项目的源码答疑、定位某功能在哪实现、评估改动影响。

【对用户最新输入的判定与回应规则】
先把用户最新输入归入以下三类之一：

A 类 —— 询问"Raven AI 系统怎么用 / 有什么功能"（例如"日志分析怎么用""系统支持哪些功能"）
  → 简洁、准确地回答，不要编造系统中不存在的功能。

B 类 —— 实际需要某个专门 Agent 才能完成的任务（例如"帮我重启 X 设备""分析这份日志为什么报错""查一下 xxx 包的最新版本""这个项目的鉴权在哪里实现"）
  → **不要尝试自己执行，也不要臆测结果**。明确告诉用户：该需求需要使用「<对应 Agent 名称>」，**请先在上方选择该 Agent，然后再发送你的请求**。

C 类 —— 与本系统完全无关（通用知识、百科、闲聊、编程、写作、翻译等）
  → 使用下方固定拒答话术，引导用户选择合适的功能模块，不要给出任何实质性解答。

【固定拒答话术】（遇到 C 类问题时使用，可适当衔接，但不要解答原问题）
"抱歉，我是 Raven AI 的系统使用助手，只能解答与本系统功能和使用方法相关的问题，无法回答其他内容。

如果你有具体需求，可以在上方选择对应的功能模块：
- 设备相关操作 → 选择「设备操作」
- 日志分析 → 选择「日志分析」
- 包信息查询 → 选择「检索包」
- 项目源码答疑 → 选择「项目专家」

也欢迎直接问我本系统的使用方法。"

【结尾标记规则（必须严格遵守）】
- 你的每一次回复，**最后一行必须且只能是一个标记**：[[SUGGESTED_AGENT:key]]
- key 取值仅限：device、log_analysis、package_search、project_expert、none
- 当且仅当属于 B 类时，key 取对应专门 Agent；A 类与 C 类一律用 none。
- 标记必须单独成行，放在所有正文之后；正文中不要重复输出该标记，也不要对它做任何解释。

【其他规则】
1. 始终使用中文回答。
2. 语气友好、专业、简洁。
3. 当你在解释 Raven AI 系统功能、模块关系或使用流程，且用户要求流程图/交互图，或图形比文字更清楚时，可以使用 ` ```mermaid ` 代码块（如`flowchart` / `sequenceDiagram`）。如果简短文字或列表更清楚，则不必使用Mermaid。
4. 直接以文本作答，不需要也不允许调用任何工具。
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
    "- 如需针对某个项目源码答疑，请选择「项目专家」功能。\n"
    "请告诉我你想了解的系统功能，我会尽力帮助你。"
)


def _extract_suggested_agent(text: str) -> Tuple[str, Optional[str]]:
    """从模型回复中解析并剥离 ``[[SUGGESTED_AGENT:key]]`` 标记。

    返回 ``(clean_text, suggested)``：

    - ``suggested`` 取最后一个标记的 key（大小写不敏感归一化为小写）；当 key 为
      ``none``、非法值或缺失标记时为 ``None``。
    - ``clean_text`` 已剥离**全部**标记（不论出现在末行、中间还是重复），并清理
      由此产生的尾随空白，保证呈现给用户的正文不含任何标记片段。
    """
    if not text:
        return "", None

    matches = list(_SUGGESTED_AGENT_RE.finditer(text))
    suggested: Optional[str] = None
    if matches:
        key = matches[-1].group(1).strip().lower()
        if key in VALID_SUGGESTED_AGENTS:
            suggested = key

    clean_text = _SUGGESTED_AGENT_RE.sub("", text)
    # 标记被剥离后常残留空行/尾随空白，统一收尾。
    clean_text = clean_text.rstrip()
    return clean_text, suggested


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
    # 本轮活动语言，仅用于追加回复语言指令（general agent 暂无每语言提示词正文，
    # 沿用单一 ``SYSTEM_PROMPT`` 常量）。缺省时回退系统默认语言。
    locale: Optional[str] = None


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
        from app.agents.usage import accumulate_usage, new_token_usage
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
        provider = str(settings.anthropic_provider)
        start_ts = time.monotonic()

        yield {
            "type": "run_start",
            "task_id": run_id,
            "model": effective_model,
            "provider": provider,
            "agent_key": AGENT_KEY,
        }

        system_prompt = _compose_system_prompt(SYSTEM_PROMPT, ctx.system_prompt_override)
        # 末尾追加直白的回复语言指令，使回复语言随活动语言切换。
        from app.i18n.prompts import response_language_directive

        system_prompt = _compose_system_prompt(
            system_prompt, response_language_directive(ctx.locale)
        )

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
        token_usage = new_token_usage()
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
                        accumulate_usage(getattr(message, "usage", None), token_usage)

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

        # 解析并剥离结构化建议标记；正文（final_text）保证不含 [[SUGGESTED_AGENT:...]]。
        answer_text, suggested_agent = _extract_suggested_agent(answer_text)

        if not answer_text.strip():
            logger.warning(
                "GeneralAgent: 模型未产出有效文本，使用兜底回答 (session=%s)", session_id
            )
            answer_text = _FALLBACK_ANSWER
            # 兜底回答属于"无法定向"场景，不给出具体建议。
            suggested_agent = None

        yield {
            "type": "run_complete",
            "task_id": run_id,
            "final_text": answer_text,
            "model": effective_model,
            "provider": provider,
            "token_usage": dict(token_usage),
            "duration_seconds": round(time.monotonic() - start_ts, 3),
            "suggested_agent_type": suggested_agent,
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


__all__ = [
    "GeneralAgent",
    "GeneralAgentContext",
    "AGENT_KEY",
    "VALID_SUGGESTED_AGENTS",
    "_extract_suggested_agent",
]
