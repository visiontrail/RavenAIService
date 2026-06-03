"""
Bug Fix Coding Agent 工作区准备与清理。

职责：
- 为每个 Bug 修复任务在隔离临时目录下浅克隆项目仓库（复用 ``build_clone_url``
  注入 token，token 仅用于 clone 命令，不写入 task.json）
- 写入 task.json（仅含非敏感字段：任务总结、proposed_fixes、来源、默认分支、git 身份）
- 任务结束后幂等清理临时目录

工作区布局对齐 log_analysis：``temp_dir/`` 下含 ``repo/``（克隆出的源码）与
``task.json``。Agent 的 cwd 设为 ``temp_dir``，git 操作在 ``repo/`` 中进行。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.log_analysis.mcp_tools import build_clone_url
from app.agents.log_analysis.trace import mask_tokens
from app.config import settings

logger = logging.getLogger(__name__)


class BugFixWorkspaceError(Exception):
    """Bug 修复工作区相关错误基类。"""


class CloneFailedError(BugFixWorkspaceError):
    """git clone 失败。"""


@dataclass
class BugFixWorkspaceContext:
    task_id: str            # bug_fix_task.id（非 celery id）
    temp_dir: str           # 绝对路径，如 /base/<uuid>/
    repo_dir: str           # temp_dir/repo/
    task_json_path: str     # temp_dir/task.json
    default_branch: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def _git_identity() -> Dict[str, str]:
    """提交身份。固定为系统账号，便于在 MR/提交历史中识别自动修复来源。"""
    return {"name": "RavenAI Bug Fix Agent", "email": "bot@ravenai.local"}


def prepare(
    *,
    bug_fix_task_id: str,
    repo_url: str,
    default_branch: str,
    git_token: Optional[str],
    title: str,
    summary: Optional[str],
    proposed_fixes: List[Dict[str, Any]],
    source_log_id: Optional[str] = None,
    source_analysis_task_id: Optional[str] = None,
) -> BugFixWorkspaceContext:
    """准备隔离工作区并浅克隆仓库。

    Raises:
        CloneFailedError: git clone 失败（错误信息已脱敏）
    """
    workspace_id = str(uuid.uuid4())
    base_dir = Path(settings.code_repo_clone_base_dir)
    temp_dir = base_dir / workspace_id
    repo_dir = temp_dir / "repo"

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)

        clone_url = build_clone_url(repo_url, git_token or None)
        # 浅克隆默认分支以加速；--single-branch 限制只取默认分支。
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            default_branch,
            clone_url,
            str(repo_dir),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            # 退化：某些仓库默认分支名不确定时，去掉 --branch 再试一次。
            fallback = [
                "git",
                "clone",
                "--depth",
                "1",
                clone_url,
                str(repo_dir),
            ]
            proc = subprocess.run(
                fallback, capture_output=True, text=True, timeout=600
            )
            if proc.returncode != 0:
                raise CloneFailedError(
                    f"git clone failed: {mask_tokens(proc.stderr or proc.stdout or '')}"
                )

        # 配置提交身份（仅在该 clone 内生效）。
        identity = _git_identity()
        for key, value in (("user.name", identity["name"]), ("user.email", identity["email"])):
            subprocess.run(
                ["git", "-C", str(repo_dir), "config", key, value],
                capture_output=True,
                text=True,
                timeout=30,
            )

        task_data = {
            "bug_fix_task_id": bug_fix_task_id,
            "title": title,
            "summary": summary or "",
            "proposed_fixes": proposed_fixes,
            "source_log_id": source_log_id,
            "source_analysis_task_id": source_analysis_task_id,
            "default_branch": default_branch,
            "git_identity": identity,
        }
        task_json_path = temp_dir / "task.json"
        task_json_path.write_text(
            json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Bug fix workspace prepared: task=%s temp_dir=%s branch=%s",
            bug_fix_task_id,
            temp_dir,
            default_branch,
        )
        return BugFixWorkspaceContext(
            task_id=bug_fix_task_id,
            temp_dir=str(temp_dir),
            repo_dir=str(repo_dir),
            task_json_path=str(task_json_path),
            default_branch=default_branch,
            metadata={"title": title, "proposed_fixes": proposed_fixes},
        )
    except BugFixWorkspaceError:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise CloneFailedError(f"git clone timed out: {exc}") from exc
    except Exception:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise


def cleanup(ctx: BugFixWorkspaceContext) -> None:
    """幂等删除临时工作区目录。"""
    temp = Path(ctx.temp_dir)
    if temp.exists():
        shutil.rmtree(str(temp), ignore_errors=True)
        logger.info("Bug fix workspace cleaned up: %s", ctx.temp_dir)
