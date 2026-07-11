"""Load and render the editable GeneralAgent prompts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from app.i18n.prompts import select_localized_body

_PROMPTS_CACHE: Dict[str, Any] = {}


def _load_config() -> Dict[str, Any]:
    if _PROMPTS_CACHE:
        return _PROMPTS_CACHE

    from app.config import settings

    raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
    if os.path.isabs(raw):
        path = Path(raw)
    else:
        project_root = Path(__file__).resolve().parents[3]
        path = (project_root / raw).resolve()

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    _PROMPTS_CACHE.update(parsed or {})
    return _PROMPTS_CACHE


def reset_cache() -> None:
    _PROMPTS_CACHE.clear()


def get_prompts(locale: Optional[str] = None) -> Tuple[str, str]:
    """Return the localized GeneralAgent system and user prompt templates."""
    config = _load_config()
    agent_config: Dict[str, Any] = config.get("claude_agent_general", {})
    variant = agent_config.get("generic") or {}
    system_prompt = select_localized_body(variant.get("system_prompt"), locale)
    user_prompt_template = select_localized_body(
        variant.get("user_prompt_template"), locale
    )
    return system_prompt, user_prompt_template


def render_user_prompt(
    user_prompt_template: str,
    *,
    user_message: str,
    conversation_history: str = "",
) -> str:
    """Render history and the latest user message without ``str.format`` hazards."""
    history_block = ""
    if conversation_history.strip():
        history_block = (
            "<conversation_history>\n"
            f"{conversation_history.strip()}\n"
            "</conversation_history>\n\n"
        )
    rendered = user_prompt_template or "{conversation_history_block}{user_message}"
    return (
        rendered.replace("{conversation_history_block}", history_block)
        .replace("{conversation_history}", conversation_history)
        .replace("{user_message}", user_message)
    )


__all__ = ["get_prompts", "render_user_prompt", "reset_cache"]
