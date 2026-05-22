"""DeviceAgent 会话级工作区管理。

不同于 ``log_analysis.workspace``（要解压归档、放 task.json、克隆代码仓库），
DeviceAgent 的工作区只承担一件事：为本次 ``query()`` 调用准备一个临时目录，
让 ``skills_service.materialize_enabled_skills`` 可以把启用的 Skill 包写到
``<workspace>/.claude/skills/<name>/`` 下，并在请求结束时幂等清理。
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _resolve_base_dir() -> Path:
    """会话工作区根目录。复用 ``code_repo_clone_base_dir`` 作为父目录，
    避免再引入新配置项；DeviceAgent 与 LogAnalysis 工作区按 ``device_agent_``
    前缀区分。"""
    from app.config import settings

    raw = getattr(settings, "code_repo_clone_base_dir", "temp/code_repos")
    base = Path(raw)
    if not base.is_absolute():
        base = (Path(settings.base_dir) / base).resolve() if hasattr(settings, "base_dir") else base.resolve()
    return base


def prepare_session(session_id: Optional[str]) -> Path:
    """创建 ``<base>/device_agent/<session_id>-<uuid>/`` 临时工作区。

    返回工作区根目录的绝对 :class:`Path`。调用方负责在 ``finally`` 中调用
    :func:`cleanup` 清理。
    """
    safe_session = (session_id or "anon").strip() or "anon"
    # 防止 session_id 含路径分隔符 / 控制字符 — 仅保留 ASCII alnum/dash/underscore
    safe_session = "".join(ch for ch in safe_session if ch.isalnum() or ch in ("-", "_"))[:64] or "anon"

    base = _resolve_base_dir() / "device_agent"
    workspace = base / f"{safe_session}-{uuid.uuid4().hex[:12]}"
    skills_dir = workspace / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    logger.info("DeviceAgent workspace prepared: session=%s path=%s", safe_session, workspace)
    return workspace


def cleanup(path: Optional[Path]) -> None:
    """幂等清理工作区目录。``path`` 为空 / 不存在时静默忽略。"""
    if path is None:
        return
    try:
        p = Path(path)
    except TypeError:
        return
    if not p.exists():
        return
    shutil.rmtree(str(p), ignore_errors=True)
    logger.info("DeviceAgent workspace cleaned: %s", p)
