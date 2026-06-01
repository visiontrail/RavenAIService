"""
读取并渲染 claude_agent_project_expert 通用提示词。

结构对齐 ``app/agents/log_analysis/prompts.py``，但读取
``claude_agent_project_expert`` 键，且没有 log_type 维度。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import yaml

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


def get_prompts() -> Tuple[str, str]:
    """Return the generic (system_prompt, user_prompt_template)."""
    config = _load_config()
    agent_config: Dict[str, Any] = config.get("claude_agent_project_expert", {})
    variant = agent_config.get("generic") or {}

    system_prompt = variant.get("system_prompt", "")
    user_prompt_template = variant.get("user_prompt_template", "")

    return system_prompt.strip(), user_prompt_template.strip()


def render_user_prompt(
    user_prompt_template: str,
    *,
    task_id: str,
    workspace_dir: str = "",
    question: str,
    hints: str,
) -> str:
    replacements = {
        "task_id": task_id,
        "workspace_dir": workspace_dir,
        "question": question,
        "hints": hints or "",
    }
    rendered = user_prompt_template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered
