"""
Claude Agent SDK 项目专家 Agent。

与 ``LogAnalysisAgent`` 同构，但去掉附件日志分析这一环：工作区只含
``repo/`` + ``task.json``，不解压归档、不校验 metadata.json。项目身份
来自用户显式选择的项目仓库（写入 ``task.json.repo_info``）。

主入口：
  ProjectExpertAgent().run(ctx)       — async, returns dict
  ProjectExpertAgent().run_sync(ctx)  — sync wrapper (供后台线程调用)

两个入口都可选注入 ``trace_emitter``，在 SDK loop 内部按消息粒度向外
推送 ``AgentTraceEvent`` —— 与 Log Analysis 完全一致。

trace 层与 ``lookup_project_repo`` MCP 工具均 **复用** log_analysis 的
实现，不重复造轮子。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 复用 log_analysis 的 trace 层（纯 SDK 消息 → AgentTraceEvent 转换，无日志语义）。
from app.agents.log_analysis.trace import (
    AgentTraceEvent,
    CANCELLED,
    DEFAULT_EXCERPT_MAX_BYTES,
    ERROR,
    RUN_COMPLETE,
    RUN_START,
    STEP_END,
    SYSTEM_NOTICE,
    build_event,
    coerce_excerpt,
    derive_tool_trace,
    mask_tokens,
    summarize,
)
# 复用 log_analysis agent 的 trace 状态机与结果抽取逻辑。
from app.agents.log_analysis.agent import (
    AgentCancelled,
    _RunState,
    _cancelled_result,
    _close_any_active_steps,
    _emit_cancel_requested,
    _emit_for_message,
    _extract_fenced_json,
    _log_workflow,
    _normalize_question_type,
    _strip_confidence_fields,
    _validate_result_schema,
    extract_recoverable_result_fields,
)
from app.agents.project_expert.workspace import WorkspaceContext

logger = logging.getLogger(__name__)


PROJECT_REPO_MCP_TOOL = "mcp__project_repo__lookup_project_repo"

ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Grep",
    "Glob",
    "Skill",  # 允许模型调用通过 setting_sources 加载的用户自定义 Skill
    PROJECT_REPO_MCP_TOOL,
]

# Agent 唯一键，与 skills_service.SUPPORTED_AGENTS 对应。
AGENT_KEY = "project_expert"


TraceEmitter = Callable[[AgentTraceEvent], None]


def _build_skill_relevance_query(ctx: WorkspaceContext, task_data: Dict[str, Any]) -> str:
    """Build the text used to select request-relevant user skills.

    Focused on the user's actual question / hints / selected project name.
    """
    repo_info = task_data.get("repo_info") if isinstance(task_data, dict) else None
    parts = [
        ctx.metadata.get("question"),
        task_data.get("question"),
        task_data.get("hints"),
    ]
    if isinstance(repo_info, dict):
        parts.append(repo_info.get("project_name"))
        parts.append(repo_info.get("project_code"))
    return "\n".join(str(part) for part in parts if part)


def _empty_result(model: str, *, status: str, error_kind: Optional[str], **extra: Any) -> Dict[str, Any]:
    base = {
        "engine": "claude-agent-sdk",
        "model": model,
        "schema_version": 3,
        "status": status,
        "error_kind": error_kind,
        "question_type": "other",
        "answer": "",
        "summary": "",
        "severity": "info",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": [],
    }
    base.update(extra)
    return base


class ProjectExpertAgent:
    """Wraps the Claude Agent SDK query() loop for project source-code Q&A."""

    async def run(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
        trace_emitter: Optional[TraceEmitter] = None,
    ) -> Dict[str, Any]:
        """Run the agent loop and return the structured result dict.

        Args:
            ctx: project-expert workspace context (paths + metadata).
            cancel_event: optional ``threading.Event`` checked between SDK
                messages; when set the agent emits ``cancel_requested`` then
                terminates with a ``cancelled`` result.
            trace_emitter: optional synchronous callback invoked once per
                ``AgentTraceEvent`` (used by the chat service for SSE).
        """
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
        from app.agents.project_expert.prompts import get_prompts, render_user_prompt
        from app.config import settings

        try:
            from claude_agent_sdk import query  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
            ) from exc

        system_prompt, user_prompt_template = get_prompts()
        system_prompt += (
            "\n\n## 当前运行工作区\n"
            f"本次运行的当前工作目录是 `{ctx.temp_dir}`。"
            f"`task.json` 的真实路径是 `{ctx.task_json_path}`，"
            f"源码目录是 `{ctx.repo_dir}`。"
            "读取文件和搜索时只使用这些路径或它们的相对路径 "
            "(`task.json`、`repo/...`)。"
            "第一次 Read 调用请使用 `{\"file_path\":\"task.json\"}`。"
            "本工作区没有 `logs/` 目录，也没有 metadata.json，不要去搜索它们。"
            "如果路径不确定，先用 `pwd` / `ls -la` 确认当前目录。\n"
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

        # Resolve effective model before run for logging & result.
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
            allowed_tools = [name for name in allowed_tools if name != PROJECT_REPO_MCP_TOOL]
            system_prompt += (
                "\n\n## 运行时约束\n"
                f"当前 provider `{provider}` 不支持 MCP server 工具。"
                "本次运行中 `mcp__project_repo__lookup_project_repo` 不可用。"
                "请直接使用 `task.json` 中 `repo_info.repo_url` 克隆仓库。"
            )
            logger.info(
                "ProjectExpertAgent: provider=%s does not support MCP; using repo_info.repo_url only",
                provider,
            )

        # 物化本次请求相关的 Skill 到 cwd/.claude/skills/<name>/，配合
        # setting_sources=["project"] 让 SDK 按官方约定发现 Skill。
        materialized_skills: List[str] = []
        try:
            from app.services import skills_service
            materialized_skills = skills_service.materialize_relevant_enabled_skills(
                AGENT_KEY,
                ctx.temp_dir,
                query_text=_build_skill_relevance_query(ctx, task_data),
            )
            if materialized_skills:
                logger.info(
                    "ProjectExpertAgent: loaded %d skill(s): %s",
                    len(materialized_skills),
                    ", ".join(materialized_skills),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ProjectExpertAgent: failed to materialize skills: %s", exc)

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

        _log_workflow(ctx.task_id, "run_start", model=effective_model)
        state.emit(
            build_event(
                RUN_START,
                task_id=ctx.task_id,
                seq_counter=state.seq_counter,
                model=effective_model,
                provider=str(provider),
                loaded_skills=list(materialized_skills),
            )
        )
        if materialized_skills:
            state.emit(
                build_event(
                    SYSTEM_NOTICE,
                    task_id=ctx.task_id,
                    seq_counter=state.seq_counter,
                    kind="skills_loaded",
                    detail=", ".join(materialized_skills),
                    loaded_skills=list(materialized_skills),
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
            logger.exception("ProjectExpertAgent: run failed: %s", exc)
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
            "loaded_skills": list(materialized_skills),
        }

        if parsed is None:
            logger.warning("ProjectExpertAgent: no fenced JSON in result, schema_mismatch")
            return _empty_result(
                effective_model, status="schema_mismatch", error_kind=None, **common_extra
            )

        if not _validate_result_schema(parsed):
            recovered = extract_recoverable_result_fields(final_text)
            if recovered:
                logger.warning(
                    "ProjectExpertAgent: result JSON incomplete; recovered user-facing answer"
                )
                recovered_status = recovered.get("status", "ok")
                recovered_error_kind = recovered.get("error_kind")
                if recovered_error_kind:
                    recovered_status = "error"
                return {
                    "engine": "claude-agent-sdk",
                    "model": effective_model,
                    "schema_version": 3,
                    "status": recovered_status,
                    "error_kind": recovered_error_kind,
                    "question_type": recovered.get("question_type", "other"),
                    "answer": recovered.get("answer", ""),
                    "summary": recovered.get("summary", ""),
                    "severity": recovered.get("severity", "info"),
                    "root_cause_hypotheses": _strip_confidence_fields(
                        recovered.get("root_cause_hypotheses", [])
                    ),
                    "recommended_actions": recovered.get("recommended_actions", []),
                    "related_keywords": recovered.get("related_keywords", []),
                    "parse_warning": "incomplete_json_recovered",
                    **common_extra,
                }

            logger.warning("ProjectExpertAgent: result JSON missing required fields, schema_mismatch")
            return _empty_result(
                effective_model, status="schema_mismatch", error_kind=None, **common_extra
            )

        status = parsed.get("status", "ok")
        error_kind = parsed.get("error_kind")
        if error_kind:
            status = "error"

        question_type = _normalize_question_type(parsed.get("question_type"))
        answer = parsed.get("answer", "") or ""
        summary = parsed.get("summary", "") or ""
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
            logger.error("ProjectExpertAgent: timed out after %ds", timeout)
            return _empty_result(
                "unknown",
                status="error",
                error_kind="timeout",
                severity="error",
                tool_trace=[],
                trace_events=[],
                trace_summary={
                    "thought_duration_seconds": float(timeout),
                    "tool_call_count": 0,
                    "thinking_chars": 0,
                },
                raw=f"Agent timed out after {timeout} seconds",
                duration_seconds=float(timeout),
                token_usage={"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            )
