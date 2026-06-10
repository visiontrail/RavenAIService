"""
Service helpers for reading and updating editable prompt entries in
prompts_config.yaml.
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

PROMPT_FUNCTION_META: Dict[str, Dict[str, str]] = {
    "claude_agent_log_analysis": {
        "name": "日志分析",
        "description": "Claude Agent SDK 驱动的日志智能分析提示词",
    },
    "claude_agent_device": {
        "name": "设备对话",
        "description": "Claude Agent SDK 驱动的设备联动对话提示词",
    },
    "claude_agent_project_expert": {
        "name": "项目专家",
        "description": "Claude Agent SDK 驱动的项目源码问答提示词",
    },
    "claude_agent_package_search": {
        "name": "重构包检索",
        "description": "Claude Agent SDK 驱动的项目绑定重构包检索提示词",
    },
    "chat": {
        "name": "AI 对话",
        "description": "AI 对话相关提示词",
    },
}

PROMPT_AGENT_META: Dict[Tuple[str, str], Dict[str, str]] = {
    ("claude_agent_log_analysis", "generic"): {
        "name": "通用日志分析 Agent",
        "description": "统一适用于所有日志类型，按 metadata/task 中的代码库信息克隆代码并分析问题",
    },
    ("claude_agent_device", "default"): {
        "name": "默认设备对话 Agent",
        "description": "面向已链接设备的通用对话场景，模型直接选择设备 MCP 工具与参数",
    },
    ("claude_agent_project_expert", "generic"): {
        "name": "通用项目专家 Agent",
        "description": "面向已登记项目的源码答疑场景，按用户选择的项目仓库克隆代码并回答问题",
    },
    ("claude_agent_package_search", "generic"): {
        "name": "重构包配置管理员",
        "description": "面向所选项目的重构包检索场景，包元数据工具优先、必要时结合 Git 提交记录分析",
    },
}

PROMPT_FIELD_META: Dict[str, Dict[str, str]] = {
    "system_prompt": {
        "label": "系统提示词",
        "type": "system",
    },
}


class _LiteralString(str):
    """Marker used so PyYAML emits multiline prompts as block scalars."""


def _literal_string_representer(dumper: yaml.SafeDumper, data: _LiteralString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.SafeDumper.add_representer(_LiteralString, _literal_string_representer)


def _resolve_prompts_path() -> Path:
    raw = getattr(settings, "prompts_config_path", "app/prompts/prompts_config.yaml")
    if os.path.isabs(raw):
        return Path(raw)
    project_root = Path(__file__).resolve().parents[2]  # repository root
    return (project_root / raw).resolve()


def _compute_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _literalize_multiline(value: Any) -> Any:
    if isinstance(value, str) and "\n" in value:
        return _LiteralString(value)
    if isinstance(value, dict):
        return {key: _literalize_multiline(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_literalize_multiline(item) for item in value]
    return value


def _dump_prompts_config(parsed: Any) -> str:
    rendered = yaml.safe_dump(
        _literalize_multiline(parsed),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )
    return rendered if rendered.endswith("\n") else f"{rendered}\n"


def _summarize_prompts(parsed: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "log_type_keys": [],
        "has_default_plan": False,
        "has_default_summary": False,
        "function_keys": [],
        "editable_prompt_count": 0,
    }
    if isinstance(parsed, dict):
        summary["function_keys"] = sorted(
            key for key, value in parsed.items() if isinstance(value, dict)
        )
        summary["editable_prompt_count"] = len(_extract_prompt_entries(parsed))
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


def _path_set(root: Dict[str, Any], path: List[str], value: str) -> None:
    cursor: Any = root
    for key in path[:-1]:
        if not isinstance(cursor, dict) or key not in cursor:
            raise KeyError(".".join(path))
        cursor = cursor[key]
    if not isinstance(cursor, dict):
        raise KeyError(".".join(path))
    # The final key may be a not-yet-present language variant (e.g. authoring an
    # ``en`` body alongside an existing ``zh`` one), so the parent dict only has
    # to exist — the leaf key is allowed to be new.
    cursor[path[-1]] = value


def _extract_prompt_entries(parsed: Any) -> List[Dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []

    entries: List[Dict[str, Any]] = []
    for function_key, function_config in parsed.items():
        if not isinstance(function_config, dict):
            continue

        function_meta = PROMPT_FUNCTION_META.get(function_key, {})
        for agent_key, agent_config in function_config.items():
            if not isinstance(agent_config, dict):
                continue

            agent_meta = PROMPT_AGENT_META.get((function_key, agent_key), {})
            for prompt_key, field_meta in PROMPT_FIELD_META.items():
                raw = agent_config.get(prompt_key)
                # A body is either a legacy flat string or a per-language map
                # ({locale: body}). Normalize to a list of (locale, content)
                # pairs so each language is an independently editable entry; a
                # flat string keeps ``locale = None`` for backward compatibility.
                variants: List[Tuple[Optional[str], str]] = []
                if isinstance(raw, str):
                    variants.append((None, raw))
                elif isinstance(raw, dict):
                    for loc_code, loc_content in raw.items():
                        if isinstance(loc_code, str) and isinstance(loc_content, str):
                            variants.append((loc_code, loc_content))

                for locale_code, content in variants:
                    prompt_path = [function_key, agent_key, prompt_key]
                    if locale_code is not None:
                        prompt_path = prompt_path + [locale_code]
                    label = field_meta["label"]
                    if locale_code is not None:
                        label = f"{label} ({locale_code})"
                    entries.append(
                        {
                            "id": ".".join(prompt_path),
                            "function_key": function_key,
                            "function_name": function_meta.get("name") or function_key,
                            "function_description": function_meta.get("description"),
                            "agent_key": agent_key,
                            "agent_name": agent_meta.get("name") or agent_key,
                            "agent_description": agent_meta.get("description"),
                            "prompt_key": prompt_key,
                            "locale": locale_code,
                            "prompt_label": label,
                            "prompt_type": field_meta["type"],
                            "path": prompt_path,
                            "content": content,
                        }
                    )

    return entries


def _read_prompts_file(path: Path) -> Tuple[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompts config not found at {path}",
        ) from exc

    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"YAML parse error: {exc}",
        ) from exc
    return content, parsed


def _invalidate_prompt_caches() -> None:
    # Invalidate cached claude_agent_log_analysis prompts so new values take effect immediately.
    try:
        from app.agents.log_analysis import prompts as log_analysis_prompts

        if hasattr(log_analysis_prompts, "_PROMPTS_CACHE"):
            log_analysis_prompts._PROMPTS_CACHE.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    # Same for the device agent prompt cache.
    try:
        from app.agents.device_agent import prompts as device_agent_prompts

        device_agent_prompts.reset_cache()
    except Exception:
        pass
    # Same for the project expert agent prompt cache.
    try:
        from app.agents.project_expert import prompts as project_expert_prompts

        if hasattr(project_expert_prompts, "_PROMPTS_CACHE"):
            project_expert_prompts._PROMPTS_CACHE.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    # Same for the package search agent prompt cache.
    try:
        from app.agents.package_search import prompts as package_search_prompts

        if hasattr(package_search_prompts, "_PROMPTS_CACHE"):
            package_search_prompts._PROMPTS_CACHE.clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _response_data(path: Path, content: str, parsed: Any) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "content": content,
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
        "size": stat.st_size,
        "checksum": _compute_checksum(content),
        "summary": _summarize_prompts(parsed),
        "prompts": _extract_prompt_entries(parsed),
    }


def load_prompts_config() -> Dict[str, Any]:
    """Return file content, editable prompt entries, and metadata."""
    path = _resolve_prompts_path()
    content, parsed = _read_prompts_file(path)
    return _response_data(path, content, parsed)


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

    # Atomic write to prevent partial saves.
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        tmp.write(new_content)
        temp_name = tmp.name
    Path(temp_name).replace(path)

    _invalidate_prompt_caches()
    return _response_data(path, new_content, parsed)


def update_prompt_entries(
    prompt_updates: List[Dict[str, str]],
    expected_checksum: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Persist selected editable prompt entries without exposing raw YAML editing.

    Raises:
        HTTPException 400: YAML invalid or payload invalid
        HTTPException 409: checksum mismatch when force=False
        HTTPException 422: unknown/non-editable prompt id
    """
    path = _resolve_prompts_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    current_content, parsed = _read_prompts_file(path)
    current_checksum = _compute_checksum(current_content)
    if expected_checksum and current_checksum != expected_checksum and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File changed on disk. Reload and retry or set force=true.",
        )

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompts config root must be a YAML mapping.",
        )

    editable_entries = {entry["id"]: entry for entry in _extract_prompt_entries(parsed)}
    if not editable_entries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No editable system prompts found in prompts config.",
        )

    for update in prompt_updates:
        prompt_id = update.get("id")
        content = update.get("content")
        if not prompt_id or not isinstance(content, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each prompt update requires id and content.",
            )
        entry = editable_entries.get(prompt_id)
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown or non-editable prompt id: {prompt_id}",
            )
        _path_set(parsed, entry["path"], content)

    new_content = _dump_prompts_config(parsed)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tmp:
        tmp.write(new_content)
        temp_name = tmp.name
    Path(temp_name).replace(path)

    _invalidate_prompt_caches()
    return _response_data(path, new_content, parsed)


def get_device_agent_prompts(
    scene_hint: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Expose DeviceAgent prompts + risk rules through the same service layer
    so callers (DeviceAgent, admin UI, tests) all read the cache-aware path.

    Returns a dict with keys ``system_prompt`` / ``user_prompt_template``
    / ``risk_rules`` / ``scene``. ``locale`` selects the per-language body with
    a default-language fallback. Empty strings / empty list when the yaml
    section is missing or malformed.
    """
    from app.agents.device_agent import prompts as device_agent_prompts

    system_prompt, user_prompt_template = device_agent_prompts.get_prompts(
        scene_hint, locale
    )
    risk_rules = device_agent_prompts.get_risk_rules(scene_hint)
    return {
        "scene": scene_hint or "default",
        "system_prompt": system_prompt,
        "user_prompt_template": user_prompt_template,
        "risk_rules": risk_rules,
    }


def get_chat_title_prompt_template(locale: Optional[str] = None) -> str:
    """Load the chat session-title prompt template for ``locale``.

    The ``template`` may be a flat string (legacy) or a per-language map
    ({locale: body}); the latter is resolved with a default-language (``zh``)
    fallback. Falls back to :data:`DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE` when the
    config is missing or malformed.
    """
    from app.i18n.prompts import select_localized_body

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
        template = select_localized_body(raw_prompt.get("template"), locale)
    elif isinstance(raw_prompt, str):
        template = raw_prompt.strip()
    else:
        template = ""

    if isinstance(template, str) and template.strip():
        return template.strip()
    return DEFAULT_CHAT_TITLE_PROMPT_TEMPLATE
