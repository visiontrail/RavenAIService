"""Secret-safe helpers for primary model API-key pools."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, List

MAX_API_KEYS = 64
_KEY_SPLIT_RE = re.compile(r"[,\r\n]+")


def normalize_api_keys(raw: Any, *, field_name: str = "anthropic_api_keys") -> List[str]:
    """Return a trimmed, unique key list or raise a secret-free ``ValueError``.

    Runtime JSON stores native arrays. Accepting JSON/newline/comma text as a
    defensive compatibility path keeps hand-authored environment overrides
    readable without ever echoing a credential in an error.
    """
    if raw is None:
        values: List[Any] = []
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            values = []
        elif text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field_name} 必须是 API Key 数组") from exc
            if not isinstance(decoded, list):
                raise ValueError(f"{field_name} 必须是 API Key 数组")
            values = decoded
        else:
            values = _KEY_SPLIT_RE.split(text)
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        raise ValueError(f"{field_name} 必须是 API Key 数组")

    normalized = [str(value).strip() for value in values if str(value).strip()]
    if len(normalized) > MAX_API_KEYS:
        raise ValueError(f"{field_name} 最多允许 {MAX_API_KEYS} 个 API Key")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} 不能包含重复 API Key")
    return normalized


def key_identifier(api_key: str) -> str:
    """Opaque, non-reversible identifier safe for logs and Admin diagnostics."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"key-{digest[:12]}"
