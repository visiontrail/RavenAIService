"""
读取并渲染 claude_agent_log_analysis 通用提示词。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import yaml

from app.i18n.prompts import select_localized_body

_PROMPTS_CACHE: Dict[str, Any] = {}


def _load_config() -> Dict[str, Any]:
    if _PROMPTS_CACHE:
        return _PROMPTS_CACHE

    from app.config import settings
    from pathlib import Path
    import os

    raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
    if os.path.isabs(raw):
        path = Path(raw)
    else:
        project_root = Path(__file__).resolve().parents[3]
        path = (project_root / raw).resolve()

    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    _PROMPTS_CACHE.update(parsed or {})
    return _PROMPTS_CACHE


def get_prompts(
    project_code: Optional[str] = None,
    locale: Optional[str] = None,
) -> Tuple[str, str]:
    """Return the generic (system_prompt, user_prompt_template) for ``locale``.

    ``project_code`` is kept for caller compatibility, but prompt selection
    does not vary by project. ``locale`` selects the per-language body, falling
    back to the default language (``zh``) when a variant is missing; a legacy
    flat-string body is returned unchanged.
    """
    config = _load_config()
    agent_config: Dict[str, Any] = config.get("claude_agent_log_analysis", {})
    variant = agent_config.get("generic") or {}

    system_prompt = select_localized_body(variant.get("system_prompt"), locale)
    user_prompt_template = select_localized_body(
        variant.get("user_prompt_template"), locale
    )

    return system_prompt, user_prompt_template


def render_user_prompt(
    user_prompt_template: str,
    *,
    task_id: str,
    workspace_dir: str = "",
    question: str,
    project_code: Optional[str] = None,
    hints: str,
) -> str:
    replacements = {
        "task_id": task_id,
        "workspace_dir": workspace_dir,
        "question": question,
        "project_code": project_code or "generic",
        # 保留 {log_type} 占位符向后兼容旧模板
        "log_type": project_code or "generic",
        "hints": hints or "",
    }
    rendered = user_prompt_template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered
