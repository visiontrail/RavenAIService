"""
Claude Agent SDK in-process MCP server: project discovery and repo lookup.

``discover_projects`` 只返回可公开的项目卡片目录；``lookup_project_repo``
将已确认的 project_code 解析为 git 仓库 URL 和默认分支。clone_url 注入 git
token（若有），仅在 lookup 工具响应内传递，不写入 task.json。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

_server = None  # full project server, lazily created
_discovery_server = None  # discovery-only view for GeneralAgent

PROJECT_DISCOVERY_MCP_TOOL = "mcp__project_repo__discover_projects"
PROJECT_REPO_LOOKUP_MCP_TOOL = "mcp__project_repo__lookup_project_repo"


def build_project_fit_guidance(
    *,
    workflow_name: str,
    project_name: Optional[str],
    project_code: Optional[str],
    project_card: Optional[str],
    catalog_available: bool,
    switch_instruction: str,
) -> str:
    """Build the shared, high-priority project-fit policy for Agent prompts."""
    selected = (
        f"当前项目：{project_name or '未知'}（{project_code or 'unknown'}）\n"
        f"当前项目卡片：{project_card or '项目范围未提供，不能据此作出确定匹配'}"
    )
    if catalog_available:
        evidence_rule = (
            "在克隆仓库、加载项目专属知识或作出领域结论之前，必须先调用 "
            "`mcp__project_repo__discover_projects` 读取完整的已启用项目卡片目录。"
        )
        catalog_rule = (
            "只有读到完整目录后，才可以推荐具体项目或断言没有合适项目。"
        )
    else:
        evidence_rule = (
            "当前运行时无法调用项目目录工具；只能使用当前项目卡片判断当前项目是否明显不匹配。"
        )
        catalog_rule = (
            "不得声称某个替代项目一定存在，也不得断言整个系统没有合适项目。"
        )
    return (
        "\n\n## 项目适配性检查（最高优先级）\n"
        f"这是 {workflow_name} 的前置安全检查。{selected}\n"
        f"- {evidence_rule}\n"
        "- 如果问题/日志与当前项目卡片明确不匹配，立即停止基于当前仓库、项目提示词或项目 Skill 作答；准确说明不匹配，不要从错误项目生成似是而非的结论。\n"
        "- 如果目录中有明确匹配项，给出项目名称和 project_code，并说明为何它的项目卡片更匹配；"
        f"{switch_instruction}\n"
        "- 如果完整目录中没有任何项目卡片匹配，必须明确回答“当前系统还没有适合回答这个问题的项目”，不要勉强挑选最接近但无关的项目。\n"
        "- 如果存在多个可能项目或证据不足，明确说明不确定性并请用户补充信息，不得制造唯一结论。\n"
        f"- {catalog_rule}\n"
        "- 只有当前项目确实匹配时，才继续原有分析流程与最终 JSON 输出契约。"
    )


def build_clone_url(repo_url: str, token: Optional[str]) -> str:
    """Inject a git token into an HTTPS clone URL. Public — also used by
    workspace pre-resolution for providers that don't support MCP tools.
    """
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


_build_clone_url = build_clone_url  # backward-compat alias


def _mask_clone_url(url: str) -> str:
    return re.sub(r"https://[^@]+@", "https://***@", url)


async def discover_projects_payload() -> dict:
    """Build the safe Agent-facing project catalog (public for focused tests)."""
    from app.models.database import db_manager
    from app.services import project_repo_service

    async with db_manager.session_factory() as db:
        return await project_repo_service.discover_projects(db)


def _get_servers():
    """Lazily create the full and discovery-only in-process MCP servers."""
    global _server, _discovery_server
    if _server is not None and _discovery_server is not None:
        return _server, _discovery_server

    try:
        from claude_agent_sdk import tool, create_sdk_mcp_server
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    from app.config import settings

    @tool(
        "discover_projects",
        "List all enabled projects and their required project cards so you can "
        "judge which project fits a user's question. Returns only safe identity, "
        "scope, repository-availability, and enabled-Agent metadata; never returns "
        "repository URLs or credentials. Read the complete catalog before naming "
        "a matching project or claiming that no suitable project exists.",
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )
    async def _discover_projects(_args):
        payload = await discover_projects_payload()
        logger.info(
            "discover_projects: count=%s truncated=%s",
            payload.get("count"),
            payload.get("truncated"),
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False),
                }
            ]
        }

    @tool(
        "lookup_project_repo",
        "Resolve a git repository URL and default branch by project_code "
        "(and optional project_name fallback) from the admin-managed registry. "
        "Returns clone-ready URL (with auth token if required), default branch, and auth info.",
        {
            "type": "object",
            "properties": {
                "project_code": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["project_code"],
        },
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
            # 日志分析 Agent 对「未关联代码仓库」的项目不可见。
            repo = await project_repo_service.get_by_project_code(
                db, code, require_repo=True
            )

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
        version="1.1.0",
        tools=[_discover_projects, _lookup_project_repo],
    )
    # ``allowed_tools`` is not a hard visibility boundary in every Claude Agent
    # SDK permission mode. GeneralAgent therefore receives a separate server
    # object that never exposes the credential-bearing lookup tool at all.
    _discovery_server = create_sdk_mcp_server(
        name="project_repo",
        version="1.1.0",
        tools=[_discover_projects],
    )
    return _server, _discovery_server


def get_mcp_server():
    """Return the full project_repo server used by project-bound Agents."""
    return _get_servers()[0]


def get_project_discovery_mcp_server():
    """Return a discovery-only project_repo server safe for GeneralAgent."""
    return _get_servers()[1]
