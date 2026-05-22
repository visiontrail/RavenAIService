"""DeviceAgent 专属 trace 事件常量。

复用 ``app.agents.log_analysis.trace`` 的 ``AgentTraceEvent`` schema、
``SeqCounter``、``build_event``、``mask_*`` 等通用工具，本文件仅声明
DeviceAgent 独有的三类事件常量（详见 design.md Decision 11）：

- ``tool_permission_request``  — HITL 请求用户确认工具调用
- ``tool_permission_resolved`` — HITL 用户/超时给出结论
- ``result_validation``        — PostToolUse hook 校验结果

它们的字段 schema（``request_id`` / ``tool_name`` / ``args`` / ``risk`` /
``decision`` / ``status`` …）通过 ``build_event(**fields)`` 透传，未在
``AgentTraceEvent`` TypedDict 中显式列出的字段也允许携带，与 log_analysis 一致。
"""

from __future__ import annotations

from app.agents.log_analysis.trace import (  # noqa: F401  re-export for callers
    AgentTraceEvent,
    SeqCounter,
    build_event,
    coerce_chunk,
    coerce_excerpt,
    mask_input,
    mask_tokens,
    new_step_id,
    safe_emit,
    summarize,
)

# DeviceAgent-specific event type constants.
TOOL_PERMISSION_REQUEST = "tool_permission_request"
TOOL_PERMISSION_RESOLVED = "tool_permission_resolved"
RESULT_VALIDATION = "result_validation"


__all__ = [
    "AgentTraceEvent",
    "SeqCounter",
    "build_event",
    "coerce_chunk",
    "coerce_excerpt",
    "mask_input",
    "mask_tokens",
    "new_step_id",
    "safe_emit",
    "summarize",
    "TOOL_PERMISSION_REQUEST",
    "TOOL_PERMISSION_RESOLVED",
    "RESULT_VALIDATION",
]
