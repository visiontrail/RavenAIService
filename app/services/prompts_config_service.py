"""
Service helpers for reading and updating the prompts_config.yaml file.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import HTTPException, status

from app.config import settings

DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE = """
你是对话标题生成助手。请基于以下信息生成一个中文会话标题：
- 标题需要概括用户核心诉求或问题。
- 长度不超过 {max_length} 个字。
- 不要使用引号、冒号、序号、emoji、换行。
- 只输出标题文本，不要输出解释。

用户消息：
{user_content}

助手回复：
{ai_content}
""".strip()


def _resolve_prompts_path() -> Path:
    raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
    if os.path.isabs(raw):
        return Path(raw)
    project_root = Path(__file__).resolve().parents[2]  # repository root
    return (project_root / raw).resolve()


def _compute_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _summarize_prompts(parsed: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "log_type_keys": [],
        "has_default_plan": False,
        "has_default_summary": False,
    }
    if isinstance(parsed, dict):
        log_types = parsed.get("log_types")
        if isinstance(log_types, dict):
            summary["log_type_keys"] = sorted(log_types.keys())
            default_entry = log_types.get("default")
            if isinstance(default_entry, dict):
                summary["has_default_plan"] = "plan_prompt" in default_entry
                summary["has_default_summary"] = "summary_prompt" in default_entry
        else:
            summary["log_type_keys"] = []
        if "plan_prompt" in parsed:
            summary["has_default_plan"] = True
        if "summary_prompt" in parsed:
            summary["has_default_summary"] = True
    return summary


def load_prompts_config() -> Dict[str, Any]:
    """Return file content and metadata for prompts_config.yaml."""
    path = _resolve_prompts_path()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompts config not found at {path}",
        ) from exc

    stat = path.stat()
    try:
        parsed = yaml.safe_load(content)
    except Exception:
        parsed = None

    return {
        "path": str(path),
        "content": content,
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
        "size": stat.st_size,
        "checksum": _compute_checksum(content),
        "summary": _summarize_prompts(parsed),
    }


def update_prompts_config(
    new_content: str,
    expected_checksum: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Validate and persist prompts_config.yaml.

    Raises:
        HTTPException 400: YAML invalid
        HTTPException 409: checksum mismatch when force=False
    """
    path = _resolve_prompts_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    try:
        parsed = yaml.safe_load(new_content)
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"YAML parse error: {exc}",
        ) from exc

    current_checksum = None
    if path.exists():
        current_checksum = _compute_checksum(path.read_text(encoding="utf-8"))
        if expected_checksum and current_checksum != expected_checksum and not force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="File changed on disk. Reload and retry or set force=true.",
            )

    # Atomic write to prevent partial saves
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        tmp.write(new_content)
        temp_name = tmp.name
    Path(temp_name).replace(path)

    # Invalidate cached claude_agent_log_analysis prompts so new values take effect immediately
    try:
        from app.agents.log_analysis import prompts as log_analysis_prompts

        if hasattr(log_analysis_prompts, "_PROMPTS_CACHE"):
            log_analysis_prompts._PROMPTS_CACHE.clear()  # type: ignore[attr-defined]
    except Exception:
        pass

    stat = path.stat()
    checksum = _compute_checksum(new_content)
    return {
        "path": str(path),
        "content": new_content,
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
        "size": stat.st_size,
        "checksum": checksum,
        "summary": _summarize_prompts(parsed),
    }


def get_chat_title_prompt_template() -> str:
    """Load chat title prompt template from prompts_config.yaml."""
    path = _resolve_prompts_path()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE

    try:
        parsed = yaml.safe_load(content)
    except Exception:
        return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE

    if not isinstance(parsed, dict):
        return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE

    chat_cfg = parsed.get("chat")
    if not isinstance(chat_cfg, dict):
        return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE

    raw_prompt = chat_cfg.get("session_title_prompt")
    if isinstance(raw_prompt, dict):
        template = raw_prompt.get("template")
    elif isinstance(raw_prompt, str):
        template = raw_prompt
    else:
        template = None

    if isinstance(template, str) and template.strip():
        return template.strip()
    return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE
