"""
读取并渲染 claude_agent_log_analysis 提示词，按 log_type 选择变体。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import yaml

_PROMPTS_CACHE: Dict[str, Any] = {}

_LOG_TYPE_ALIASES = {
    "stack": "protocol_stack",
    "oam_antenna": "generic",
    "full": "generic",
}


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
        project_root = Path(__file__).resolve().parents[4]
        path = (project_root / raw).resolve()

    content = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    _PROMPTS_CACHE.update(parsed or {})
    return _PROMPTS_CACHE


def get_prompts(log_type: Optional[str] = None) -> Tuple[str, str]:
    """Return (system_prompt, user_prompt_template) for the given log_type.

    Falls back to 'generic' if the specific variant is unavailable.
    """
    config = _load_config()
    agent_config: Dict[str, Any] = config.get("claude_agent_log_analysis", {})

    # Normalize log_type to a variant key
    variant_key = (log_type or "generic").lower()
    variant_key = _LOG_TYPE_ALIASES.get(variant_key, variant_key)

    variant = agent_config.get(variant_key) or agent_config.get("generic") or {}

    system_prompt = variant.get("system_prompt", "")
    user_prompt_template = variant.get("user_prompt_template", "")

    return system_prompt.strip(), user_prompt_template.strip()


def render_user_prompt(
    user_prompt_template: str,
    *,
    task_id: str,
    question: str,
    log_type: Optional[str],
    hints: str,
) -> str:
    return user_prompt_template.format(
        task_id=task_id,
        question=question,
        log_type=log_type or "generic",
        hints=hints or "",
    )
