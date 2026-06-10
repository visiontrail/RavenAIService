"""
重构包检索工作区准备与清理。

职责（与 ``project_expert/workspace.py`` 同构）：
- 为每次运行在隔离临时目录下创建 **只含 `repo/` 占位目录 + `task.json`**
  的工作区（没有 `logs/`、不解压任何归档、不要求 metadata.json）。
- 把用户显式选择的项目仓库身份写入 `task.json.repo_info`
  （`source="user_selected_project_repo"`），**不写入任何 git token**。
- 任务结束后幂等清理临时目录。
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from app.i18n import DEFAULT as I18N_DEFAULT

logger = logging.getLogger(__name__)


# ─────────────────────── Exceptions ────────────────────────────────

class WorkspaceError(Exception):
    """工作区相关错误基类。"""


class MissingProjectRepoError(WorkspaceError):
    """未提供项目仓库（project_repo），无法确定项目身份。"""


# ─────────────────────── Data Structures ───────────────────────────

@dataclass
class WorkspaceContext:
    """重构包检索工作区上下文。

    与 project_expert 的 ``WorkspaceContext`` 同构——本智能体同样不处理
    日志归档，只多了 ``project_code``（包元数据 MCP 工具的服务端过滤键）。
    """

    task_id: str
    temp_dir: str           # 绝对路径，如 /base/clone_dirs/<task_id>/
    repo_dir: str           # temp_dir/repo/
    task_json_path: str     # temp_dir/task.json
    project_code: str = ""  # 本次运行绑定的项目代号（包工具按此过滤）
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Active locale for this run (drives prompt selection + the response-language
    # directive). Resolved from the request/owner at stream time; defaults to the
    # system default so legacy callers keep working.
    locale: str = I18N_DEFAULT


# ─────────────────────── Public API ────────────────────────────────

def prepare(
    *,
    project_repo: Any,
    question: str,
    hints: str = "",
    session_id: Optional[str] = None,
) -> WorkspaceContext:
    """准备重构包检索工作区。

    只创建 ``repo/`` 占位目录并写入 ``task.json``；不解压归档、不校验
    metadata.json、不在磁盘上落 git token。

    Args:
        project_repo: ProjectRepo ORM 对象（含 project_code / project_name /
            repo_url / default_branch 等字段）。权威的项目身份来源。
        question: 用户问题。
        hints: 可选的对话上下文提示。
        session_id: 可选的会话 id，仅用于日志关联。

    Returns:
        WorkspaceContext

    Raises:
        MissingProjectRepoError: project_repo 为空。
    """
    if project_repo is None:
        raise MissingProjectRepoError("project_repo is required for Package Search workspace")

    task_id = str(uuid.uuid4())
    base_dir = Path(settings.code_repo_clone_base_dir)
    temp_dir = base_dir / task_id
    repo_dir = temp_dir / "repo"

    try:
        repo_dir.mkdir(parents=True, exist_ok=True)

        repo_info = {
            "project_code": getattr(project_repo, "project_code", None),
            "project_name": getattr(project_repo, "project_name", None),
            "repo_url": getattr(project_repo, "repo_url", None),
            "default_branch": getattr(project_repo, "default_branch", None),
            "source": "user_selected_project_repo",
        }
        # task.json 仅含非敏感字段 —— 绝不写入 git token。
        task_data = {
            "question": question or "",
            "hints": hints or "",
            "repo_info": repo_info,
        }
        task_json_path = temp_dir / "task.json"
        task_json_path.write_text(
            json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Package Search workspace prepared: task_id=%s temp_dir=%s project_code=%s session_id=%s",
            task_id, temp_dir, repo_info.get("project_code"), session_id or "-",
        )
        return WorkspaceContext(
            task_id=task_id,
            temp_dir=str(temp_dir),
            repo_dir=str(repo_dir),
            task_json_path=str(task_json_path),
            project_code=str(repo_info.get("project_code") or ""),
            metadata={
                "question": question or "",
                "hints": hints or "",
                "repo_info": repo_info,
            },
        )
    except Exception:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise


def cleanup(ctx: WorkspaceContext) -> None:
    """幂等删除临时工作区目录。"""
    temp = Path(ctx.temp_dir)
    if temp.exists():
        shutil.rmtree(str(temp), ignore_errors=True)
        logger.info("Package Search workspace cleaned up: %s", ctx.temp_dir)
