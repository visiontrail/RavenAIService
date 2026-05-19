"""
Claude Agent SDK 日志分析 Agent。

主入口:
  LogAnalysisAgent().run(ctx)      — async, returns dict
  LogAnalysisAgent().run_sync(ctx) — sync wrapper for Celery
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

from app.agents.log_analysis.workspace import WorkspaceContext

logger = logging.getLogger(__name__)


class AgentCancelled(Exception):
    """Raised inside the agent loop when an external cancel signal fires."""

# Regex to scrub token-injected URLs from tool traces
_TOKEN_URL_RE = re.compile(r"https://[^@\s]+@")
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


def _mask_tokens(text: str) -> str:
    return _TOKEN_URL_RE.sub("https://***@", text)


def _mask_input(inp: Any) -> str:
    if isinstance(inp, dict):
        return _mask_tokens(json.dumps(inp, ensure_ascii=False))
    return _mask_tokens(str(inp) if inp is not None else "")


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


def _record_tool_call(
    tool_trace: List[Dict[str, str]],
    *,
    name: str,
    tool_input: Any,
) -> None:
    tool_trace.append(
        {
            "name": name,
            "input": _mask_input(tool_input),
            "output_excerpt": "",
        }
    )


def _record_tool_result(
    tool_trace: List[Dict[str, str]],
    *,
    content: Any,
    index_from_end: int = 0,
) -> None:
    excerpt = _mask_tokens(_tool_result_to_text(content))[:1024]
    if not tool_trace:
        return
    target_index = len(tool_trace) - 1 - index_from_end
    if 0 <= target_index < len(tool_trace):
        tool_trace[target_index]["output_excerpt"] = excerpt


def _handle_content_block(
    block: Any,
    *,
    task_id: str,
    tool_trace: List[Dict[str, str]],
) -> None:
    thinking = getattr(block, "thinking", None)
    if thinking:
        _log_workflow(
            task_id,
            "thinking",
            content=_truncate_for_log(_mask_tokens(str(thinking))),
        )
        return

    tool_use_id = getattr(block, "tool_use_id", None)
    if tool_use_id is not None:
        content = getattr(block, "content", None)
        is_error = getattr(block, "is_error", None)
        tool_name = ""
        for entry in reversed(tool_trace):
            if not entry.get("output_excerpt"):
                tool_name = entry.get("name", "")
                break
        _log_workflow(
            task_id,
            "tool_result",
            tool=tool_name or str(tool_use_id),
            status="error" if is_error else "ok",
            output=_truncate_for_log(_mask_tokens(_tool_result_to_text(content))),
        )
        _record_tool_result(
            tool_trace,
            content=content,
        )
        return

    name = getattr(block, "name", None)
    tool_input = getattr(block, "input", None)
    if name and tool_input is not None:
        _log_workflow(
            task_id,
            "tool_call",
            tool=str(name),
            input=_truncate_for_log(_mask_input(tool_input)),
        )
        _record_tool_call(tool_trace, name=str(name), tool_input=tool_input)
        return

    text = getattr(block, "text", None)
    if text:
        _log_workflow(
            task_id,
            "assistant_text",
            content=_truncate_for_log(_mask_tokens(str(text))),
        )


def _handle_stream_message(
    message: Any,
    *,
    task_id: str,
    tool_trace: List[Dict[str, str]],
    token_usage: Dict[str, int],
    final_text: Dict[str, str],
) -> None:
    content = getattr(message, "content", None)
    if isinstance(content, list) and content:
        for block in content:
            _handle_content_block(block, task_id=task_id, tool_trace=tool_trace)
        _accumulate_token_usage(getattr(message, "usage", None), token_usage)
        return

    if hasattr(message, "tool_uses") and message.tool_uses:
        for tool_use in message.tool_uses or []:
            name = getattr(tool_use, "name", "")
            tool_input = getattr(tool_use, "input", {})
            _log_workflow(
                task_id,
                "tool_call",
                tool=str(name),
                input=_truncate_for_log(_mask_input(tool_input)),
            )
            _record_tool_call(tool_trace, name=str(name), tool_input=tool_input)

    if hasattr(message, "usage"):
        _accumulate_token_usage(message.usage, token_usage)

    if hasattr(message, "tool_results") and message.tool_results:
        total = len(message.tool_results)
        for i, tool_result in enumerate(message.tool_results or []):
            content_text = _tool_result_to_text(getattr(tool_result, "content", None))
            tool_name = tool_trace[-(total - i)]["name"] if tool_trace and (total - i) <= len(tool_trace) else ""
            is_error = getattr(tool_result, "is_error", None)
            excerpt = _mask_tokens(content_text)[:1024]
            _log_workflow(
                task_id,
                "tool_result",
                tool=tool_name,
                status="error" if is_error else "ok",
                output=_truncate_for_log(excerpt),
            )
            if tool_trace:
                target_index = len(tool_trace) - (total - i)
                if 0 <= target_index < len(tool_trace):
                    tool_trace[target_index]["output_excerpt"] = excerpt

    data = getattr(message, "data", None)
    subtype = getattr(message, "subtype", None)
    if isinstance(data, dict) and subtype:
        summary = data.get("summary") or data.get("description") or data.get("message")
        if summary:
            _log_workflow(task_id, "system", subtype=str(subtype), detail=_truncate_for_log(str(summary)))
        else:
            _log_workflow(task_id, "system", subtype=str(subtype))

    raw_result = getattr(message, "result", None)
    if isinstance(raw_result, str) and raw_result:
        final_text["text"] = raw_result
        _log_workflow(
            task_id,
            "result",
            turns=getattr(message, "num_turns", None),
            stop_reason=getattr(message, "stop_reason", None),
            excerpt=_truncate_for_log(_mask_tokens(raw_result)),
        )


def _cancelled_result(
    *,
    model: str,
    duration: float,
    tool_trace: List[Dict[str, str]],
    token_usage: Dict[str, int],
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
    ) -> Dict[str, Any]:
        """Run the agent loop and return the structured result dict."""
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
        from app.agents.log_analysis.prompts import get_prompts, render_user_prompt
        from app.config import settings

        try:
            from claude_agent_sdk import query, AssistantMessage, ResultMessage
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
                "If source code is required, use explicit repository fields or "
                "`repo_info` from `task.json`. If neither exists, finish with "
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

        tool_trace: List[Dict[str, str]] = []
        token_usage: Dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
        }
        final_text_holder: Dict[str, str] = {"text": ""}
        start = time.monotonic()

        _log_workflow(ctx.task_id, "run_start", model=effective_model)

        try:
            async for message in query(prompt=user_prompt, options=options):
                if cancel_event is not None and cancel_event.is_set():
                    _log_workflow(ctx.task_id, "cancelled", reason="cancel_event_set")
                    raise AgentCancelled()
                _handle_stream_message(
                    message,
                    task_id=ctx.task_id,
                    tool_trace=tool_trace,
                    token_usage=token_usage,
                    final_text=final_text_holder,
                )

        except AgentCancelled:
            duration = time.monotonic() - start
            _log_workflow(
                ctx.task_id,
                "run_complete",
                status="cancelled",
                tool_calls=len(tool_trace),
                duration_s=round(duration, 2),
                tokens_in=token_usage["input_tokens"],
                tokens_out=token_usage["output_tokens"],
            )
            return _cancelled_result(
                model=effective_model,
                duration=duration,
                tool_trace=tool_trace,
                token_usage=token_usage,
            )
        except asyncio.TimeoutError:
            raise

        final_text = final_text_holder["text"]
        duration = time.monotonic() - start
        _log_workflow(
            ctx.task_id,
            "run_complete",
            status="finished",
            tool_calls=len(tool_trace),
            duration_s=round(duration, 2),
            tokens_in=token_usage["input_tokens"],
            tokens_out=token_usage["output_tokens"],
        )

        parsed = _extract_fenced_json(final_text)

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
                "tool_trace": tool_trace,
                "raw": final_text,
                "duration_seconds": round(duration, 2),
                "token_usage": token_usage,
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
                "tool_trace": tool_trace,
                "raw": final_text,
                "duration_seconds": round(duration, 2),
                "token_usage": token_usage,
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
            "tool_trace": tool_trace,
            "raw": final_text,
            "duration_seconds": round(duration, 2),
            "token_usage": token_usage,
        }

    def run_sync(
        self,
        ctx: WorkspaceContext,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for Celery tasks. Applies request timeout."""
        from app.config import settings

        timeout = settings.anthropic_request_timeout_seconds

        try:
            return asyncio.run(
                asyncio.wait_for(
                    self.run(ctx, cancel_event=cancel_event),
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
                "raw": f"Agent timed out after {timeout} seconds",
                "duration_seconds": float(timeout),
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            }
