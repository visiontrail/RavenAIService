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
import time
from typing import Any, Dict, List, Optional

from app.agents.log_analysis.workspace import WorkspaceContext

logger = logging.getLogger(__name__)

# Bash command whitelist prefixes
_BASH_ALLOWLIST = frozenset([
    "git", "grep", "rg", "tar", "zcat", "gunzip",
    "find", "cat", "head", "tail", "wc", "jq", "ls",
    "awk", "sed",
])

# Regex to scrub token-injected URLs from tool traces
_TOKEN_URL_RE = re.compile(r"https://[^@\s]+@")

ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Grep",
    "Glob",
    "Skill",  # 允许模型调用通过 setting_sources 加载的用户自定义 Skill
    "mcp__project_repo__lookup_project_repo",
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


class LogAnalysisAgent:
    """Wraps Claude Agent SDK query() loop for log analysis tasks."""

    async def run(self, ctx: WorkspaceContext) -> Dict[str, Any]:
        """Run the agent loop and return the structured result dict."""
        from app.agents.anthropic_client import build_options
        from app.agents.log_analysis.mcp_tools import get_mcp_server
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
            question=task_data.get("question", ""),
            log_type=task_data.get("log_type"),
            hints=task_data.get("hints", ""),
        )

        mcp_server = get_mcp_server()

        # Resolve effective model before run for logging & result
        from app.agents.anthropic_client import PROVIDER_PROFILES
        provider = settings.anthropic_provider
        profile = PROVIDER_PROFILES.get(provider)
        effective_model = settings.anthropic_model or (profile.default_model if profile else "unknown")

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
            allowed_tools=ALLOWED_TOOLS,
            cwd=ctx.temp_dir,
            permission_mode="acceptEdits",
            mcp_servers={"project_repo": mcp_server},
            setting_sources=setting_sources,
        )

        tool_trace: List[Dict[str, str]] = []
        token_usage: Dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
        }
        final_text: str = ""
        start = time.monotonic()

        try:
            async for message in query(prompt=user_prompt, options=options):
                if hasattr(message, "tool_uses"):
                    # AssistantMessage with tool use blocks
                    for tool_use in (message.tool_uses or []):
                        trace_entry = {
                            "name": getattr(tool_use, "name", ""),
                            "input": _mask_input(getattr(tool_use, "input", {})),
                            "output_excerpt": "",
                        }
                        tool_trace.append(trace_entry)

                if hasattr(message, "usage"):
                    usage = message.usage
                    if usage:
                        token_usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
                        token_usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
                        token_usage["cache_read_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0

                # ToolResultMessage — capture output excerpts
                if hasattr(message, "tool_results"):
                    for i, tool_result in enumerate(message.tool_results or []):
                        content_text = ""
                        content = getattr(tool_result, "content", None)
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    content_text += item.get("text", "")
                                elif hasattr(item, "text"):
                                    content_text += getattr(item, "text", "")
                        elif isinstance(content, str):
                            content_text = content
                        excerpt = _mask_tokens(content_text)[:1024]
                        # Associate with the corresponding trace entry
                        if i < len(tool_trace):
                            tool_trace[-(len(message.tool_results) - i)]["output_excerpt"] = excerpt

                # ResultMessage — the final output
                if hasattr(message, "result"):
                    raw_result = getattr(message, "result", "")
                    if isinstance(raw_result, str):
                        final_text = raw_result

        except asyncio.TimeoutError:
            raise

        duration = time.monotonic() - start

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
            "root_cause_hypotheses": parsed.get("root_cause_hypotheses", []),
            "recommended_actions": parsed.get("recommended_actions", []),
            "related_keywords": parsed.get("related_keywords", []),
            "tool_trace": tool_trace,
            "raw": final_text,
            "duration_seconds": round(duration, 2),
            "token_usage": token_usage,
        }

    def run_sync(self, ctx: WorkspaceContext) -> Dict[str, Any]:
        """Synchronous wrapper for Celery tasks. Applies request timeout."""
        from app.config import settings

        timeout = settings.anthropic_request_timeout_seconds

        try:
            return asyncio.run(
                asyncio.wait_for(self.run(ctx), timeout=float(timeout))
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
