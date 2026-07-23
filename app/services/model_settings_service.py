"""Runtime-configurable model settings, editable from the Admin console.

Historically every model parameter lived in ``.env`` / ``app/config.py`` and a
service restart was required to change providers, keys or model ids. This
service moves that mechanism behind the Admin "模型设置" page: overrides are
persisted through :mod:`app.services.runtime_settings_service` (a small JSON
store) and win over the ``.env`` bootstrap defaults at runtime — no restart.

The overlay itself lives in :meth:`app.config.Settings.__getattribute__`, which
calls :func:`get_override` for the whitelisted keys. Because every consumer
reads model config via ``settings.<key>`` (``anthropic_client.build_options``,
the per-agent telemetry, ``ocr_service`` …), wiring the overlay once means all
of them transparently pick up Admin changes.

Layered future work (multi-provider cost routing) can build on this store
without touching call sites again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import OVERRIDABLE_MODEL_KEYS, settings
from app.services import runtime_settings_service

logger = logging.getLogger(__name__)


ANTHROPIC_PROVIDERS: Tuple[str, ...] = ("anthropic", "deepseek", "custom")

# Upper bounds mirror the intent of the pydantic fields; keep them generous.
_MAX_TOKENS_MIN = 1
_MAX_TOKENS_MAX = 200_000


@dataclass(frozen=True)
class FieldSpec:
    key: str          # matches the Settings attribute / runtime store key
    kind: str         # "str" | "int" | "bool" | "secret"
    group: str        # "anthropic" | "ocr"
    secret: bool = False


# Canonical, ordered list of the settings that the Admin page may override.
_SPECS: Tuple[FieldSpec, ...] = (
    # ── Primary Anthropic-compatible model ────────────────────────────────
    FieldSpec("anthropic_provider", "str", "anthropic"),
    FieldSpec("anthropic_api_key", "secret", "anthropic", secret=True),
    FieldSpec("anthropic_base_url", "str", "anthropic"),
    FieldSpec("anthropic_model", "str", "anthropic"),
    FieldSpec("anthropic_small_fast_model", "str", "anthropic"),
    FieldSpec("anthropic_max_tokens", "int", "anthropic"),
    # ── OCR / vision model (image input) ──────────────────────────────────
    FieldSpec("ocr_enabled", "bool", "ocr"),
    FieldSpec("ocr_api_key", "secret", "ocr", secret=True),
    FieldSpec("ocr_base_url", "str", "ocr"),
    FieldSpec("ocr_model", "str", "ocr"),
    FieldSpec("ocr_provider", "str", "ocr"),
)

_SPEC_BY_KEY: Dict[str, FieldSpec] = {spec.key: spec for spec in _SPECS}
OVERRIDABLE_KEYS: frozenset = frozenset(_SPEC_BY_KEY)

# Guard against the two key lists drifting apart. ``config`` owns the overlay
# whitelist; this module owns the field metadata — they must describe the same
# set of keys.
assert OVERRIDABLE_KEYS == OVERRIDABLE_MODEL_KEYS, (
    "model_settings_service._SPECS and config.OVERRIDABLE_MODEL_KEYS disagree: "
    f"{sorted(OVERRIDABLE_KEYS ^ OVERRIDABLE_MODEL_KEYS)}"
)

# Let the runtime store accept writes/deletes for our keys.
runtime_settings_service.register_allowed_keys(OVERRIDABLE_KEYS)


# ─────────────────────────── Coercion ──────────────────────────────────────

_TRUE_TOKENS = {"1", "true", "yes", "on"}
_FALSE_TOKENS = {"0", "false", "no", "off", ""}


def _coerce(spec: FieldSpec, raw: Any) -> Any:
    """Coerce a raw (JSON / form) value to the spec's Python type.

    Raises ``ValueError`` on invalid input so callers can surface a 400.
    """
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        token = str(raw).strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
        raise ValueError(f"{spec.key} 必须是布尔值")
    if spec.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{spec.key} 必须是整数") from exc
        return value
    # str / secret — normalise to a trimmed string
    return str(raw).strip()


# ─────────────────────────── Overlay hook ──────────────────────────────────

def get_override(key: str) -> Tuple[bool, Any]:
    """Return ``(found, value)`` for an overridable key.

    ``found`` is ``True`` only when the runtime store explicitly holds the key
    (an empty string counts as an intentional override → "use provider
    default"). Called from :meth:`app.config.Settings.__getattribute__`; it must
    never read ``settings.<overridable_key>`` itself (would recurse).
    """
    spec = _SPEC_BY_KEY.get(key)
    if spec is None:
        return False, None
    store = runtime_settings_service.get_all()
    if key not in store:
        return False, None
    try:
        return True, _coerce(spec, store[key])
    except ValueError:
        # A hand-corrupted store must not break config reads; fall back to env.
        logger.warning("model_settings: 覆盖值非法，回退默认 key=%s", key)
        return False, None


# ─────────────────────────── Read for Admin ────────────────────────────────

def _env_default(key: str) -> Any:
    """Raw ``.env`` / field default, bypassing the runtime overlay."""
    return object.__getattribute__(settings, key)


def _provider_profiles() -> List[Dict[str, Any]]:
    from app.agents.anthropic_client import PROVIDER_PROFILES

    profiles: List[Dict[str, Any]] = []
    for name in ANTHROPIC_PROVIDERS:
        profile = PROVIDER_PROFILES.get(name)
        if profile is None:
            continue
        profiles.append(
            {
                "name": profile.name,
                "default_base_url": profile.default_base_url,
                "default_model": profile.default_model,
                "default_small_fast_model": profile.default_small_fast_model,
                "supports_image_input": profile.supports_image_input,
                "supports_mcp_server_tools": profile.supports_mcp_server_tools,
            }
        )
    return profiles


def describe() -> Dict[str, Any]:
    """Effective values + metadata for rendering the Admin form.

    Secrets never leave the backend: only an ``*_set`` boolean is exposed.
    ``source`` is ``override`` when the runtime store holds the key, ``env``
    when it falls back to the bootstrap default, or ``unset`` for an empty
    secret.
    """
    store = runtime_settings_service.get_all()
    fields: Dict[str, Any] = {}
    for spec in _SPECS:
        overridden = spec.key in store
        effective = getattr(settings, spec.key)  # overlay-resolved
        entry: Dict[str, Any] = {
            "group": spec.group,
            "source": "override" if overridden else "env",
        }
        if spec.secret:
            is_set = bool(effective)
            entry["is_set"] = is_set
            if not is_set:
                entry["source"] = "unset"
        else:
            entry["value"] = effective
            entry["env_default"] = _env_default(spec.key)
        fields[spec.key] = entry

    return {
        "fields": fields,
        "provider_options": list(ANTHROPIC_PROVIDERS),
        "provider_profiles": _provider_profiles(),
    }


# ─────────────────────────── Write for Admin ───────────────────────────────

def _effective_after(updates: Dict[str, Any], key: str) -> Any:
    """Value of ``key`` once ``updates`` is applied over the current effective."""
    if key in updates and updates[key] is not None:
        return updates[key]
    return getattr(settings, key)


def save(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist the provided subset of model settings.

    ``payload`` maps field keys to desired values. A ``None`` value means "leave
    unchanged"; for secrets an empty string is treated the same way (use the
    existing key). Non-secret text fields may be set to an empty string to mean
    "use the provider default". Returns :func:`describe` for the new state.

    Raises ``ValueError`` (→ HTTP 400) on any invalid value.
    """
    unknown = set(payload) - OVERRIDABLE_KEYS
    if unknown:
        raise ValueError(f"未知的模型设置项：{sorted(unknown)}")

    coerced: Dict[str, Any] = {}
    for key, raw in payload.items():
        spec = _SPEC_BY_KEY[key]
        if raw is None:
            continue
        if spec.secret:
            value = str(raw).strip()
            if not value:
                # Empty secret → keep whatever is already effective.
                continue
            coerced[key] = value
        else:
            coerced[key] = _coerce(spec, raw)

    # ── Cross-field validation against the post-save effective state ────────
    provider = _effective_after(coerced, "anthropic_provider")
    if provider not in ANTHROPIC_PROVIDERS:
        raise ValueError(
            f"anthropic_provider 必须是 {list(ANTHROPIC_PROVIDERS)} 之一"
        )

    max_tokens = _effective_after(coerced, "anthropic_max_tokens")
    try:
        max_tokens_int = int(max_tokens)
    except (TypeError, ValueError) as exc:
        raise ValueError("anthropic_max_tokens 必须是整数") from exc
    if not (_MAX_TOKENS_MIN <= max_tokens_int <= _MAX_TOKENS_MAX):
        raise ValueError(
            f"anthropic_max_tokens 必须在 {_MAX_TOKENS_MIN}~{_MAX_TOKENS_MAX} 之间"
        )

    if provider == "custom":
        base_url = str(_effective_after(coerced, "anthropic_base_url") or "").strip()
        model = str(_effective_after(coerced, "anthropic_model") or "").strip()
        if not base_url:
            raise ValueError("provider 为 custom 时必须提供 anthropic_base_url")
        if not model:
            raise ValueError("provider 为 custom 时必须提供 anthropic_model")

    if coerced:
        runtime_settings_service.update(coerced)
    return describe()


def reset() -> Dict[str, Any]:
    """Remove all model overrides, reverting every key to its ``.env`` default."""
    runtime_settings_service.delete_keys(OVERRIDABLE_KEYS)
    return describe()
