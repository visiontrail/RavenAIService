"""
Claude Agent SDK in-process MCP server: lookup_project_repo tool.

Agent 调用此工具将 project_code 解析为 git 仓库 URL 和默认分支。
clone_url 注入 git token（若有），仅在工具响应内传递，不写入 task.json。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

_server = None  # lazily created


def _build_clone_url(repo_url: str, token: Optional[str]) -> str:
    if not token:
        return repo_url
    try:
        parsed = urlparse(repo_url)
        if parsed.scheme in ("http", "https") and not parsed.username:
            netloc = f"oauth2:{token}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return repo_url


def _mask_clone_url(url: str) -> str:
    return re.sub(r"https://[^@]+@", "https://***@", url)


def _get_server():
    """Lazily create and return the in-process MCP server."""
    global _server
    if _server is not None:
        return _server

    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    from app.config import settings

    @tool(
        "lookup_project_repo",
        "Resolve a git repository URL and default branch by project_code "
        "(and optional project_name fallback) from the admin-managed registry. "
        "Returns clone-ready URL (with auth token if required), default branch, and auth info.",
        {"project_code": str, "project_name": "str | None"},
    )
    async def _lookup_project_repo(args):
        from app.models.database import db_manager
        from app.services import project_repo_service

        code = (args.get("project_code") or "").strip()
        name = (args.get("project_name") or "").strip() or None

        if not code:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": "invalid_input", "message": "project_code is required"})}]
            }

        async with db_manager.session_factory() as db:
            repo = await project_repo_service.get_by_project_code(db, code)

        if not repo:
            logger.info("lookup_project_repo: not_found code=%s", code)
            return {
                "content": [{"type": "text", "text": json.dumps({"error": "not_found", "project_code": code})}]
            }

        effective_token = repo.git_token or settings.code_repo_git_token or ""
        clone_url = _build_clone_url(repo.repo_url, effective_token or None)

        payload = {
            "project_code": repo.project_code,
            "project_name": repo.project_name,
            "repo_url": repo.repo_url,           # no token, for display
            "clone_url": clone_url,               # token injected, for actual git clone
            "default_branch": repo.default_branch,
            "auth_required": bool(effective_token),
        }
        logger.info(
            "lookup_project_repo: found code=%s repo_url=%s auth=%s",
            repo.project_code,
            repo.repo_url,
            bool(effective_token),
        )
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    _server = create_sdk_mcp_server(
        name="project_repo",
        version="1.0.0",
        tools=[_lookup_project_repo],
    )
    return _server


def get_mcp_server():
    """Return the project_repo in-process MCP server (creates it on first call)."""
    return _get_server()
