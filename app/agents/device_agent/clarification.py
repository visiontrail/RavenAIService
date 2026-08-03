"""Backwards-compatible alias for the shared clarification module.

AskUserQuestion started as a DeviceAgent-only feature, but the user preference
that drives it（「指令不清晰时允许 Agent 向我提问」）is global, so the
implementation now lives in :mod:`app.agents.clarification` and is shared by
every chat-facing agent. This module re-exports it unchanged so existing
imports (and tests) keep working.

New code should import from ``app.agents.clarification`` directly.
"""

from __future__ import annotations

from app.agents.clarification import (  # noqa: F401
    ASK_SDK_NAME,
    ASK_SERVER_NAME,
    ASK_TOOL_NAME,
    BUILTIN_ASK_TOOL_NAME,
    ClarificationPrefs,
    ClarificationRuntime,
    build_clarification_mcp_server,
    clarification_guidance,
    make_ask_user_question_tool,
    setup_clarification,
)

__all__ = [
    "ASK_SERVER_NAME",
    "ASK_TOOL_NAME",
    "ASK_SDK_NAME",
    "BUILTIN_ASK_TOOL_NAME",
    "ClarificationPrefs",
    "ClarificationRuntime",
    "clarification_guidance",
    "make_ask_user_question_tool",
    "build_clarification_mcp_server",
    "setup_clarification",
]
