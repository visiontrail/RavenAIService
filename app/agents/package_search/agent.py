"""Claude Agent SDK driven Raven package search agent.

Drives one ``query()`` loop with the 7 in-process MCP tools defined in
``app.agents.package_search.mcp_tools``. Returns a structured response
with the recommended package IDs (validated against the metadata store),
along with the tool-call trace for the UI.

The agent has two entry points:

- ``run(query, session_id=None) -> dict`` — runs the SDK loop to
  completion and returns the structured result;
- ``stream(query, session_id=None)`` — async generator that yields
  ``AgentTraceEvent`` dicts in order, ending with a ``final`` event
  whose ``data`` is the same dict that ``run`` would return.

Both entry points share the same event-collection machinery so the
non-stream branch can simply consume the generator and discard the
intermediate events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from app.agents.package_search.trace import (
    AgentTraceEvent,
    ANSWER_DELTA,
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
    extract_text_delta,
    mask_input,
    mask_tokens,
    new_step_id,
    safe_emit,
    summarize,
)

logger = logging.getLogger(__name__)


# All MCP tool names are prefixed with ``mcp__package_search__`` by the SDK.
_MCP_PREFIX = "mcp__package_search__"

ALLOWED_TOOLS = [
    f"{_MCP_PREFIX}list_packages",
    f"{_MCP_PREFIX}get_package_by_id",
    f"{_MCP_PREFIX}search_packages_by_text",
    f"{_MCP_PREFIX}filter_packages_by_version",
    f"{_MCP_PREFIX}list_components",
    f"{_MCP_PREFIX}find_packages_by_component",
    f"{_MCP_PREFIX}package_stats",
]


TraceEmitter = Callable[[AgentTraceEvent], None]


# ──────────────────────── helpers ─────────────────────────

_FENCED_JSON_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def _extract_fenced_json(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract the first ```json ... ``` block.

    Returns ``(parsed_dict, error)``:
    - ``(dict, None)`` on success;
    - ``(None, "missing")`` if no fenced block;
    - ``(None, "unparsable")`` if JSON parsing fails or schema is invalid.
    """
    if not text:
        return None, "missing"
    match = _FENCED_JSON_RE.search(text)
    if not match:
        return None, "missing"
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None, "unparsable"
    if not isinstance(parsed, dict):
        return None, "unparsable"
    return parsed, None


def _coerce_id_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            out.append(str(item))
    return out


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


# ──────────────────────── run state ─────────────────────────


class _RunState:
    """Per-run state shared across the SDK message handlers."""

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
    )

    def __init__(self, task_id: str, emitter: Optional[TraceEmitter]) -> None:
        self.task_id = task_id
        self.emitter = emitter
        self.seq_counter = SeqCounter()
        self.trace_events: List[AgentTraceEvent] = []
        self.active_step_ids: List[str] = []
        self.tool_use_id_to_step: Dict[str, str] = {}
        self.step_started_at: Dict[str, float] = {}
        self.token_usage: Dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
        }
        self.final_text: str = ""

    def emit(self, event: AgentTraceEvent) -> None:
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
    if isinstance(tool_use_id, str) and tool_use_id in state.tool_use_id_to_step:
        return state.tool_use_id_to_step.pop(tool_use_id)
    if state.active_step_ids:
        return state.active_step_ids[0]
    return None


def _emit_for_content_block(state: _RunState, block: Any) -> None:
    thinking = getattr(block, "thinking", None)
    if thinking:
        _emit_thinking_or_text(state, str(thinking))
        return

    tool_use_id = getattr(block, "tool_use_id", None)
    if tool_use_id is not None:
        content = getattr(block, "content", None)
        is_error = bool(getattr(block, "is_error", False))
        output_text = _tool_result_to_text(content)
        step_id = _resolve_step_id_for_result(state, tool_use_id)
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
        _emit_step_end(state, step_id=step_id, output_text=output_text, is_error=is_error)
        return

    name = getattr(block, "name", None)
    tool_input = getattr(block, "input", None)
    if name and tool_input is not None:
        block_id = getattr(block, "id", None)
        _emit_step_start(
            state,
            tool_name=str(name),
            tool_input=tool_input,
            tool_use_id=block_id if isinstance(block_id, str) else None,
        )
        return

    text = getattr(block, "text", None)
    if text:
        # Capture the latest assistant text as the candidate final answer.
        state.final_text = str(text)
        _emit_thinking_or_text(state, str(text))


def _emit_answer_delta_from_stream(state: _RunState, message: Any) -> bool:
    """Translate a partial-streaming ``StreamEvent`` into ``answer_delta``.

    Returns ``True`` when ``message`` was a ``StreamEvent`` (handled here).
    Only ``content_block_delta`` text increments produce output.
    """
    event = getattr(message, "event", None)
    if not isinstance(event, dict):
        return False
    text = extract_text_delta(event)
    if text is None:
        return True
    masked = mask_tokens(text)
    for chunk in coerce_chunk(masked, DEFAULT_CHUNK_MAX_BYTES):
        state.emit(
            build_event(
                ANSWER_DELTA,
                task_id=state.task_id,
                seq_counter=state.seq_counter,
                text_chunk=chunk,
            )
        )
    return True


def _emit_for_message(message: Any, *, state: _RunState) -> None:
    # StreamEvent (include_partial_messages): has an ``event`` dict and no
    # ``content`` list — translate answer text increments into answer_delta.
    if getattr(message, "content", None) is None and isinstance(
        getattr(message, "event", None), dict
    ):
        _emit_answer_delta_from_stream(state, message)
        return

    content = getattr(message, "content", None)
    if isinstance(content, list) and content:
        for block in content:
            _emit_for_content_block(state, block)
        _accumulate_token_usage(getattr(message, "usage", None), state.token_usage)
        return

    if hasattr(message, "usage"):
        _accumulate_token_usage(message.usage, state.token_usage)

    raw_result = getattr(message, "result", None)
    if isinstance(raw_result, str) and raw_result:
        state.final_text = raw_result


def _close_any_active_steps(state: _RunState, *, reason: str) -> None:
    for step_id in list(state.active_step_ids):
        _emit_step_end(
            state,
            step_id=step_id,
            output_text=f"[interrupted: {reason}]",
            is_error=True,
        )


# ──────────────────────── tool_trace warnings ─────────────────────────


def _append_warning(tool_trace: List[Dict[str, Any]], message: str) -> None:
    tool_trace.append({"type": "warning", "message": message})


# ──────────────────────── PackageSearchAgent ─────────────────────────


class PackageSearchAgent:
    """Run the Claude Agent SDK loop for one user query.

    Tests that need to bypass the real SDK loop can monkeypatch
    ``self._run_sdk_loop`` to yield a curated sequence of messages.
    """

    async def _run_sdk_loop(
        self,
        prompt: str,
        options: Any,
    ) -> AsyncIterator[Any]:
        """Yield messages from the SDK loop. Overridden in tests."""
        try:
            from claude_agent_sdk import query  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
            ) from exc

        async for message in query(prompt=prompt, options=options):
            yield message

    def _build_options(self, *, system_prompt: str, max_turns: Optional[int] = None) -> Tuple[Any, str, str]:
        """Build ClaudeAgentOptions; return ``(options, model, provider)``."""
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
        from app.agents.package_search.mcp_tools import get_mcp_server
        from app.config import settings

        provider = settings.anthropic_provider
        profile = PROVIDER_PROFILES.get(provider)
        effective_model = settings.anthropic_model or (
            profile.default_model if profile else "unknown"
        )
        supports_mcp = bool(profile and profile.supports_mcp_server_tools)

        allowed_tools = list(ALLOWED_TOOLS)
        mcp_servers: Optional[Dict[str, Any]] = None
        if supports_mcp:
            mcp_servers = {"package_search": get_mcp_server()}
        else:
            # Provider has no MCP tool support — clear the allow-list so the
            # SDK doesn't complain about unknown tools. The agent can still
            # answer in degraded mode using its own knowledge, but the fenced
            # JSON will most likely come back empty.
            allowed_tools = []
            logger.warning(
                "PackageSearchAgent: provider=%s does not support MCP tools; "
                "running in degraded (no-tool) mode",
                provider,
            )

        effective_max_turns = max_turns if max_turns is not None else int(
            settings.package_search_max_turns
        )

        options = build_options(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            cwd=str(settings.base_dir),
            max_turns=effective_max_turns,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers,
        )
        return options, effective_model, str(provider)

    async def _drive(
        self,
        query_text: str,
        *,
        session_id: Optional[str],
        emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Inner loop shared by ``run`` and ``stream``."""
        from app.agents.package_search.prompts import SYSTEM_PROMPT
        from app.services.raven_package_service import raven_package_service

        task_id = session_id or f"pkgsearch-{uuid.uuid4()}"
        state = _RunState(task_id=task_id, emitter=emitter)

        options, effective_model, provider = self._build_options(system_prompt=SYSTEM_PROMPT)

        state.emit(
            build_event(
                RUN_START,
                task_id=task_id,
                seq_counter=state.seq_counter,
                model=effective_model,
                provider=provider,
            )
        )

        start = time.monotonic()
        try:
            async for message in self._run_sdk_loop(prompt=query_text, options=options):
                _emit_for_message(message, state=state)
        except Exception as exc:  # noqa: BLE001
            _close_any_active_steps(state, reason="error")
            trace_summary = summarize(state.trace_events)
            state.emit(
                build_event(
                    ERROR,
                    task_id=task_id,
                    seq_counter=state.seq_counter,
                    error_kind=type(exc).__name__,
                    message=str(exc),
                    trace_summary=trace_summary,
                )
            )
            logger.exception("PackageSearchAgent: run failed: %s", exc)
            raise

        duration = time.monotonic() - start
        trace_summary = summarize(state.trace_events)

        # ---- Structured-answer parsing & ID validation ----
        tool_trace = derive_tool_trace(state.trace_events)
        parsed, parse_error = _extract_fenced_json(state.final_text)
        recommended: List[str] = []
        relevant: List[str] = []
        notes: Optional[str] = None

        if parse_error == "missing":
            _append_warning(tool_trace, "missing structured answer")
        elif parse_error == "unparsable":
            _append_warning(tool_trace, "unparsable structured answer")
        elif parsed is not None:
            raw_recommended = _coerce_id_list(parsed.get("recommended_package_ids"))
            raw_relevant = _coerce_id_list(parsed.get("relevant_package_ids"))
            if (
                not isinstance(parsed.get("recommended_package_ids"), list)
                or not isinstance(parsed.get("relevant_package_ids"), list)
            ):
                _append_warning(tool_trace, "unparsable structured answer")
            else:
                # Validate IDs against the metadata store; filter unknown ones.
                def _validate(ids: List[str]) -> Tuple[List[str], int]:
                    keep: List[str] = []
                    seen: set[str] = set()
                    dropped = 0
                    for pid in ids:
                        if pid in seen:
                            continue
                        seen.add(pid)
                        if raven_package_service.get_package(pid) is not None:
                            keep.append(pid)
                        else:
                            dropped += 1
                    return keep, dropped

                recommended, dropped_r = _validate(raw_recommended)
                relevant, dropped_v = _validate(raw_relevant)
                total_dropped = dropped_r + dropped_v
                if total_dropped:
                    _append_warning(
                        tool_trace,
                        f"filtered {total_dropped} invalid ids",
                    )
                raw_notes = parsed.get("notes")
                if isinstance(raw_notes, str) and raw_notes.strip():
                    notes = raw_notes.strip()

        state.emit(
            build_event(
                RUN_COMPLETE,
                task_id=task_id,
                seq_counter=state.seq_counter,
                trace_summary=trace_summary,
                final_text=coerce_excerpt(
                    mask_tokens(state.final_text), DEFAULT_EXCERPT_MAX_BYTES * 4
                ),
            )
        )

        return {
            "answer": state.final_text or "",
            "recommended_package_ids": recommended,
            "relevant_package_ids": relevant,
            "notes": notes,
            "tool_trace": tool_trace,
            "trace_events": list(state.trace_events),
            "trace_summary": trace_summary,
            "model": effective_model,
            "provider": provider,
            "usage": dict(state.token_usage),
            "duration_seconds": round(duration, 2),
            "session_id": task_id,
        }

    async def run(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the agent loop to completion. Returns the structured result."""
        return await self._drive(query, session_id=session_id, emitter=None)

    async def stream(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield trace events for SSE.

        Each yielded value is an ``AgentTraceEvent`` dict — pass them
        through ``json.dumps`` to put on the wire. After the SDK loop
        ends, a synthetic ``final`` event is appended whose ``data``
        field carries the same dict as ``run`` returns.
        """
        queue: asyncio.Queue[AgentTraceEvent] = asyncio.Queue()
        DONE = object()

        def emitter(event: AgentTraceEvent) -> None:
            try:
                queue.put_nowait(event)
            except Exception:  # noqa: BLE001
                pass

        async def _runner() -> Dict[str, Any]:
            try:
                result = await self._drive(query, session_id=session_id, emitter=emitter)
                return result
            finally:
                queue.put_nowait(DONE)  # type: ignore[arg-type]

        task = asyncio.create_task(_runner())
        try:
            while True:
                item = await queue.get()
                if item is DONE:
                    break
                yield item  # type: ignore[misc]
            result = await task
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception:
            if not task.done():
                task.cancel()
            raise

        yield {
            "type": "final",
            "task_id": result.get("session_id", session_id or ""),
            "seq": result.get("trace_summary", {}).get("tool_call_count", 0) + 9999,
            "timestamp": round(time.time(), 6),
            "data": {
                "answer": result["answer"],
                "recommended_package_ids": result["recommended_package_ids"],
                "relevant_package_ids": result["relevant_package_ids"],
                "notes": result.get("notes"),
                "tool_trace": result["tool_trace"],
                "model": result["model"],
                "usage": result["usage"],
            },
        }
