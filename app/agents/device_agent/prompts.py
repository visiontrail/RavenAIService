"""读取并渲染 ``claude_agent_device.*`` 提示词。

prompts_config.yaml 结构：

```yaml
claude_agent_device:
  default:
    system_prompt: |
      ...
    user_prompt_template: |
      ...
    risk_rules:
      - {server: "*", tool: "*list*",   risk: "read"}
      - {server: "*", tool: "*upgrade*", risk: "destructive"}
```

调用方拿到 ``(system_prompt, user_prompt_template, risk_rules)`` 三元组后
再拼装历史与当前用户消息（详见 ``device_agent.agent``）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

_PROMPTS_CACHE: Dict[str, Any] = {}


_DEFAULT_SCENE = "default"


def _load_config() -> Dict[str, Any]:
    if _PROMPTS_CACHE:
        return _PROMPTS_CACHE

    import os

    from app.config import settings

    raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
    if os.path.isabs(raw):
        path = Path(raw)
    else:
        project_root = Path(__file__).resolve().parents[3]
        path = (project_root / raw).resolve()

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _PROMPTS_CACHE
    parsed = yaml.safe_load(content) or {}
    _PROMPTS_CACHE.update(parsed)
    return _PROMPTS_CACHE


def _scene_config(scene_hint: Optional[str]) -> Dict[str, Any]:
    config = _load_config()
    agent_config: Dict[str, Any] = config.get("claude_agent_device") or {}
    if scene_hint:
        variant = agent_config.get(scene_hint)
        if isinstance(variant, dict):
            return variant
    return agent_config.get(_DEFAULT_SCENE) or {}


def get_prompts(scene_hint: Optional[str] = None) -> Tuple[str, str]:
    """返回 ``(system_prompt, user_prompt_template)``。

    缺失/为空时返回空字符串；DeviceAgent.run 会在拼接 prompt 时把空模板退化为
    "直接附加历史 + 当前消息"。
    """
    variant = _scene_config(scene_hint)
    system_prompt = variant.get("system_prompt") or ""
    user_prompt_template = variant.get("user_prompt_template") or ""
    if isinstance(system_prompt, str):
        system_prompt = system_prompt.strip()
    else:
        system_prompt = ""
    if isinstance(user_prompt_template, str):
        user_prompt_template = user_prompt_template.strip()
    else:
        user_prompt_template = ""
    return system_prompt, user_prompt_template


def get_risk_rules(scene_hint: Optional[str] = None) -> List[Dict[str, str]]:
    """返回风险规则列表，按 yaml 中声明顺序匹配。

    每条规则形如 ``{"server": "<glob>", "tool": "<glob>", "risk": "read|write|destructive"}``。
    未声明时返回空列表，``permissions.classify_risk`` 会兜底为 ``"write"``。
    """
    variant = _scene_config(scene_hint)
    rules = variant.get("risk_rules")
    if not isinstance(rules, list):
        return []
    out: List[Dict[str, str]] = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk") or "").strip().lower()
        if risk not in {"read", "write", "destructive"}:
            continue
        out.append({
            "server": str(item.get("server") or "*"),
            "tool": str(item.get("tool") or "*"),
            "risk": risk,
        })
    return out


def render_user_prompt(
    user_prompt_template: str,
    *,
    user_message: str,
    history_block: str = "",
    target_device_id: str = "",
    target_device_name: str = "",
    session_id: str = "",
) -> str:
    """把模板渲染成最终 user prompt。

    模板里允许引用 ``{user_message}`` / ``{history_block}`` / ``{target_device_id}``
    / ``{target_device_name}`` / ``{session_id}`` 五个占位符；不出现时原样返回。
    模板为空字符串时，回退为 ``f"{history_block}\\n\\n[user] {user_message}"``。
    """
    if not user_prompt_template:
        if history_block:
            return f"{history_block}\n\n[user] {user_message}".strip()
        return user_message
    try:
        return user_prompt_template.format(
            user_message=user_message,
            history_block=history_block,
            target_device_id=target_device_id,
            target_device_name=target_device_name,
            session_id=session_id,
        )
    except (KeyError, IndexError):
        # 模板里出现未知占位符时直接返回原文 + 用户消息，避免崩溃。
        return f"{user_prompt_template}\n\n[user] {user_message}".strip()


def reset_cache() -> None:
    """清空内存缓存（admin 改完 prompts_config.yaml 后调用）。"""
    _PROMPTS_CACHE.clear()
