"""
Claude Agent SDK 重构包检索 Agent（项目绑定形态）。

与 ``ProjectExpertAgent`` 同构：工作区只含 ``repo/`` + ``task.json``，
项目身份来自用户显式选择的项目仓库（写入 ``task.json.repo_info``）。
trace 层与 ``_RunState`` 状态机 **复用** log_analysis 的实现；包元数据
MCP 工具按本次运行绑定的 ``project_code`` 构建，服务端强制限定项目范围。

与项目专家的差异在最终结果契约：保留包检索自有的 fenced JSON schema
（``recommended_package_ids`` / ``relevant_package_ids`` / ``notes``），
并对返回 ID 做"所选项目范围内真实存在"的服务端校验过滤。

主入口：
  PackageSearchAgent().run(ctx)       — async, returns dict
  PackageSearchAgent().run_sync(ctx)  — sync wrapper (供后台线程调用)
  PackageSearchAgent().stream(ctx)    — async generator，逐条 yield
      ``AgentTraceEvent``，结尾追加 ``final`` 事件（供一次性 SSE 端点）

``run`` / ``run_sync`` 均可注入 ``cancel_event`` 与 ``trace_emitter``，
行为与项目专家一致。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

# 复用 log_analysis 的 trace 层（纯 SDK 消息 → AgentTraceEvent 转换，无日志语义）。
from app.agents.log_analysis.trace import (
    AgentTraceEvent,
    CANCELLED,
    DEFAULT_EXCERPT_MAX_BYTES,
    ERROR,
    RUN_COMPLETE,
    RUN_START,
    STEP_END,
    build_event,
    coerce_excerpt,
    derive_tool_trace,
    mask_tokens,
    summarize,
)
# 复用 log_analysis agent 的 trace 状态机与取消机制。
from app.agents.log_analysis.agent import (
    AgentCancelled,
    _RunState,
    _close_any_active_steps,
    _emit_cancel_requested,
    _emit_for_message,
    _log_workflow,
)
from app.agents.package_search.workspace import WorkspaceContext

logger = logging.getLogger(__name__)


PROJECT_REPO_MCP_TOOL = "mcp__project_repo__lookup_project_repo"

# All package-metadata MCP tool names are prefixed with
# ``mcp__package_search__`` by the SDK.
_PKG_MCP_PREFIX = "mcp__package_search__"

PACKAGE_MCP_TOOLS = [
    f"{_PKG_MCP_PREFIX}list_packages",
    f"{_PKG_MCP_PREFIX}get_package_by_id",
    f"{_PKG_MCP_PREFIX}search_packages_by_text",
    f"{_PKG_MCP_PREFIX}filter_packages_by_version",
    f"{_PKG_MCP_PREFIX}list_components",
    f"{_PKG_MCP_PREFIX}find_packages_by_component",
    f"{_PKG_MCP_PREFIX}package_stats",
]

ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Grep",
    "Glob",
    PROJECT_REPO_MCP_TOOL,
    *PACKAGE_MCP_TOOLS,
]


TraceEmitter = Callable[[AgentTraceEvent], None]


# ──────────────────────── 结果契约 helpers ─────────────────────────

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


def _append_warning(tool_trace: List[Dict[str, Any]], message: str) -> None:
    tool_trace.append({"type": "warning", "message": message})


def _validate_ids_in_project(
    ids: List[str], project_code: str
) -> Tuple[List[str], int]:
    """Keep only IDs that exist in the metadata store *and* belong to the
    run's project; dedupe and count dropped entries."""
    from app.services.raven_package_service import raven_package_service

    keep: List[str] = []
    seen: set[str] = set()
    dropped = 0
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        pkg = raven_package_service.get_package(pid)
        if pkg is not None and (
            not project_code or pkg.get("projectCode") == project_code
        ):
            keep.append(pid)
        else:
            dropped += 1
    return keep, dropped


def _base_result(model: str, *, status: str, **extra: Any) -> Dict[str, Any]:
    base = {
        "engine": "claude-agent-sdk",
        "model": model,
        "status": status,
        "answer": "",
        "recommended_package_ids": [],
        "relevant_package_ids": [],
        "notes": None,
    }
    base.update(extra)
    return base


class PackageSearchAgent:
    """Wraps the Claude Agent SDK query() loop for project-bound package search.

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

    def _build_options(
        self, *, system_prompt: str, project_code: str, cwd: str
    ) -> Tuple[Any, str, str]:
        """Build ClaudeAgentOptions; return ``(options, model, provider)``."""
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
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
            from app.agents.log_analysis.mcp_tools import (
                get_mcp_server as get_project_repo_server,
            )
            from app.agents.package_search.mcp_tools import (
                get_mcp_server as get_package_server,
            )

            mcp_servers = {
                "project_repo": get_project_repo_server(),
                "package_search": get_package_server(project_code),
            }
        else:
            allowed_tools = [
                name for name in allowed_tools if not name.startswith("mcp__")
            ]
            logger.warning(
                "PackageSearchAgent: provider=%s does not support MCP tools; "
                "package metadata tools unavailable this run",
                provider,
            )

        options = build_options(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            cwd=cwd,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers,
        )
        return options, effective_model, str(provider)

    async def run(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Run the agent loop and return the structured result dict.

        Args:
            ctx: package-search workspace context (paths + project binding).
            cancel_event: optional ``threading.Event`` checked between SDK
                messages; when set the agent emits ``cancel_requested`` then
                terminates with a ``cancelled`` result.
            trace_emitter: optional synchronous callback invoked once per
                ``AgentTraceEvent`` (used by the chat service for SSE).
        """
        from app.agents.package_search.prompts import get_prompts, render_user_prompt
        from app.i18n.prompts import response_language_directive

        system_prompt, user_prompt_template = get_prompts(locale=ctx.locale)
        system_prompt += (
            "\n\n## 当前运行工作区\n"
            f"本次运行的当前工作目录是 `{ctx.temp_dir}`。"
            f"`task.json` 的真实路径是 `{ctx.task_json_path}`，"
            f"源码目录是 `{ctx.repo_dir}`。"
            "读取文件和搜索时只使用这些路径或它们的相对路径 "
            "(`task.json`、`repo/...`)。"
            "本工作区没有 `logs/` 目录，也没有 metadata.json，不要去搜索它们。"
            "如果路径不确定，先用 `pwd` / `ls -la` 确认当前目录。\n"
            "\n## 本次运行绑定的项目\n"
            f"本次运行绑定项目 `{ctx.project_code}`。"
            "所有 mcp__package_search__* 工具已在服务端限定为该项目的包。\n"
        )

        task_data: Dict[str, Any] = {}
        try:
            task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
        except Exception:
            pass

        user_prompt = render_user_prompt(
            user_prompt_template,
            task_id=ctx.task_id,
            workspace_dir=ctx.temp_dir,
            question=ctx.metadata.get("question") or task_data.get("question", ""),
            hints=ctx.metadata.get("hints") or task_data.get("hints", ""),
        )

        # Append the blunt response-language directive last so the answer
        # language is decoupled from the (largely Chinese) package metadata.
        system_prompt += "\n\n" + response_language_directive(ctx.locale)

        options, effective_model, provider = self._build_options(
            system_prompt=system_prompt,
            project_code=ctx.project_code,
            cwd=ctx.temp_dir,
        )

        state = _RunState(task_id=ctx.task_id, emitter=trace_emitter)
        start = time.monotonic()

        _log_workflow(ctx.task_id, "run_start", model=effective_model)
        state.emit(
            build_event(
                RUN_START,
                task_id=ctx.task_id,
                seq_counter=state.seq_counter,
                model=effective_model,
                provider=provider,
            )
        )

        try:
            async for message in self._run_sdk_loop(prompt=user_prompt, options=options):
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
            return _base_result(
                effective_model,
                status="cancelled",
                provider=provider,
                tool_trace=derive_tool_trace(state.trace_events),
                trace_events=list(state.trace_events),
                trace_summary=trace_summary,
                usage=dict(state.token_usage),
                duration_seconds=round(duration, 2),
                session_id=ctx.task_id,
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
            logger.exception("PackageSearchAgent: run failed: %s", exc)
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
                final_text=coerce_excerpt(
                    mask_tokens(final_text), DEFAULT_EXCERPT_MAX_BYTES * 4
                ),
            )
        )

        # ---- 包检索结果契约：fenced JSON 解析 + 项目范围内 ID 校验 ----
        tool_trace = derive_tool_trace(state.trace_events)
        parsed, parse_error = _extract_fenced_json(final_text)
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
                recommended, dropped_r = _validate_ids_in_project(
                    raw_recommended, ctx.project_code
                )
                relevant, dropped_v = _validate_ids_in_project(
                    raw_relevant, ctx.project_code
                )
                total_dropped = dropped_r + dropped_v
                if total_dropped:
                    _append_warning(
                        tool_trace,
                        f"filtered {total_dropped} invalid ids",
                    )
                raw_notes = parsed.get("notes")
                if isinstance(raw_notes, str) and raw_notes.strip():
                    notes = raw_notes.strip()

        return _base_result(
            effective_model,
            status="ok",
            provider=provider,
            answer=final_text or "",
            recommended_package_ids=recommended,
            relevant_package_ids=relevant,
            notes=notes,
            tool_trace=tool_trace,
            trace_events=list(state.trace_events),
            trace_summary=trace_summary,
            usage=dict(state.token_usage),
            duration_seconds=round(duration, 2),
            session_id=ctx.task_id,
        )

    def run_sync(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper (for background threads). Applies request timeout."""
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
            logger.error("PackageSearchAgent: timed out after %ds", timeout)
            return _base_result(
                "unknown",
                status="error",
                error_kind="timeout",
                tool_trace=[],
                trace_events=[],
                trace_summary={
                    "thought_duration_seconds": float(timeout),
                    "tool_call_count": 0,
                    "thinking_chars": 0,
                },
                usage={"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
                duration_seconds=float(timeout),
                session_id=ctx.task_id,
            )

    async def stream(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield trace events for a one-shot SSE response.

        Each yielded value is an ``AgentTraceEvent`` dict — pass them
        through ``json.dumps`` to put on the wire. After the SDK loop
        ends, a synthetic ``final`` event is appended whose ``data``
        field carries the same payload as the non-stream response body.
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
                return await self.run(
                    ctx, cancel_event=cancel_event, trace_emitter=emitter
                )
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
            "task_id": result.get("session_id", ctx.task_id),
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
