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

from app.i18n.prompts import select_localized_body

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


def get_prompts(
    scene_hint: Optional[str] = None,
    locale: Optional[str] = None,
) -> Tuple[str, str]:
    """返回 ``(system_prompt, user_prompt_template)``。

    ``locale`` 选择每种语言的提示词正文，缺失某语言时回退到默认语言（``zh``）；
    旧的扁平字符串正文原样返回。缺失/为空时返回空字符串；DeviceAgent.run
    会在拼接 prompt 时把空模板退化为"直接附加历史 + 当前消息"。
    """
    variant = _scene_config(scene_hint)
    system_prompt = select_localized_body(variant.get("system_prompt"), locale)
    user_prompt_template = select_localized_body(
        variant.get("user_prompt_template"), locale
    )
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


_CLARIFICATION_GUIDANCE = {
    "zh": (
        "## 何时向用户提问（mcp__ask__AskUserQuestion）\n"
        "当且仅当满足以下情形时，调用 `mcp__ask__AskUserQuestion` 工具向用户澄清：\n"
        "- 缺少执行所必需的关键参数；\n"
        "- 指令存在多种合理且后果不同的解读；\n"
        "- 操作目标对象/范围不明确，猜错代价较高。\n"
        "必须使用完整工具名 `mcp__ask__AskUserQuestion`；不要调用 Claude CLI 内置的"
        "同名 `AskUserQuestion` 工具，后者未接入本产品的提问卡片。\n"
        "能够根据上下文合理推断时，不要打断用户，直接继续。\n"
        "提问时：把需要澄清的点尽量在一次调用里问全（每个问题给 2–4 个预设选项，"
        "并配简短说明）；本轮最多可提问 {max_rounds} 次，达上限后请基于已知信息自行决断。"
    ),
    "en": (
        "## When to ask the user (mcp__ask__AskUserQuestion)\n"
        "Call `mcp__ask__AskUserQuestion` to clarify only when:\n"
        "- a required parameter for the action is missing;\n"
        "- the instruction has multiple reasonable interpretations with different outcomes;\n"
        "- the target/scope is ambiguous and guessing wrong is costly.\n"
        "Always use the full name `mcp__ask__AskUserQuestion`; never use Claude CLI's "
        "built-in `AskUserQuestion`, which is not connected to RavenAI's clarification card.\n"
        "If you can reasonably infer intent from context, do NOT interrupt — just proceed.\n"
        "When you do ask, batch everything you need into a single call (2–4 preset options "
        "with short descriptions per question). You may ask at most {max_rounds} time(s) this "
        "run; once the cap is hit, decide using the information you have."
    ),
}


def clarification_guidance(locale: Optional[str] = None, *, max_rounds: int = 5) -> str:
    """返回 AskUserQuestion 使用指引（按 locale），供 system prompt 末尾追加。

    仅在 ``clarification_enabled`` 为真时由调用方拼接；禁用澄清时不应出现。
    """
    lang = (locale or "zh").strip().lower()
    body = _CLARIFICATION_GUIDANCE.get(lang) or _CLARIFICATION_GUIDANCE["zh"]
    try:
        return body.format(max_rounds=max_rounds)
    except (KeyError, IndexError):
        return body


def reset_cache() -> None:
    """清空内存缓存（admin 改完 prompts_config.yaml 后调用）。"""
    _PROMPTS_CACHE.clear()
