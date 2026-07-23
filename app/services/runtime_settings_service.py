"""Runtime-mutable settings persisted to disk for Admin overrides.

Currently only prompt overrides + future small key/value runtime settings
are stored here. Primary/light LLM overrides were removed when the legacy
ChatAgent / ``light_llm_service`` paths were retired in favour of the
unified Anthropic provider (DeviceAgent + ``title_generator_service``).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: Optional[Dict[str, Any]] = None
_CACHE_MTIME: float = 0.0
_CACHE_PATH: Optional[Path] = None

# Only explicitly listed keys may be changed through the Admin runtime API.
# Domain services (e.g. ``model_settings_service``) extend this set at import
# time via :func:`register_allowed_keys` so each domain owns its own key list.
_ALLOWED_KEYS: set[str] = {
    "registration_email_regex",
    "registration_email_validation_message",
    "system_announcement",
}


def register_allowed_keys(keys: Iterable[str]) -> None:
    """Whitelist additional keys for :func:`update` / :func:`delete_keys`.

    Idempotent — safe to call from a domain service's module import so the
    service stays the single source of truth for the keys it owns.
    """
    _ALLOWED_KEYS.update(keys)


def _resolve_path() -> Path:
    raw = getattr(settings, "runtime_settings_path", "data/runtime_settings.json")
    if os.path.isabs(raw):
        return Path(raw)
    project_root = Path(__file__).resolve().parents[2]
    return (project_root / raw).resolve()


def _load_unlocked() -> Dict[str, Any]:
    global _CACHE, _CACHE_MTIME, _CACHE_PATH
    path = _resolve_path()
    if not path.exists():
        _CACHE = {}
        _CACHE_MTIME = 0.0
        _CACHE_PATH = path
        return _CACHE

    try:
        mtime = path.stat().st_mtime
        if _CACHE is not None and path == _CACHE_PATH and mtime == _CACHE_MTIME:
            return _CACHE
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if not isinstance(data, dict):
            data = {}
        _CACHE = data
        _CACHE_MTIME = mtime
        _CACHE_PATH = path
        return _CACHE
    except Exception as exc:  # noqa: BLE001
        logger.warning("runtime_settings: 读取失败 %s: %s", path, exc)
        _CACHE = {}
        _CACHE_MTIME = 0.0
        _CACHE_PATH = path
        return _CACHE


def _persist_unlocked(values: Dict[str, Any]) -> None:
    global _CACHE, _CACHE_MTIME, _CACHE_PATH
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
    _CACHE_PATH = path


def get_all() -> Dict[str, Any]:
    """Return the current persisted overrides (may be empty)."""
    with _LOCK:
        return dict(_load_unlocked())


def update(values: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the allowed runtime setting keys and return the merged values."""
    unsupported = set(values) - _ALLOWED_KEYS
    if unsupported:
        raise ValueError(f"Unsupported runtime settings: {sorted(unsupported)}")
    with _LOCK:
        merged = dict(_load_unlocked())
        merged.update(values)
        _persist_unlocked(merged)
        return dict(merged)


def delete_keys(keys: Iterable[str]) -> Dict[str, Any]:
    """Remove the given keys from the store (revert them to their defaults).

    Only whitelisted keys may be removed; unknown keys are rejected so callers
    cannot silently clear settings they do not own. Missing keys are a no-op.
    Returns the remaining persisted values.
    """
    target = set(keys)
    unsupported = target - _ALLOWED_KEYS
    if unsupported:
        raise ValueError(f"Unsupported runtime settings: {sorted(unsupported)}")
    with _LOCK:
        merged = dict(_load_unlocked())
        removed = [k for k in target if k in merged]
        if not removed:
            return dict(merged)
        for key in removed:
            merged.pop(key, None)
        _persist_unlocked(merged)
        return dict(merged)
