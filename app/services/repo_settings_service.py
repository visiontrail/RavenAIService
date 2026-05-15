"""
Git 代码仓库配置管理服务。

持久化方式：读写项目根目录下的 .env 文件（仅修改 CODE_REPO_* 相关键）。
变更后同步更新 in-memory settings 对象，使新流程立即生效，无需重启。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

from app.config import settings

logger = logging.getLogger(__name__)

# .env 中对应的环境变量键名
_KEY_OAM_URL     = "CODE_REPO_OAM_URL"
_KEY_STACK_URL   = "CODE_REPO_STACK_URL"
_KEY_GIT_TOKEN   = "CODE_REPO_GIT_TOKEN"
_KEY_CLONE_DEPTH = "CODE_REPO_CLONE_DEPTH"

# 脱敏用占位符（前端展示时替换 token 内容）
_TOKEN_MASK = "••••••••"


# ─────────────────────── Data Structures ───────────────────────────

class RepoEntry:
    """单个代码仓库的配置。"""

    def __init__(self, log_type: str, url: str, display_name: str):
        self.log_type    = log_type       # "oam_antenna" | "stack"
        self.url         = url            # git URL（空字符串表示未配置）
        self.display_name = display_name  # 界面友好名称


class RepoSettings:
    """所有仓库的配置快照，供 API 层序列化。"""

    def __init__(
        self,
        oam_url: str,
        stack_url: str,
        git_token_set: bool,
        clone_depth: int,
        updated_at: Optional[str] = None,
    ):
        self.oam_url      = oam_url
        self.stack_url    = stack_url
        self.git_token_set = git_token_set   # 是否已设置 token（不返回明文）
        self.clone_depth  = clone_depth
        self.updated_at   = updated_at or ""


# ─────────────────────── .env 读写 ─────────────────────────────────

def _env_path() -> Path:
    return Path(settings.base_dir) / ".env"


def _read_env_lines() -> list[str]:
    p = _env_path()
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8").splitlines()


def _write_env_updates(updates: dict[str, Optional[str]]) -> None:
    """更新 .env 中指定键的值。

    - 键存在时原地替换（保留注释和顺序）。
    - 键不存在时追加到文件末尾。
    - 值为 None 时注释掉该行（不删除，方便以后取消注释）。
    """
    p = _env_path()
    lines = _read_env_lines()
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # 跳过纯注释行和空行
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        key_part = stripped.split("=", 1)[0].strip().upper()
        if key_part in updates:
            value = updates[key_part]
            if value is None or value == "":
                # 保留注释掉的原行，方便管理员知道有这个配置项
                new_lines.append(f"# {key_part}=")
            else:
                new_lines.append(f"{key_part}={value}")
            updated_keys.add(key_part)
        else:
            new_lines.append(line)

    # 追加未出现过的新键
    appended = False
    for key, value in updates.items():
        if key not in updated_keys and value:
            if not appended:
                new_lines.append("")  # 空行分隔
                new_lines.append("# Code repository settings (managed by admin UI)")
                appended = True
            new_lines.append(f"{key}={value}")

    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("Updated .env with keys: %s", list(updates.keys()))


# ─────────────────────── In-Memory Sync ────────────────────────────

def _sync_settings(
    oam_url: Optional[str],
    stack_url: Optional[str],
    git_token: Optional[str],
    clone_depth: int,
) -> None:
    """将新值同步到全局 settings 对象，使变更立即生效（无需重启）。"""
    try:
        if oam_url is not None:
            settings.code_repo_oam_url = oam_url or None  # type: ignore[assignment]
        if stack_url is not None:
            settings.code_repo_stack_url = stack_url or None  # type: ignore[assignment]
        if git_token is not None:
            settings.code_repo_git_token = git_token or None  # type: ignore[assignment]
        settings.code_repo_clone_depth = max(1, int(clone_depth))
    except Exception as exc:
        logger.warning("Failed to sync settings in-memory: %s", exc)


# ─────────────────────── Public API ────────────────────────────────

def load_repo_settings() -> RepoSettings:
    """读取当前 Git 仓库配置（合并 .env 文件和 in-memory settings）。"""
    oam_url   = settings.code_repo_oam_url   or ""
    stack_url = settings.code_repo_stack_url or ""
    token_set = bool(settings.code_repo_git_token)
    depth     = max(1, int(settings.code_repo_clone_depth or 1))

    # 尝试从 .env 文件直接读取（in-memory 可能因重启被重置）
    lines = _read_env_lines()
    env_map: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env_map[k.strip().upper()] = v.strip()

    if not oam_url:
        oam_url = env_map.get(_KEY_OAM_URL, "")
    if not stack_url:
        stack_url = env_map.get(_KEY_STACK_URL, "")
    if not token_set and _KEY_GIT_TOKEN in env_map and env_map[_KEY_GIT_TOKEN]:
        token_set = True
    if _KEY_CLONE_DEPTH in env_map:
        try:
            depth = max(1, int(env_map[_KEY_CLONE_DEPTH]))
        except ValueError:
            pass

    return RepoSettings(
        oam_url       = oam_url,
        stack_url     = stack_url,
        git_token_set = token_set,
        clone_depth   = depth,
        updated_at    = datetime.utcnow().isoformat(),
    )


def save_repo_settings(
    oam_url: Optional[str],
    stack_url: Optional[str],
    git_token: Optional[str],
    clone_depth: int = 1,
    clear_token: bool = False,
) -> RepoSettings:
    """保存 Git 仓库配置：写入 .env 并同步到 in-memory settings。

    参数说明：
    - oam_url / stack_url: 传 None 表示不修改，传 "" 表示清空
    - git_token: 传 None 表示不修改；传 "" 或 clear_token=True 表示清除
    - clone_depth: 浅克隆深度（最小 1）
    """
    depth = max(1, int(clone_depth))
    current = load_repo_settings()

    # 构建 .env 更新字典
    env_updates: dict[str, Optional[str]] = {
        _KEY_CLONE_DEPTH: str(depth),
    }

    final_oam   = current.oam_url
    final_stack = current.stack_url
    final_token: Optional[str] = None  # None = 不改

    if oam_url is not None:
        final_oam = oam_url.strip()
        env_updates[_KEY_OAM_URL] = final_oam or None

    if stack_url is not None:
        final_stack = stack_url.strip()
        env_updates[_KEY_STACK_URL] = final_stack or None

    if clear_token or (git_token is not None and git_token == ""):
        env_updates[_KEY_GIT_TOKEN] = None
        final_token = ""
    elif git_token is not None and git_token != _TOKEN_MASK:
        env_updates[_KEY_GIT_TOKEN] = git_token.strip()
        final_token = git_token.strip()

    _write_env_updates(env_updates)
    _sync_settings(
        oam_url    = final_oam   if oam_url   is not None else None,
        stack_url  = final_stack if stack_url is not None else None,
        git_token  = final_token,
        clone_depth = depth,
    )

    logger.info(
        "Repo settings saved: oam=%s stack=%s token_set=%s depth=%d",
        bool(final_oam), bool(final_stack), bool(env_updates.get(_KEY_GIT_TOKEN)), depth,
    )
    return load_repo_settings()


# ─────────────────────── Connection Test ───────────────────────────

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

    # 确定认证方式
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
            # SSH URL：需要 SSH key，目前不支持，直接测试连通性
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
