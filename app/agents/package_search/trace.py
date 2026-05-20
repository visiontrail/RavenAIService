"""Trace helpers for the Package Search Agent.

We reuse the unified ``AgentTraceEvent`` schema from ``log_analysis.trace``
so the existing frontend trace renderer (``LogDetail.vue``) works against
this agent unchanged.
"""

from app.agents.log_analysis.trace import (
    AgentTraceEvent,
    CANCELLED,
    DEFAULT_CHUNK_MAX_BYTES,
    DEFAULT_EXCERPT_MAX_BYTES,
    ERROR,
    RUN_COMPLETE,
    RUN_START,
    STEP_DELTA,
    STEP_END,
    STEP_START,
    SYSTEM_NOTICE,
    THINKING_DELTA,
    THINKING_END,
    THINKING_START,
    SeqCounter,
    build_event,
    coerce_chunk,
    coerce_excerpt,
    derive_tool_trace,
    mask_input,
    mask_tokens,
    new_step_id,
    safe_emit,
    summarize,
)

__all__ = [
    "AgentTraceEvent",
    "CANCELLED",
    "DEFAULT_CHUNK_MAX_BYTES",
    "DEFAULT_EXCERPT_MAX_BYTES",
    "ERROR",
    "RUN_COMPLETE",
    "RUN_START",
    "STEP_DELTA",
    "STEP_END",
    "STEP_START",
    "SYSTEM_NOTICE",
    "THINKING_DELTA",
    "THINKING_END",
    "THINKING_START",
    "SeqCounter",
    "build_event",
    "coerce_chunk",
    "coerce_excerpt",
    "derive_tool_trace",
    "mask_input",
    "mask_tokens",
    "new_step_id",
    "safe_emit",
    "summarize",
]
