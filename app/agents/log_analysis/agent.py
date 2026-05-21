"""
Claude Agent SDK 日志分析 Agent。

主入口:
  LogAnalysisAgent().run(ctx)      — async, returns dict
  LogAnalysisAgent().run_sync(ctx) — sync wrapper for Celery

两个入口都可选注入 ``trace_emitter``，在 SDK loop 内部按消息粒度向外推送
``AgentTraceEvent`` (见 ``trace.py``)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

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
from app.agents.log_analysis.workspace import WorkspaceContext

logger = logging.getLogger(__name__)


class AgentCancelled(Exception):
    """Raised inside the agent loop when an external cancel signal fires."""


PROJECT_REPO_MCP_TOOL = "mcp__project_repo__lookup_project_repo"

ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Grep",
    "Glob",
    "Skill",  # 允许模型调用通过 setting_sources 加载的用户自定义 Skill
    PROJECT_REPO_MCP_TOOL,
]

# Agent 唯一键，与 skills_service.SUPPORTED_AGENTS 对应
AGENT_KEY = "log_analysis"


TraceEmitter = Callable[[AgentTraceEvent], None]


def _extract_fenced_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract and parse the first ```json ... ``` block from text."""
    pattern = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
    m = pattern.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _validate_result_schema(data: Dict[str, Any]) -> bool:
    # `answer` and `question_type` are part of the v3 schema. They are
    # checked softly (the agent is instructed to emit them, but legacy
    # responses without them are still accepted so we can fall back to
    # `summary`).
    required = {"status", "summary", "severity", "root_cause_hypotheses",
                "recommended_actions", "related_keywords"}
    return required.issubset(data.keys())


_VALID_QUESTION_TYPES = {"root_cause", "qa", "search", "stats", "meta", "other"}


def _normalize_question_type(value: Any) -> str:
    if isinstance(value, str) and value.strip().lower() in _VALID_QUESTION_TYPES:
        return value.strip().lower()
    return "other"


def _strip_confidence_fields(value: Any) -> Any:
    """Remove confidence scores from model output before persisting or returning it."""
    if isinstance(value, list):
        return [_strip_confidence_fields(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_confidence_fields(item)
            for key, item in value.items()
            if key != "confidence"
        }
    return value


_WORKFLOW_LOG_LIMIT = 600


def _truncate_for_log(text: str, limit: int = _WORKFLOW_LOG_LIMIT) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


def _tool_result_to_text(content: Any) -> str:
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text", "")))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _accumulate_token_usage(usage: Any, token_usage: Dict[str, int]) -> None:
    if not usage:
        return
    token_usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
    token_usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
    token_usage["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0


def _log_workflow(task_id: str, event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    logger.info("LogAnalysisAgent workflow task_id=%s %s", task_id, " ".join(parts))


# ───────────────────────── trace state machine ─────────────────────────


class _RunState:
    """Mutable state shared across all SDK message handlers for one run.

    Owns the seq counter, the accumulated ``trace_events`` list, in-flight
    step bookkeeping, token usage accumulator, and the final result text.
    """

    __slots__ = (
        "task_id",
        "emitter",
        "seq_counter",
        "trace_events",
        "active_step_ids",
        "tool_use_id_to_step",
        "step_started_at",
        "token_usage",
        "final_text",
        "cancel_notice_sent",
    )

    def __init__(self, task_id: str, emitter: Optional[TraceEmitter]) -> None:
        self.task_id = task_id
        self.emitter = emitter
        self.seq_counter = SeqCounter()
        self.trace_events: List[AgentTraceEvent] = []
        # FIFO of step_ids that have step_start but no step_end yet.
        # Used as the positional fallback when a tool_result lacks tool_use_id.
        self.active_step_ids: List[str] = []
        # Map SDK tool_use id → trace step_id so subsequent tool_result blocks
        # can correlate without relying on positional ordering.
        self.tool_use_id_to_step: Dict[str, str] = {}
        # step_id → monotonic start time, popped on step_end for duration calc.
        self.step_started_at: Dict[str, float] = {}
        self.token_usage: Dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
        }
        self.final_text: str = ""
        self.cancel_notice_sent = False

    def emit(self, event: AgentTraceEvent) -> None:
        """Append to internal buffer and notify external emitter (if any)."""
        self.trace_events.append(event)
        safe_emit(self.emitter, event)


def _emit_step_start(
    state: _RunState,
    *,
    tool_name: str,
    tool_input: Any,
    tool_use_id: Optional[str] = None,
) -> str:
    step_id = new_step_id()
    state.active_step_ids.append(step_id)
    state.step_started_at[step_id] = time.monotonic()
    if isinstance(tool_use_id, str) and tool_use_id:
        state.tool_use_id_to_step[tool_use_id] = step_id

    if isinstance(tool_input, dict):
        masked_input = mask_input(tool_input)
    elif tool_input is None:
        masked_input = {}
    else:
        masked_input = {"value": mask_input(tool_input)}

    state.emit(
        build_event(
            STEP_START,
            task_id=state.task_id,
            seq_counter=state.seq_counter,
            step_id=step_id,
            tool_name=str(tool_name or ""),
            tool_input=masked_input,
        )
    )
    return step_id


def _emit_step_end(
    state: _RunState,
    *,
    step_id: str,
    output_text: str,
    is_error: bool,
) -> None:
    started = state.step_started_at.pop(step_id, None)
    duration = max(0.0, time.monotonic() - started) if started is not None else 0.0
    masked = mask_tokens(output_text or "")

    for chunk in coerce_chunk(masked, DEFAULT_CHUNK_MAX_BYTES):
        state.emit(
            build_event(
                STEP_DELTA,
                task_id=state.task_id,
                seq_counter=state.seq_counter,
                step_id=step_id,
                output_chunk=chunk,
            )
        )

    state.emit(
        build_event(
            STEP_END,
            task_id=state.task_id,
            seq_counter=state.seq_counter,
            step_id=step_id,
            status="error" if is_error else "ok",
            output_excerpt=coerce_excerpt(masked, DEFAULT_EXCERPT_MAX_BYTES),
            duration_seconds=round(duration, 3),
        )
    )
    try:
        state.active_step_ids.remove(step_id)
    except ValueError:
        pass


def _emit_thinking_or_text(state: _RunState, text: str) -> None:
    """Emit one logical "thinking" unit (start → deltas → end) for a block.

    Per spec, both ``thinking`` blocks and assistant ``text`` blocks map to
    the ``thinking_*`` event family on the wire — the UI does not need to
    distinguish them.
    """
    if not text:
        return
    masked = mask_tokens(str(text))
    step_id = new_step_id()
    state.emit(
        build_event(
            THINKING_START,
            task_id=state.task_id,
            seq_counter=state.seq_counter,
            step_id=step_id,
        )
    )
    for chunk in coerce_chunk(masked, DEFAULT_CHUNK_MAX_BYTES):
        state.emit(
            build_event(
                THINKING_DELTA,
                task_id=state.task_id,
                seq_counter=state.seq_counter,
                step_id=step_id,
                text_chunk=chunk,
            )
        )
    state.emit(
        build_event(
            THINKING_END,
            task_id=state.task_id,
            seq_counter=state.seq_counter,
            step_id=step_id,
            text=coerce_excerpt(masked, DEFAULT_EXCERPT_MAX_BYTES * 4),
        )
    )


def _resolve_step_id_for_result(
    state: _RunState,
    tool_use_id: Optional[str],
) -> Optional[str]:
    """Find the step_id that this tool_result should close out.

    Prefer matching by ``tool_use_id`` (carried by the Anthropic SDK
    `ToolResultBlock`), fall back to the oldest unfinished step so order
    is preserved when the SDK does not propagate ids.
    """
    if isinstance(tool_use_id, str) and tool_use_id in state.tool_use_id_to_step:
        return state.tool_use_id_to_step.pop(tool_use_id)
    if state.active_step_ids:
        return state.active_step_ids[0]
    return None


def _emit_for_content_block(state: _RunState, block: Any) -> None:
    """Translate one assistant content block into trace events.

    Mirrors the dispatch order of the legacy ``_handle_content_block``:

    1. thinking block (has non-empty ``thinking`` attr)
    2. tool_result block (has ``tool_use_id``)
    3. tool_use block (has ``name`` + ``input``)
    4. assistant text block (has ``text``)
    """
    thinking = getattr(block, "thinking", None)
    if thinking:
        _log_workflow(
            state.task_id,
            "thinking",
            content=_truncate_for_log(mask_tokens(str(thinking))),
        )
        _emit_thinking_or_text(state, str(thinking))
        return

    tool_use_id = getattr(block, "tool_use_id", None)
    if tool_use_id is not None:
        content = getattr(block, "content", None)
        is_error = bool(getattr(block, "is_error", False))
        output_text = _tool_result_to_text(content)
        step_id = _resolve_step_id_for_result(state, tool_use_id)
        # Map step_id to a logging-friendly tool name (legacy expectation).
        tool_name = ""
        for past in reversed(state.trace_events):
            if past.get("type") == STEP_START and past.get("step_id") == step_id:
                tool_name = str(past.get("tool_name") or "")
                break
        _log_workflow(
            state.task_id,
            "tool_result",
            tool=tool_name or str(tool_use_id),
            status="error" if is_error else "ok",
            output=_truncate_for_log(mask_tokens(output_text)),
        )
        if step_id is None:
            state.emit(
                build_event(
                    SYSTEM_NOTICE,
                    task_id=state.task_id,
                    seq_counter=state.seq_counter,
                    kind="orphan_tool_result",
                    detail=coerce_excerpt(mask_tokens(output_text), 256),
                )
            )
            return
        _emit_step_end(
            state,
            step_id=step_id,
            output_text=output_text,
            is_error=is_error,
        )
        return

    name = getattr(block, "name", None)
    tool_input = getattr(block, "input", None)
    if name and tool_input is not None:
        block_id = getattr(block, "id", None)
        _log_workflow(
            state.task_id,
            "tool_call",
            tool=str(name),
            input=_truncate_for_log(
                mask_tokens(json.dumps(mask_input(tool_input), ensure_ascii=False))
                if isinstance(tool_input, (dict, list))
                else mask_tokens(str(tool_input))
            ),
        )
        _emit_step_start(
            state,
            tool_name=str(name),
            tool_input=tool_input,
            tool_use_id=block_id if isinstance(block_id, str) else None,
        )
        return

    text = getattr(block, "text", None)
    if text:
        _log_workflow(
            state.task_id,
            "assistant_text",
            content=_truncate_for_log(mask_tokens(str(text))),
        )
        _emit_thinking_or_text(state, str(text))


def _emit_for_message(message: Any, *, state: _RunState) -> None:
    """Top-level dispatch — one SDK message → 0..N trace events.

    Side-effects:
      - emits events through ``state.emit`` (which appends + notifies emitter)
      - accumulates token usage on ``state.token_usage``
      - sets ``state.final_text`` on terminal ResultMessage
      - writes structured workflow logs (legacy behaviour preserved)
    """
    content = getattr(message, "content", None)
    if isinstance(content, list) and content:
        for block in content:
            _emit_for_content_block(state, block)
        _accumulate_token_usage(getattr(message, "usage", None), state.token_usage)
        return

    # Older SDK shape: `tool_uses` / `tool_results` attributes on the message.
    if hasattr(message, "tool_uses") and message.tool_uses:
        for tool_use in message.tool_uses or []:
            name = getattr(tool_use, "name", "")
            tool_input = getattr(tool_use, "input", {})
            block_id = getattr(tool_use, "id", None)
            _log_workflow(
                state.task_id,
                "tool_call",
                tool=str(name),
                input=_truncate_for_log(
                    mask_tokens(json.dumps(mask_input(tool_input), ensure_ascii=False))
                    if isinstance(tool_input, (dict, list))
                    else mask_tokens(str(tool_input))
                ),
            )
            _emit_step_start(
                state,
                tool_name=str(name),
                tool_input=tool_input,
                tool_use_id=block_id if isinstance(block_id, str) else None,
            )

    if hasattr(message, "usage"):
        _accumulate_token_usage(message.usage, state.token_usage)

    if hasattr(message, "tool_results") and message.tool_results:
        for tool_result in message.tool_results or []:
            content_text = _tool_result_to_text(getattr(tool_result, "content", None))
            tool_use_id = getattr(tool_result, "tool_use_id", None)
            is_error = bool(getattr(tool_result, "is_error", False))
            step_id = _resolve_step_id_for_result(state, tool_use_id)
            tool_name = ""
            if step_id is not None:
                for past in reversed(state.trace_events):
                    if past.get("type") == STEP_START and past.get("step_id") == step_id:
                        tool_name = str(past.get("tool_name") or "")
                        break
            _log_workflow(
                state.task_id,
                "tool_result",
                tool=tool_name or str(tool_use_id or ""),
                status="error" if is_error else "ok",
                output=_truncate_for_log(mask_tokens(content_text)),
            )
            if step_id is None:
                state.emit(
                    build_event(
                        SYSTEM_NOTICE,
                        task_id=state.task_id,
                        seq_counter=state.seq_counter,
                        kind="orphan_tool_result",
                        detail=coerce_excerpt(mask_tokens(content_text), 256),
                    )
                )
                continue
            _emit_step_end(
                state,
                step_id=step_id,
                output_text=content_text,
                is_error=is_error,
            )

    data = getattr(message, "data", None)
    subtype = getattr(message, "subtype", None)
    if isinstance(data, dict) and subtype:
        summary_text = data.get("summary") or data.get("description") or data.get("message")
        detail = coerce_excerpt(mask_tokens(str(summary_text or "")), 512) or None
        _log_workflow(
            state.task_id,
            "system",
            subtype=str(subtype),
            detail=_truncate_for_log(str(summary_text)) if summary_text else None,
        )
        state.emit(
            build_event(
                SYSTEM_NOTICE,
                task_id=state.task_id,
                seq_counter=state.seq_counter,
                subtype=str(subtype),
                detail=detail,
            )
        )

    raw_result = getattr(message, "result", None)
    if isinstance(raw_result, str) and raw_result:
        state.final_text = raw_result
        _log_workflow(
            state.task_id,
            "result",
            turns=getattr(message, "num_turns", None),
            stop_reason=getattr(message, "stop_reason", None),
            excerpt=_truncate_for_log(mask_tokens(raw_result)),
        )


def _emit_cancel_requested(state: _RunState) -> None:
    """Send the first half of the two-phase cancel signal, exactly once."""
    if state.cancel_notice_sent:
        return
    state.cancel_notice_sent = True
    state.emit(
        build_event(
            SYSTEM_NOTICE,
            task_id=state.task_id,
            seq_counter=state.seq_counter,
            kind="cancel_requested",
        )
    )


def _close_any_active_steps(state: _RunState, *, reason: str) -> None:
    """If the run ended with steps still in flight (cancel/error), close
    them with a synthetic step_end so the UI does not see orphan cards."""
    for step_id in list(state.active_step_ids):
        _emit_step_end(
            state,
            step_id=step_id,
            output_text=f"[interrupted: {reason}]",
            is_error=True,
        )


def _cancelled_result(
    *,
    model: str,
    duration: float,
    tool_trace: List[Dict[str, str]],
    token_usage: Dict[str, int],
    trace_events: List[AgentTraceEvent],
    trace_summary: Dict[str, Any],
    raw: str = "Agent cancelled by user",
) -> Dict[str, Any]:
    return {
        "engine": "claude-agent-sdk",
        "model": model,
        "schema_version": 3,
        "status": "cancelled",
        "error_kind": "cancelled",
        "question_type": "other",
        "answer": "本轮分析已被用户取消。",
        "summary": "本轮分析已被用户取消。",
        "severity": "info",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": [],
        "tool_trace": tool_trace,
        "trace_events": trace_events,
        "trace_summary": trace_summary,
        "raw": raw,
        "duration_seconds": round(duration, 2),
        "token_usage": token_usage,
    }


class LogAnalysisAgent:
    """Wraps Claude Agent SDK query() loop for log analysis tasks."""

    async def run(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Run the agent loop and return the structured result dict.

        Args:
            ctx: workspace context (paths + metadata).
            cancel_event: optional ``threading.Event`` checked between SDK
                messages. When set, the agent emits a ``cancel_requested``
                ``system_notice`` then raises ``AgentCancelled`` internally
                and finally emits a ``cancelled`` terminal event.
            trace_emitter: optional **synchronous** callback invoked once
                per ``AgentTraceEvent``. Exceptions inside the callback are
                caught and logged at warning level. Pass ``None`` (the
                default) for the legacy behaviour where events are still
                accumulated internally but no external sink is notified.
        """
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
        from app.agents.log_analysis.prompts import get_prompts, render_user_prompt
        from app.config import settings

        try:
            from claude_agent_sdk import query, AssistantMessage, ResultMessage  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
            ) from exc

        log_type = ctx.metadata.get("log_type")
        system_prompt, user_prompt_template = get_prompts(log_type)

        task_data: Dict[str, Any] = {}
        try:
            import json as _json
            from pathlib import Path
            task_data = _json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
        except Exception:
            pass

        # When the user explicitly selected a project repository on the
        # frontend, the backend writes repo_info into task.json with
        # source="user_selected_project_repo". The base system prompt
        # already makes cloning mandatory for every run; this block only
        # adds the extra signal that metadata.json discovery can be
        # skipped because repo_info is already authoritative.
        repo_info = task_data.get("repo_info") if isinstance(task_data, dict) else None
        user_selected_repo = (
            isinstance(repo_info, dict)
            and repo_info.get("source") == "user_selected_project_repo"
        )
        if user_selected_repo:
            system_prompt += (
                "\n\n## User-Selected Project Repository\n"
                "The user explicitly selected the project repository for this "
                "run. `task.json` already contains a fully-resolved "
                "`repo_info` (`clone_url`, `repo_url`, `default_branch`) — "
                "treat it as the authoritative source and skip metadata.json "
                "discovery / `project_code` lookup. Proceed directly to "
                "Step 4 (clone) and Step 5 (investigate). Cloning and using "
                "the source code is mandatory, as already stated in the "
                "base workflow.\n"
            )

        user_prompt = render_user_prompt(
            user_prompt_template,
            task_id=ctx.task_id,
            question=ctx.metadata.get("question") or task_data.get("question", ""),
            log_type=ctx.metadata.get("log_type") or task_data.get("log_type"),
            hints=task_data.get("hints", ""),
        )

        # Resolve effective model before run for logging & result
        provider = settings.anthropic_provider
        profile = PROVIDER_PROFILES.get(provider)
        effective_model = settings.anthropic_model or (profile.default_model if profile else "unknown")
        supports_mcp = bool(profile and profile.supports_mcp_server_tools)

        allowed_tools = list(ALLOWED_TOOLS)
        mcp_servers = None
        if supports_mcp:
            from app.agents.log_analysis.mcp_tools import get_mcp_server
            mcp_servers = {"project_repo": get_mcp_server()}
        else:
            allowed_tools = [
                name for name in allowed_tools if name != PROJECT_REPO_MCP_TOOL
            ]
            system_prompt += (
                "\n\n## Runtime Constraint\n"
                f"The active provider `{provider}` does not support MCP server tools. "
                "`mcp__project_repo__lookup_project_repo` is unavailable in this run. "
                "Use explicit repository fields or `repo_info` from `task.json` / "
                "`metadata.json` to resolve the repo. Source code consultation is "
                "still mandatory per the base workflow. If no explicit repository "
                "info exists anywhere, finish with "
                '`"status": "error", "error_kind": "project_repo_not_registered"`.'
            )
            logger.info(
                "LogAnalysisAgent: provider=%s does not support MCP; using repo_info fallback only",
                provider,
            )

        # 物化已启用 Skill 到 cwd/.claude/skills/<name>/，配合 setting_sources=["project"]
        # 让 Claude Agent SDK 通过官方约定自动加载 Skill
        materialized_skills: List[str] = []
        try:
            from app.services import skills_service
            materialized_skills = skills_service.materialize_enabled_skills(
                AGENT_KEY, ctx.temp_dir
            )
            if materialized_skills:
                logger.info(
                    "LogAnalysisAgent: loaded %d skill(s): %s",
                    len(materialized_skills),
                    ", ".join(materialized_skills),
                )
        except Exception as exc:
            logger.warning("LogAnalysisAgent: failed to materialize skills: %s", exc)

        setting_sources = ["project"] if materialized_skills else None

        options = build_options(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            cwd=ctx.temp_dir,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers,
            setting_sources=setting_sources,
        )

        state = _RunState(task_id=ctx.task_id, emitter=trace_emitter)
        start = time.monotonic()

        # run_start lifecycle event (and legacy log line).
        _log_workflow(ctx.task_id, "run_start", model=effective_model)
        state.emit(
            build_event(
                RUN_START,
                task_id=ctx.task_id,
                seq_counter=state.seq_counter,
                model=effective_model,
                provider=str(provider),
            )
        )

        try:
            async for message in query(prompt=user_prompt, options=options):
                if cancel_event is not None and cancel_event.is_set():
                    _log_workflow(ctx.task_id, "cancelled", reason="cancel_event_set")
                    _emit_cancel_requested(state)
                    raise AgentCancelled()
                _emit_for_message(message, state=state)

        except AgentCancelled:
            duration = time.monotonic() - start
            _log_workflow(
                ctx.task_id,
                "run_complete",
                status="cancelled",
                tool_calls=len(state.active_step_ids) + sum(
                    1 for ev in state.trace_events if ev.get("type") == STEP_END
                ),
                duration_s=round(duration, 2),
                tokens_in=state.token_usage["input_tokens"],
                tokens_out=state.token_usage["output_tokens"],
            )
            _close_any_active_steps(state, reason="cancelled")
            trace_summary = summarize(state.trace_events)
            state.emit(
                build_event(
                    CANCELLED,
                    task_id=ctx.task_id,
                    seq_counter=state.seq_counter,
                    trace_summary=trace_summary,
                )
            )
            return _cancelled_result(
                model=effective_model,
                duration=duration,
                tool_trace=derive_tool_trace(state.trace_events),
                token_usage=state.token_usage,
                trace_events=list(state.trace_events),
                trace_summary=trace_summary,
            )
        except asyncio.TimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - start
            _close_any_active_steps(state, reason="error")
            trace_summary = summarize(state.trace_events)
            state.emit(
                build_event(
                    ERROR,
                    task_id=ctx.task_id,
                    seq_counter=state.seq_counter,
                    error_kind=type(exc).__name__,
                    message=str(exc),
                    trace_summary=trace_summary,
                )
            )
            logger.exception("LogAnalysisAgent: run failed: %s", exc)
            raise

        final_text = state.final_text
        duration = time.monotonic() - start
        _log_workflow(
            ctx.task_id,
            "run_complete",
            status="finished",
            tool_calls=sum(1 for ev in state.trace_events if ev.get("type") == STEP_END),
            duration_s=round(duration, 2),
            tokens_in=state.token_usage["input_tokens"],
            tokens_out=state.token_usage["output_tokens"],
        )

        trace_summary = summarize(state.trace_events)
        state.emit(
            build_event(
                RUN_COMPLETE,
                task_id=ctx.task_id,
                seq_counter=state.seq_counter,
                trace_summary=trace_summary,
                final_text=coerce_excerpt(mask_tokens(final_text), DEFAULT_EXCERPT_MAX_BYTES * 4),
            )
        )

        parsed = _extract_fenced_json(final_text)
        tool_trace = derive_tool_trace(state.trace_events)
        common_extra = {
            "tool_trace": tool_trace,
            "trace_events": list(state.trace_events),
            "trace_summary": trace_summary,
            "raw": final_text,
            "duration_seconds": round(duration, 2),
            "token_usage": state.token_usage,
        }

        if parsed is None:
            logger.warning("LogAnalysisAgent: no fenced JSON in result, schema_mismatch")
            return {
                "engine": "claude-agent-sdk",
                "model": effective_model,
                "schema_version": 3,
                "status": "schema_mismatch",
                "question_type": "other",
                "answer": "",
                "summary": "",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                **common_extra,
            }

        if not _validate_result_schema(parsed):
            logger.warning("LogAnalysisAgent: result JSON missing required fields, schema_mismatch")
            return {
                "engine": "claude-agent-sdk",
                "model": effective_model,
                "schema_version": 3,
                "status": "schema_mismatch",
                "question_type": "other",
                "answer": "",
                "summary": "",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                **common_extra,
            }

        status = parsed.get("status", "ok")
        error_kind = parsed.get("error_kind")

        if error_kind:
            status = "error"

        question_type = _normalize_question_type(parsed.get("question_type"))
        answer = parsed.get("answer", "") or ""
        summary = parsed.get("summary", "") or ""
        # Backward-compat fallback: if the model omitted `answer` (older
        # response shape) but did fill `summary`, expose summary as the
        # answer so the UI still has a question-facing response.
        if not answer and summary:
            answer = summary

        return {
            "engine": "claude-agent-sdk",
            "model": effective_model,
            "schema_version": 3,
            "status": status,
            "error_kind": error_kind,
            "question_type": question_type,
            "answer": answer,
            "summary": summary,
            "severity": parsed.get("severity", "info"),
            "root_cause_hypotheses": _strip_confidence_fields(
                parsed.get("root_cause_hypotheses", [])
            ),
            "recommended_actions": parsed.get("recommended_actions", []),
            "related_keywords": parsed.get("related_keywords", []),
            **common_extra,
        }

    def run_sync(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for Celery tasks. Applies request timeout."""
        from app.config import settings

        timeout = settings.anthropic_request_timeout_seconds

        try:
            return asyncio.run(
                asyncio.wait_for(
                    self.run(ctx, cancel_event=cancel_event, trace_emitter=trace_emitter),
                    timeout=float(timeout),
                )
            )
        except asyncio.TimeoutError:
            logger.error("LogAnalysisAgent: timed out after %ds", timeout)
            return {
                "engine": "claude-agent-sdk",
                "model": "unknown",
                "schema_version": 3,
                "status": "error",
                "error_kind": "timeout",
                "question_type": "other",
                "answer": "",
                "summary": "",
                "severity": "error",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                "tool_trace": [],
                "trace_events": [],
                "trace_summary": {
                    "thought_duration_seconds": float(timeout),
                    "tool_call_count": 0,
                    "thinking_chars": 0,
                },
                "raw": f"Agent timed out after {timeout} seconds",
                "duration_seconds": float(timeout),
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            }
