"""AskUserQuestion —— Agent 主动向用户澄清不清晰指令的 in-process MCP 工具。

与 ``permissions.py`` 的工具审批（HITL）同构：调用即阻塞 agent loop，发出
``clarification_request`` trace 事件，等待 HTTP 端点
``POST /chat/clarifications/{request_id}/resolve`` 把用户答案写回
:class:`PermissionBroker` 的 Future，随后把答案作为工具返回值回喂模型继续。

设计要点（详见 openspec design.md Decision 1/2/6/9）：

- **触发权归模型**：是否调用 ``AskUserQuestion`` 完全由模型决定；不清晰才问。
- **复用 broker**：同一 run 内 permission 与 clarification 共享一个
  :class:`PermissionBroker`；``request_id`` 全 UUID，互不串扰。
- **多问题**：一次调用支持 1..N 个问题，每问 2–4 预设选项 + 隐式自由输入。
- **超时**：等待时长由调用方传入（代码常量，默认 5 分钟）；超时行为
  ``on_timeout ∈ {cancel, continue}`` 决定取消本轮 run 还是让模型继续。
- **每轮上限**：``max_rounds`` 限制单次 run 的提问次数，达上限后直接返回提示。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agents.device_agent.permissions import PermissionBroker
from app.agents.device_agent.trace import (
    CLARIFICATION_REQUEST,
    CLARIFICATION_RESOLVED,
    SeqCounter,
    build_event,
    safe_emit,
)

logger = logging.getLogger(__name__)

ASK_SERVER_NAME = "ask"
ASK_TOOL_NAME = "AskUserQuestion"
ASK_SDK_NAME = f"mcp__{ASK_SERVER_NAME}__{ASK_TOOL_NAME}"

EmitFn = Callable[[Any], None]
CancelRunFn = Callable[[], None]


# ─────────────────────── Schema ────────────────────────────────────

_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "description": "要向用户澄清的一个或多个问题。",
            "items": {
                "type": "object",
                "properties": {
                    "header": {
                        "type": "string",
                        "description": "极短标签（≤12 字），用于 UI chip 展示。",
                    },
                    "question": {
                        "type": "string",
                        "description": "完整的问题文本。",
                    },
                    "multiSelect": {
                        "type": "boolean",
                        "description": "是否允许多选；缺省 false（单选）。",
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "description": "2–4 个预设选项；用户也可不选预设、自行输入。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "选项简短文本。"},
                                "description": {
                                    "type": "string",
                                    "description": "选项含义/影响说明。",
                                },
                            },
                            "required": ["label", "description"],
                        },
                    },
                },
                "required": ["header", "question", "options"],
            },
        }
    },
    "required": ["questions"],
}

_TOOL_DESCRIPTION = (
    "当用户指令不清晰（缺少关键参数、存在多种合理解读、目标对象/范围不明确）时，"
    "向用户提出一个或多个澄清问题，每个问题给出 2–4 个预设选项；用户也可自行输入。"
    "能够合理推断时不要调用本工具。调用会阻塞，直到用户作答后返回其选择。"
)


# ─────────────────────── Helpers ───────────────────────────────────


def _normalize_questions(raw: Any) -> List[Dict[str, Any]]:
    """把模型传入的 ``questions`` 规整成稳定结构；非法项被丢弃。"""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        header = str(item.get("header") or "").strip()
        multi = bool(item.get("multiSelect") or False)
        opts_raw = item.get("options")
        options: List[Dict[str, str]] = []
        if isinstance(opts_raw, list):
            for opt in opts_raw:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label") or "").strip()
                if not label:
                    continue
                options.append(
                    {"label": label, "description": str(opt.get("description") or "").strip()}
                )
        out.append(
            {
                "header": header,
                "question": question,
                "multiSelect": multi,
                "options": options,
            }
        )
    return out


def _wrap_text(text: str) -> Dict[str, Any]:
    """SDK 工具返回形态：``{"content":[{"type":"text","text":...}]}``。"""
    return {"content": [{"type": "text", "text": text}]}


def _format_answers(questions: List[Dict[str, Any]], answers: Any) -> str:
    """把用户答案渲染为结构化、人类可读的文本块回喂模型。"""
    by_index: Dict[int, Dict[str, Any]] = {}
    if isinstance(answers, list):
        for ans in answers:
            if not isinstance(ans, dict):
                continue
            try:
                idx = int(ans.get("question_index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = ans

    lines: List[str] = ["用户对澄清问题的回答："]
    for i, q in enumerate(questions):
        lines.append(f"{i + 1}. {q.get('question', '')}")
        ans = by_index.get(i) or {}
        selected = ans.get("selected_labels")
        labels = [str(s).strip() for s in selected if str(s).strip()] if isinstance(selected, list) else []
        custom = str(ans.get("custom_text") or "").strip()
        if labels:
            lines.append(f"   - 选择：{', '.join(labels)}")
        if custom:
            lines.append(f"   - 补充：{custom}")
        if not labels and not custom:
            lines.append("   - （未作答）")
    return "\n".join(lines)


# ─────────────────────── Tool factory ──────────────────────────────


def make_ask_user_question_tool(
    *,
    broker: PermissionBroker,
    timeout_seconds: float,
    on_timeout: str = "cancel",
    max_rounds: int = 5,
    cancel_run: Optional[CancelRunFn] = None,
    emit: Optional[EmitFn] = None,
    seq_counter: Optional[SeqCounter] = None,
    task_id: str = "",
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_decorator: Callable[..., Any],
) -> Any:
    """构造 ``AskUserQuestion`` 的 SDK 工具 proxy。

    Args:
        broker: 与 resolve 端点共享的 per-run broker。
        timeout_seconds: 用户作答等待时长（秒）。
        on_timeout: ``"cancel"`` 取消本轮 run；``"continue"`` 让模型基于已知信息继续。
        max_rounds: 单次 run 最多发起的 ``AskUserQuestion`` 次数。
        cancel_run: 取消本轮 run 的回调（``cancel`` 模式超时时调用）；缺省时降级为继续。
        emit/seq_counter/task_id/run_id/session_id: trace 事件上下文。
        tool_decorator: ``claude_agent_sdk.tool`` 装饰器（由调用方注入，便于测试）。
    """

    # Per-run 提问计数（闭包内可变）。
    counter: Dict[str, int] = {"count": 0}
    normalized_on_timeout = "continue" if str(on_timeout).strip().lower() == "continue" else "cancel"

    def _emit_request(request_id: str, questions: List[Dict[str, Any]]) -> None:
        if emit is None or seq_counter is None:
            return
        safe_emit(
            emit,
            build_event(
                CLARIFICATION_REQUEST,
                task_id=task_id,
                seq_counter=seq_counter,
                request_id=request_id,
                questions=questions,
                run_id=run_id,
                session_id=session_id,
            ),
        )

    def _emit_resolved(request_id: str, outcome: str, *, reason: Optional[str] = None) -> None:
        if emit is None or seq_counter is None:
            return
        safe_emit(
            emit,
            build_event(
                CLARIFICATION_RESOLVED,
                task_id=task_id,
                seq_counter=seq_counter,
                request_id=request_id,
                outcome=outcome,
                reason=reason,
                run_id=run_id,
                session_id=session_id,
            ),
        )

    @tool_decorator(ASK_TOOL_NAME, _TOOL_DESCRIPTION, _INPUT_SCHEMA)
    async def _ask(args):
        questions = _normalize_questions((args or {}).get("questions"))
        if not questions:
            return _wrap_text(
                "AskUserQuestion 未提供有效问题；请基于已知信息继续，不要重复调用。"
            )

        # 每轮提问上限：达上限后不再阻塞用户。
        if counter["count"] >= max(0, int(max_rounds)):
            logger.info(
                "AskUserQuestion: max rounds reached run_id=%s max=%s", run_id, max_rounds
            )
            return _wrap_text(
                f"已达到本轮提问上限（{max_rounds} 次）。请基于已知信息自行决断，"
                "不要再调用 AskUserQuestion。"
            )
        counter["count"] += 1

        request_id = str(uuid.uuid4())
        _emit_request(request_id, questions)

        try:
            future = broker.open_clarification(request_id)
        except RuntimeError as exc:
            logger.warning("AskUserQuestion: broker closed: %s", exc)
            _emit_resolved(request_id, "cancelled", reason="broker_closed")
            return _wrap_text("澄清通道不可用；请基于已知信息继续。")

        try:
            decision = await asyncio.wait_for(future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            broker.cancel(request_id, reason="timeout")
            if normalized_on_timeout == "continue" or cancel_run is None:
                _emit_resolved(request_id, "timeout", reason="timeout")
                return _wrap_text(
                    "用户未在限定时间内回答澄清问题；请基于已知信息给出最合理的处理"
                    "或最佳猜测，继续完成任务。"
                )
            # cancel 模式：取消本轮 run。
            _emit_resolved(request_id, "cancelled", reason="timeout")
            try:
                cancel_run()
            except Exception as exc:  # noqa: BLE001
                logger.warning("AskUserQuestion: cancel_run failed: %s", exc)
            return _wrap_text("用户未在限定时间内回答；本轮已取消。")
        except asyncio.CancelledError:
            broker.cancel(request_id, reason="cancelled")
            raise

        answers = decision.get("answers") if isinstance(decision, dict) else None
        _emit_resolved(request_id, "answered")
        return _wrap_text(_format_answers(questions, answers))

    return _ask


def build_clarification_mcp_server(
    *,
    broker: PermissionBroker,
    timeout_seconds: float,
    on_timeout: str = "cancel",
    max_rounds: int = 5,
    cancel_run: Optional[CancelRunFn] = None,
    emit: Optional[EmitFn] = None,
    seq_counter: Optional[SeqCounter] = None,
    task_id: str = "",
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[Any, str]:
    """构造 ``ask`` in-process MCP server，仅含 ``AskUserQuestion`` 工具。

    Returns:
        ``(server, sdk_tool_name)``：server 传给
        ``ClaudeAgentOptions.mcp_servers={"ask": server}``；``sdk_tool_name`` 为
        ``mcp__ask__AskUserQuestion``，调用方追加进 ``allowed_tools``。
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    proxy = make_ask_user_question_tool(
        broker=broker,
        timeout_seconds=timeout_seconds,
        on_timeout=on_timeout,
        max_rounds=max_rounds,
        cancel_run=cancel_run,
        emit=emit,
        seq_counter=seq_counter,
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        tool_decorator=tool,
    )
    server = create_sdk_mcp_server(name=ASK_SERVER_NAME, version="1.0.0", tools=[proxy])
    return server, ASK_SDK_NAME


__all__ = [
    "ASK_SERVER_NAME",
    "ASK_TOOL_NAME",
    "ASK_SDK_NAME",
    "make_ask_user_question_tool",
    "build_clarification_mcp_server",
]
