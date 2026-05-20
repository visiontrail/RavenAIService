"""
Runtime-mutable settings that Admin can override without restarting the service.

仅持久化少量轻量级配置（例如轻量级模型名称）。文件不存在时回退到 app.config.settings。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_MTIME: float = 0.0

_ALLOWED_KEYS = {
    "llm_light_model_name",
    "llm_light_base_url",
    "llm_light_api_key",
    "llm_light_temperature",
}


def _resolve_path() -> Path:
    raw = getattr(settings, "runtime_settings_path", "data/runtime_settings.json")
    if os.path.isabs(raw):
        return Path(raw)
    project_root = Path(__file__).resolve().parents[2]
    return (project_root / raw).resolve()


def _load_unlocked() -> Dict[str, Any]:
    global _CACHE, _CACHE_MTIME
    path = _resolve_path()
    if not path.exists():
        _CACHE = {}
        _CACHE_MTIME = 0.0
        return _CACHE

    try:
        mtime = path.stat().st_mtime
        if _CACHE is not None and mtime == _CACHE_MTIME:
            return _CACHE
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if not isinstance(data, dict):
            data = {}
        _CACHE = data
        _CACHE_MTIME = mtime
        return _CACHE
    except Exception as exc:  # noqa: BLE001
        logger.warning("runtime_settings: 读取失败 %s: %s", path, exc)
        _CACHE = {}
        _CACHE_MTIME = 0.0
        return _CACHE


def _persist_unlocked(values: Dict[str, Any]) -> None:
    global _CACHE, _CACHE_MTIME
    path = _resolve_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), encoding="utf-8"
    ) as tmp:
        json.dump(values, tmp, ensure_ascii=False, indent=2)
        tmp_name = tmp.name
    Path(tmp_name).replace(path)
    _CACHE = values
    _CACHE_MTIME = path.stat().st_mtime


def get_all() -> Dict[str, Any]:
    """Return the merged view of (file overrides) + (settings defaults)."""
    with _LOCK:
        overrides = dict(_load_unlocked())
    merged = {
        "llm_light_model_name": overrides.get("llm_light_model_name")
        or getattr(settings, "llm_light_model_name", None),
        "llm_light_base_url": overrides.get("llm_light_base_url")
        or getattr(settings, "llm_light_base_url", None),
        "llm_light_api_key_set": bool(
            overrides.get("llm_light_api_key")
            or getattr(settings, "llm_light_api_key", None)
        ),
        "llm_light_temperature": overrides.get("llm_light_temperature")
        if overrides.get("llm_light_temperature") is not None
        else getattr(settings, "llm_light_temperature", 0.2),
        "fallback_model_name": getattr(settings, "llm_model_name", ""),
        "fallback_base_url": getattr(settings, "deepseek_base_url", ""),
    }
    return merged


def get_effective_light_config() -> Dict[str, Any]:
    """Return the resolved values used to actually build the light LLM client."""
    with _LOCK:
        overrides = dict(_load_unlocked())
    model = (
        overrides.get("llm_light_model_name")
        or getattr(settings, "llm_light_model_name", None)
        or getattr(settings, "llm_model_name", None)
    )
    base_url = (
        overrides.get("llm_light_base_url")
        or getattr(settings, "llm_light_base_url", None)
        or getattr(settings, "deepseek_base_url", None)
    )
    api_key = (
        overrides.get("llm_light_api_key")
        or getattr(settings, "llm_light_api_key", None)
        or getattr(settings, "deepseek_api_key", None)
    )
    temperature = overrides.get("llm_light_temperature")
    if temperature is None:
        temperature = getattr(settings, "llm_light_temperature", 0.2)
    return {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "temperature": float(temperature),
    }


def update_light_model(
    *,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    clear_api_key: bool = False,
) -> Dict[str, Any]:
    """Update light model overrides. Pass empty string to clear a string field.

    `clear_api_key=True` removes any stored api key override.
    """
    with _LOCK:
        current = dict(_load_unlocked())

        def _apply(key: str, value: Optional[str]) -> None:
            if value is None:
                return
            cleaned = value.strip()
            if cleaned == "":
                current.pop(key, None)
            else:
                current[key] = cleaned

        _apply("llm_light_model_name", model_name)
        _apply("llm_light_base_url", base_url)
        if clear_api_key:
            current.pop("llm_light_api_key", None)
        elif api_key is not None:
            cleaned = api_key.strip()
            if cleaned:
                current["llm_light_api_key"] = cleaned

        if temperature is not None:
            try:
                current["llm_light_temperature"] = float(temperature)
            except (TypeError, ValueError):
                pass

        # Filter to allowed keys only.
        current = {k: v for k, v in current.items() if k in _ALLOWED_KEYS}
        _persist_unlocked(current)
    # Reset light LLM cached client so next call rebuilds.
    try:
        from app.services import light_llm_service

        light_llm_service.reset_cached_client()
    except Exception:  # noqa: BLE001
        pass
    return get_all()
