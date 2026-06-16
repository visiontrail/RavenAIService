"""
Project 级系统提示词管理服务。

让系统提示词也能像 Skill 一样分级处理：

- **Agent 级（基础层）**：来自 ``prompts_config.yaml``，按 agent + locale 选择，
  是每个 Agent 的通用系统提示词。
- **Project 级（追加层）**：用户针对单个 ``project_code`` 追加的系统提示词，
  用于限定该项目的专属约束（可以为空）。本服务负责存取这一层。

存储布局（按 project_code 隔离，与 Project Skills 平行）：

    data/project_prompts/
    └── <project_code>/
        └── system_prompt.md

读取走文件系统、无缓存，Admin 编辑后立即对后续 Agent 运行生效。Agent 运行前
调用 :func:`build_project_prompt_addendum` 拿到要拼接到基础系统提示词之后的
项目级附加段（无内容时返回空串）。
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 单个项目系统提示词的字符上限，防止异常大文件拖垮上下文 / 存储。
MAX_PROJECT_PROMPT_CHARS = 20000

_PROMPT_FILENAME = "system_prompt.md"


class ProjectPromptError(Exception):
    """项目提示词管理基础异常。"""


class ProjectPromptValidationError(ProjectPromptError):
    """project_code 非法或内容超限。"""


# ─────────────────────── Path helpers ──────────────────────────────

def _project_prompts_root() -> Path:
    from app.config import settings

    return Path(settings.project_prompts_data_dir)


def validate_project_code(project_code: str) -> str:
    """规范化 project_code（去空白 + 小写），与 skills_service 保持一致。"""
    if not project_code or not project_code.strip():
        raise ProjectPromptValidationError("project_code 不能为空")
    return project_code.strip().lower()


def _prompt_path(project_code: str) -> Path:
    code = validate_project_code(project_code)
    return _project_prompts_root() / code / _PROMPT_FILENAME


# ─────────────────────── Public API ────────────────────────────────

def get_project_prompt(project_code: str) -> Dict[str, Any]:
    """返回项目系统提示词的可读视图。

    Always returns a dict; ``content`` 为空串且 ``exists=False`` 表示该项目
    尚未配置项目级提示词。
    """
    path = _prompt_path(project_code)
    if not path.is_file():
        return {
            "project_code": validate_project_code(project_code),
            "content": "",
            "exists": False,
            "updated_at": None,
            "size_bytes": 0,
        }
    content = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    return {
        "project_code": validate_project_code(project_code),
        "content": content,
        "exists": True,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size_bytes": stat.st_size,
    }


def get_project_prompt_text(project_code: Optional[str]) -> str:
    """便捷读取：仅返回提示词正文，无内容时返回空串、绝不抛错。"""
    if not project_code:
        return ""
    try:
        path = _prompt_path(project_code)
    except ProjectPromptValidationError:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:  # noqa: BLE001
        logger.warning("get_project_prompt_text failed for %s: %s", project_code, exc)
        return ""


def set_project_prompt(project_code: str, content: str) -> Dict[str, Any]:
    """写入（或清空）项目系统提示词。

    空内容会删除底层文件，等价于“未配置”。返回写入后的可读视图。
    """
    if content is None:
        content = ""
    if len(content) > MAX_PROJECT_PROMPT_CHARS:
        raise ProjectPromptValidationError(
            f"系统提示词长度 {len(content)} 超过上限 {MAX_PROJECT_PROMPT_CHARS}"
        )

    code = validate_project_code(project_code)
    path = _prompt_path(code)

    if not content.strip():
        # 空内容视为清除：删除文件（若存在）。
        if path.exists():
            path.unlink()
            logger.info("project prompt cleared: project=%s", code)
        return get_project_prompt(code)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    logger.info("project prompt saved: project=%s size=%d", code, len(content))
    return get_project_prompt(code)


def delete_project_prompt(project_code: str) -> None:
    """删除项目系统提示词（含其目录，若已为空）。"""
    code = validate_project_code(project_code)
    path = _prompt_path(code)
    if path.exists():
        path.unlink()
    project_dir = path.parent
    try:
        if project_dir.is_dir() and not any(project_dir.iterdir()):
            shutil.rmtree(project_dir, ignore_errors=True)
    except OSError:
        pass
    logger.info("project prompt deleted: project=%s", code)


def build_project_prompt_addendum(
    project_code: Optional[str],
    *,
    project_name: Optional[str] = None,
) -> str:
    """构建拼接到基础系统提示词之后的项目级附加段。

    无项目级提示词时返回空串。返回的内容包含一个清晰的小标题，并声明该段是
    针对当前项目的专属约束，优先级高于通用约束（但不得违背安全/格式底线）。
    """
    text = get_project_prompt_text(project_code)
    if not text:
        return ""

    label = (project_name or "").strip() or validate_project_code(project_code)
    return (
        "\n\n## 项目级附加系统指令（{label}）\n"
        "以下是管理员针对当前项目「{label}」配置的专属系统指令。在不违背安全"
        "约束与最终输出格式要求的前提下，这些项目特定的约束优先于通用指令，"
        "你必须严格遵守：\n\n"
        "{text}\n"
    ).format(label=label, text=text)
