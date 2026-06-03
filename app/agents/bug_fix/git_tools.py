"""
Bug Fix Agent 的 Git 平台辅助：平台/API base 推断与 Merge Request 创建。

首期完整覆盖 GitLab（``POST /projects/:id/merge_requests``）；GitHub（Pull Request）
走同一 ``create_merge_request`` 抽象预留。token 在任何返回/日志中一律脱敏。

注意：Agent 通常会在工作区内用 ``git`` CLI 完成分支/提交/推送，再调用平台 REST
创建 MR。此模块既可被任务编排直接调用，也为「Agent 经 Bash + curl 退化路径」
提供推断规则参考。
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
from urllib.parse import quote, urlparse

import httpx

from app.agents.log_analysis.trace import mask_tokens
from app.config import settings

logger = logging.getLogger(__name__)


def infer_provider(repo_url: str) -> str:
    """由配置覆盖或 repo_url host 推断 Git 平台类型。

    返回 ``"gitlab"`` | ``"github"`` | ``"unknown"``。
    """
    if settings.bug_fix_git_provider:
        return settings.bug_fix_git_provider.lower()
    host = (urlparse(repo_url).hostname or "").lower()
    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"
    # 私有部署的 GitLab 常见但 host 不含 gitlab 字样；默认按 gitlab 处理
    # （首期主力平台），无法识别时由调用方据 error_kind 处理。
    return "unknown"


def infer_api_base(repo_url: str, provider: str) -> Optional[str]:
    """推断平台 REST API base（含 scheme://host），配置可覆盖。"""
    if settings.bug_fix_git_api_base:
        return settings.bug_fix_git_api_base.rstrip("/")
    parsed = urlparse(repo_url)
    if not parsed.scheme or not parsed.hostname:
        return None
    host = parsed.hostname
    scheme = parsed.scheme
    if provider == "gitlab":
        return f"{scheme}://{host}/api/v4"
    if provider == "github":
        # github.com → api.github.com；GHE → https://<host>/api/v3
        if host == "github.com":
            return "https://api.github.com"
        return f"{scheme}://{host}/api/v3"
    return None


def _gitlab_project_path(repo_url: str) -> str:
    """从 repo_url 取出 GitLab project full path（namespace/project，去 .git）。"""
    path = urlparse(repo_url).path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def create_merge_request(
    *,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    token: Optional[str],
    timeout: float = 30.0,
) -> Tuple[Optional[str], Optional[str]]:
    """创建 MR/PR，返回 ``(mr_url, mr_iid)``。失败抛出 ``RuntimeError``（已脱敏）。

    认证用 per-repo / 全局 git token。MR 留作人工评审，绝不合并。
    """
    provider = infer_provider(repo_url)
    api_base = infer_api_base(repo_url, provider)
    if api_base is None or provider == "unknown":
        raise RuntimeError(
            f"git_provider_unsupported: cannot infer MR API for {mask_tokens(repo_url)}"
        )

    try:
        if provider == "gitlab":
            return _create_gitlab_mr(
                api_base=api_base,
                repo_url=repo_url,
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                token=token,
                timeout=timeout,
            )
        if provider == "github":
            return _create_github_pr(
                api_base=api_base,
                repo_url=repo_url,
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                token=token,
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"mr_create_failed: {mask_tokens(str(exc))}") from exc

    raise RuntimeError(f"git_provider_unsupported: {provider}")


def _create_gitlab_mr(
    *,
    api_base: str,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    token: Optional[str],
    timeout: float,
) -> Tuple[Optional[str], Optional[str]]:
    project_path = _gitlab_project_path(repo_url)
    project_id = quote(project_path, safe="")
    url = f"{api_base}/projects/{project_id}/merge_requests"
    headers = {"PRIVATE-TOKEN": token} if token else {}
    payload = {
        "source_branch": source_branch,
        "target_branch": target_branch,
        "title": title,
        "description": description,
        "remove_source_branch": False,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"mr_create_failed: GitLab returned {resp.status_code}: "
            f"{mask_tokens(resp.text)[:500]}"
        )
    data = resp.json()
    return data.get("web_url"), str(data.get("iid")) if data.get("iid") is not None else None


def _create_github_pr(
    *,
    api_base: str,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    token: Optional[str],
    timeout: float,
) -> Tuple[Optional[str], Optional[str]]:
    owner_repo = _gitlab_project_path(repo_url)  # owner/repo, 去 .git，复用解析
    url = f"{api_base}/repos/{owner_repo}/pulls"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "title": title,
        "body": description,
        "head": source_branch,
        "base": target_branch,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(
            f"pr_create_failed: GitHub returned {resp.status_code}: "
            f"{mask_tokens(resp.text)[:500]}"
        )
    data = resp.json()
    return data.get("html_url"), str(data.get("number")) if data.get("number") is not None else None
