"""
Git 仓库连通性测试工具（供 project_repo_service 复用）。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional
from urllib.parse import urlparse, urlunparse

from app.config import settings

logger = logging.getLogger(__name__)


def _inject_token(url: str, token: str) -> str:
    """将 token 注入 HTTPS URL 用于认证。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and not parsed.username:
            netloc = f"oauth2:{token}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


def test_repo_connection(url: str, token: Optional[str] = None) -> dict:
    """测试 git 仓库连通性。

    使用 `git ls-remote --exit-code --quiet URL` 探测，
    返回 {"success": bool, "message": str, "auth_method": str}。
    """
    if not url or not url.strip():
        return {"success": False, "message": "仓库 URL 不能为空", "auth_method": "none"}

    url = url.strip()

    effective_token = token or settings.code_repo_git_token or ""
    auth_method = "none"

    if not effective_token:
        test_url = url
        auth_method = "anonymous"
    else:
        if url.startswith(("http://", "https://")):
            test_url = _inject_token(url, effective_token)
            auth_method = "token_in_url"
        else:
            test_url = url
            auth_method = "ssh_key"

    cmd = ["git", "ls-remote", "--exit-code", "--quiet", "--heads", test_url]

    try:
        if shutil.which("git") is None:
            return {"success": False, "message": "服务器未安装 git 命令", "auth_method": auth_method}

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"},
        )

        if result.returncode == 0:
            return {
                "success": True,
                "message": "连接成功，仓库可访问",
                "auth_method": auth_method,
            }

        stderr = (result.stderr or "").strip()
        if "Authentication failed" in stderr or "could not read Username" in stderr:
            msg = "认证失败：请检查 Token 是否正确或是否有仓库访问权限"
        elif "not found" in stderr or "does not exist" in stderr:
            msg = "仓库不存在：请确认 URL 是否正确"
        elif "Could not resolve host" in stderr or "unable to access" in stderr:
            msg = "无法连接到服务器：请检查网络或 URL 中的主机名"
        elif "Repository not found" in stderr:
            msg = "仓库未找到：请检查路径或访问权限"
        else:
            msg = f"连接失败（exit={result.returncode}）：{stderr[:200] or '未知错误'}"

        return {"success": False, "message": msg, "auth_method": auth_method}

    except subprocess.TimeoutExpired:
        return {"success": False, "message": "连接超时（20s），请检查网络或服务器地址", "auth_method": auth_method}
    except Exception as exc:
        return {"success": False, "message": f"测试异常：{exc}", "auth_method": auth_method}
