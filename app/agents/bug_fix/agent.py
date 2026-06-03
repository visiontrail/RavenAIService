"""
Claude Agent SDK Bug Fix Coding Agent。

写入型 Agent：在隔离工作区内基于真实源码做最小改动修复，按问题维度产出一个或
多个 Merge Request，最终输出结构化 ``merge_requests`` 数组。

主入口:
  BugFixCodingAgent().run(ctx)      — async, returns dict
  BugFixCodingAgent().run_sync(ctx) — sync wrapper for Celery
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.agents.bug_fix.workspace import BugFixWorkspaceContext
from app.agents.log_analysis.trace import mask_tokens

logger = logging.getLogger(__name__)

# 写入型工具集：读 + 写 + Bash（git / curl）。
ALLOWED_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]

AGENT_KEY = "bug_fix"


def _extract_final_json(text: str) -> Optional[Dict[str, Any]]:
    """从 Agent 输出中提取最后一个围栏 JSON 块（``merge_requests`` 契约）。

    优先匹配 ```json ... ``` 块；多块时取最后一个完整对象。退化到裸 JSON 对象。
    """
    if not text:
        return None
    candidates: List[str] = []
    # ```json ... ``` 或 ``` ... ```
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidates.append(m.group(1))
    for body in reversed(candidates):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    # 退化：找文本里最后一个平衡的 JSON 对象。
    last = _last_balanced_object(text)
    if last is not None:
        try:
            parsed = json.loads(last)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _last_balanced_object(text: str) -> Optional[str]:
    """返回文本中最后一个大括号平衡的 JSON 对象子串（best-effort）。"""
    end = text.rfind("}")
    while end != -1:
        depth = 0
        i = end
        while i >= 0:
            if text[i] == "}":
                depth += 1
            elif text[i] == "{":
                depth -= 1
                if depth == 0:
                    return text[i : end + 1]
            i -= 1
        end = text.rfind("}", 0, end)
    return None


def _normalize_merge_requests(value: Any) -> List[Dict[str, Any]]:
    """校验并规范化 merge_requests 数组，剔除明显不完整的项。token 脱敏。"""
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        branch = item.get("branch_name")
        if not branch:
            continue  # 没分支名的 MR 无意义
        mr_url = item.get("mr_url")
        out.append(
            {
                "title": str(item.get("title") or "Bug fix"),
                "description": mask_tokens(str(item.get("description") or "")),
                "branch_name": str(branch),
                "base_branch": str(item.get("base_branch") or ""),
                "mr_url": mask_tokens(str(mr_url)) if mr_url else None,
                "mr_iid": item.get("mr_iid"),
                "commit_sha": item.get("commit_sha"),
                "changed_files": item.get("changed_files")
                if isinstance(item.get("changed_files"), list)
                else [],
                "diff_stat": item.get("diff_stat")
                if isinstance(item.get("diff_stat"), dict)
                else None,
                "status": item.get("status"),
            }
        )
    return out


def _result(
    *,
    status: str,
    merge_requests: List[Dict[str, Any]],
    error_kind: Optional[str] = None,
    error: Optional[str] = None,
    model: Optional[str] = None,
    duration_seconds: float = 0.0,
) -> Dict[str, Any]:
    return {
        "status": status,
        "error_kind": error_kind,
        "error": mask_tokens(error) if error else None,
        "merge_requests": merge_requests,
        "model": model,
        "duration_seconds": round(duration_seconds, 2),
        "engine": "claude_agent_sdk",
        "agent_kind": AGENT_KEY,
    }


class BugFixCodingAgent:
    """写入型 Bug 修复 Agent。"""

    async def run(self, ctx: BugFixWorkspaceContext) -> Dict[str, Any]:
        from app.agents.anthropic_client import PROVIDER_PROFILES, build_options
        from app.agents.bug_fix.prompts import get_prompts, render_user_prompt
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
            f"当前工作目录是 `{ctx.temp_dir}`。源码克隆在 `repo/`，"
            f"任务详情在 `task.json`。git 操作前先 `cd repo/`。\n"
        )
        user_prompt = render_user_prompt(
            user_prompt_template,
            task_id=ctx.task_id,
            workspace_dir=ctx.temp_dir,
            default_branch=ctx.default_branch,
        )

        provider = settings.anthropic_provider
        profile = PROVIDER_PROFILES.get(provider)
        effective_model = (
            settings.bug_fix_agent_model
            or settings.anthropic_model
            or (profile.default_model if profile else "unknown")
        )

        options = build_options(
            system_prompt=system_prompt,
            allowed_tools=list(ALLOWED_TOOLS),
            cwd=ctx.temp_dir,
            permission_mode="bypassPermissions",
            max_turns=settings.bug_fix_agent_max_turns,
            model=settings.bug_fix_agent_model or None,
            request_timeout_seconds=settings.bug_fix_agent_request_timeout_seconds,
        )

        start = time.monotonic()
        collected_text: List[str] = []
        logger.info(
            "BugFixCodingAgent run_start task=%s model=%s", ctx.task_id, effective_model
        )

        from claude_agent_sdk import query as _query

        async for message in _query(prompt=user_prompt, options=options):
            text = _message_text(message)
            if text:
                collected_text.append(text)

        duration = time.monotonic() - start
        full_text = "\n".join(collected_text)
        parsed = _extract_final_json(full_text)

        if not isinstance(parsed, dict):
            logger.warning(
                "BugFixCodingAgent task=%s produced no parseable result JSON", ctx.task_id
            )
            return _result(
                status="failed",
                merge_requests=[],
                error_kind="no_output_json",
                error="Agent did not emit a parseable merge_requests JSON",
                model=effective_model,
                duration_seconds=duration,
            )

        merge_requests = _normalize_merge_requests(parsed.get("merge_requests"))
        status = parsed.get("status")
        error_kind = parsed.get("error_kind")
        if status not in ("succeeded", "partial", "failed"):
            status = "succeeded" if merge_requests else "failed"
        # 自洽校正：声称成功却无 MR → failed。
        if status == "succeeded" and not merge_requests:
            status = "failed"
            error_kind = error_kind or "no_merge_requests"

        logger.info(
            "BugFixCodingAgent run_complete task=%s status=%s mrs=%d duration=%.1fs",
            ctx.task_id,
            status,
            len(merge_requests),
            duration,
        )
        return _result(
            status=status,
            merge_requests=merge_requests,
            error_kind=error_kind,
            error=parsed.get("error"),
            model=effective_model,
            duration_seconds=duration,
        )

    def run_sync(self, ctx: BugFixWorkspaceContext) -> Dict[str, Any]:
        """同步包装供 Celery 调用。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("run_sync called from a running event loop")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.run(ctx))
        finally:
            try:
                loop.close()
            except Exception:
                pass


def _message_text(message: Any) -> str:
    """从 SDK 消息中提取文本内容（兼容 AssistantMessage / ResultMessage）。"""
    parts: List[str] = []
    content = getattr(message, "content", None)
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    # ResultMessage 常带最终 result 文本
    result_text = getattr(message, "result", None)
    if isinstance(result_text, str):
        parts.append(result_text)
    return "\n".join(parts)
