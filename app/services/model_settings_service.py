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
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import OVERRIDABLE_MODEL_KEYS, settings
from app.services import runtime_settings_service

logger = logging.getLogger(__name__)


# Selectable providers, in Admin dropdown order. Mirrors
# ``anthropic_client.PROVIDER_PROFILES``; a test asserts the two stay in sync.
ANTHROPIC_PROVIDERS: Tuple[str, ...] = (
    "anthropic",
    "deepseek",
    "aliyun",
    "zhipu",
    "moonshot",
    "minimax",
    "stepfun",
    "mimo",
    "hunyuan",
    "yinhe",
    "custom",
)

# Upper bounds mirror the intent of the pydantic fields; keep them generous.
_MAX_TOKENS_MIN = 1
_MAX_TOKENS_MAX = 200_000

# Some provider defaults ship a placeholder that only the deployer can fill in
# (e.g. 阿里云百炼's ``https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/…``).
# Saving one verbatim would point every agent at a non-existent host, so reject
# it at save time rather than at the first chat turn.
_URL_PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")

# Connectivity probes must fail fast — the agent-facing
# ``anthropic_request_timeout_seconds`` (1h) would hang the Admin page.
_TEST_TIMEOUT_SECONDS = 30
# Generous enough that a thinking-by-default model still produces a reply.
_TEST_MAX_TOKENS = 256
_TEST_PROMPT = "ping"


@dataclass(frozen=True)
class FieldSpec:
    key: str          # matches the Settings attribute / runtime store key
    kind: str         # "str" | "int" | "bool" | "secret"
    group: str        # "anthropic" | "anthropic_backup" | "ocr"
    secret: bool = False


@dataclass(frozen=True)
class AnthropicSlot:
    """One Anthropic-compatible endpoint's key names.

    Primary and backup are structurally identical — same provider catalogue,
    same validation rules, same connectivity probe — and differ only in which
    Settings keys hold the values. Describing that difference as data keeps
    :func:`save` and :func:`_test_anthropic` single-implementation; adding a
    third endpoint later is one more entry here plus its ``_SPECS`` rows.

    Deliberately NOT a string-prefix scheme: ``anthropic_backup_model`` also
    starts with ``anthropic_``, so ``startswith`` matching would misclassify
    every backup key as primary.
    """

    name: str                 # "primary" | "backup" — the router's slot id
    group: str                # FieldSpec.group, and the probe ``target`` value
    provider_key: str
    api_key_key: str
    base_url_key: str
    model_key: str
    small_fast_model_key: str
    # ``None`` means "always on" (the primary cannot be disabled).
    enabled_key: Optional[str] = None

    def is_enabled(self, resolve: "Any" = None) -> bool:
        read = resolve or (lambda key: getattr(settings, key))
        return True if self.enabled_key is None else bool(read(self.enabled_key))


PRIMARY_SLOT = AnthropicSlot(
    name="primary",
    group="anthropic",
    provider_key="anthropic_provider",
    api_key_key="anthropic_api_key",
    base_url_key="anthropic_base_url",
    model_key="anthropic_model",
    small_fast_model_key="anthropic_small_fast_model",
)

BACKUP_SLOT = AnthropicSlot(
    name="backup",
    group="anthropic_backup",
    provider_key="anthropic_backup_provider",
    api_key_key="anthropic_backup_api_key",
    base_url_key="anthropic_backup_base_url",
    model_key="anthropic_backup_model",
    small_fast_model_key="anthropic_backup_small_fast_model",
    enabled_key="anthropic_backup_enabled",
)

ANTHROPIC_SLOTS: Tuple[AnthropicSlot, ...] = (PRIMARY_SLOT, BACKUP_SLOT)
SLOT_BY_GROUP: Dict[str, AnthropicSlot] = {slot.group: slot for slot in ANTHROPIC_SLOTS}
SLOT_BY_NAME: Dict[str, AnthropicSlot] = {slot.name: slot for slot in ANTHROPIC_SLOTS}


# Canonical, ordered list of the settings that the Admin page may override.
_SPECS: Tuple[FieldSpec, ...] = (
    # ── Primary Anthropic-compatible model ────────────────────────────────
    FieldSpec("anthropic_provider", "str", "anthropic"),
    FieldSpec("anthropic_api_key", "secret", "anthropic", secret=True),
    FieldSpec("anthropic_base_url", "str", "anthropic"),
    FieldSpec("anthropic_model", "str", "anthropic"),
    FieldSpec("anthropic_small_fast_model", "str", "anthropic"),
    FieldSpec("anthropic_max_tokens", "int", "anthropic"),
    # ── Backup Anthropic-compatible model (failover target) ───────────────
    # anthropic_max_tokens is intentionally NOT duplicated: token budget is a
    # workload property, not an endpoint property, so both slots share it.
    FieldSpec("anthropic_backup_enabled", "bool", "anthropic_backup"),
    FieldSpec("anthropic_backup_provider", "str", "anthropic_backup"),
    FieldSpec("anthropic_backup_api_key", "secret", "anthropic_backup", secret=True),
    FieldSpec("anthropic_backup_base_url", "str", "anthropic_backup"),
    FieldSpec("anthropic_backup_model", "str", "anthropic_backup"),
    FieldSpec("anthropic_backup_small_fast_model", "str", "anthropic_backup"),
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
                "label": profile.label or profile.name,
                "default_base_url": profile.default_base_url,
                "default_model": profile.default_model,
                "default_small_fast_model": profile.default_small_fast_model,
                "models": list(profile.models),
                "supports_image_input": profile.supports_image_input,
                "supports_mcp_server_tools": profile.supports_mcp_server_tools,
                "notes": profile.notes,
                # Tells the form the endpoint template still needs a deployer
                # value (workspace id, tenant, …) before it can be saved.
                "base_url_needs_input": bool(
                    _URL_PLACEHOLDER_RE.search(profile.default_base_url or "")
                ),
            }
        )
    return profiles


def _profile(provider: str) -> Any:
    from app.agents.anthropic_client import PROVIDER_PROFILES

    return PROVIDER_PROFILES.get(provider)


def _resolve_base_url(provider: str, base_url: str) -> str:
    """Mirror ``build_options``: explicit value wins, else the profile default."""
    if base_url:
        return base_url
    profile = _profile(provider)
    return (getattr(profile, "default_base_url", "") or "") if profile else ""


def _resolve_model(provider: str, model: str) -> str:
    """Mirror ``build_options``: explicit value wins, else the profile default."""
    if model:
        return model
    profile = _profile(provider)
    return (getattr(profile, "default_model", "") or "") if profile else ""


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
        # Live routing state. Surfacing it here is the cost guardrail: a primary
        # that stays degraded routes 100% of traffic to the paid backup, and
        # without this the only symptom is the bill.
        "router": _router_snapshot(),
    }


def _router_snapshot() -> Dict[str, Any]:
    """Routing health for the Admin page; never breaks the settings read."""
    try:
        from app.services import model_router

        return model_router.health_snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("model_settings: router snapshot unavailable: %s", exc)
        return {}


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
    for slot in ANTHROPIC_SLOTS:
        _validate_slot(slot, coerced)

    max_tokens = _effective_after(coerced, "anthropic_max_tokens")
    try:
        max_tokens_int = int(max_tokens)
    except (TypeError, ValueError) as exc:
        raise ValueError("anthropic_max_tokens 必须是整数") from exc
    if not (_MAX_TOKENS_MIN <= max_tokens_int <= _MAX_TOKENS_MAX):
        raise ValueError(
            f"anthropic_max_tokens 必须在 {_MAX_TOKENS_MIN}~{_MAX_TOKENS_MAX} 之间"
        )

    if coerced:
        runtime_settings_service.update(coerced)
    return describe()


def _validate_slot(slot: AnthropicSlot, coerced: Dict[str, Any]) -> None:
    """Cross-field checks for one endpoint slot, post-save effective state.

    A **disabled** backup is only checked for a well-formed provider — an admin
    must be able to park a half-filled backup config without the form rejecting
    it. Everything else is enforced only once the slot can actually serve
    traffic, which for the primary is always.
    """
    enabled = slot.is_enabled(lambda key: _effective_after(coerced, key))
    provider = str(_effective_after(coerced, slot.provider_key) or "").strip()

    if not provider:
        if enabled:
            raise ValueError(f"{slot.provider_key} 启用后不能为空")
        return
    if provider not in ANTHROPIC_PROVIDERS:
        raise ValueError(
            f"{slot.provider_key} 必须是 {list(ANTHROPIC_PROVIDERS)} 之一"
        )
    if not enabled:
        return

    base_url = str(_effective_after(coerced, slot.base_url_key) or "").strip()
    model = str(_effective_after(coerced, slot.model_key) or "").strip()

    if provider == "custom":
        if not base_url:
            raise ValueError(f"provider 为 custom 时必须提供 {slot.base_url_key}")
        if not model:
            raise ValueError(f"provider 为 custom 时必须提供 {slot.model_key}")

    # A template default (e.g. 百炼的 {WorkspaceId}) must be filled in first.
    # Check the *resolved* URL: an empty field falls back to the provider
    # default at call time, so a bare placeholder default is equally broken.
    placeholder = _URL_PLACEHOLDER_RE.search(_resolve_base_url(provider, base_url))
    if placeholder:
        raise ValueError(
            f"{slot.base_url_key} 仍包含占位符 {placeholder.group(0)}，"
            "请替换为实际值后再保存"
        )


def reset() -> Dict[str, Any]:
    """Remove all model overrides, reverting every key to its ``.env`` default."""
    runtime_settings_service.delete_keys(OVERRIDABLE_KEYS)
    return describe()


# ─────────────────────────── Connectivity test ─────────────────────────────
#
# "保存后能不能真的用" is not answerable from validation alone: the key may be
# wrong, the model id may not exist on that gateway, the workspace id may be
# unfilled, or the endpoint may be unreachable from this host. The Admin form's
# 测试 buttons send the *form's current* values here (falling back to the saved
# effective config for anything omitted — notably the API key, which the form
# never holds unless it is being rotated), so a config can be verified before it
# is saved.


def _excerpt(value: Any, limit: int = 400) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _fail(target: str, error_kind: str, detail: str, **extra: Any) -> Dict[str, Any]:
    result = {"ok": False, "target": target, "error_kind": error_kind, "detail": detail}
    result.update(extra)
    return result


def _pick(payload: Dict[str, Any], key: str) -> str:
    """Trimmed override from the request body, or '' when absent/blank."""
    return str(payload.get(key) or "").strip()


def _field(payload: Dict[str, Any], key: str, saved: str) -> str:
    """Resolve one non-secret field the way :func:`save` would.

    A field the client *sent* wins even when blank — blank means "fall back to
    the provider default", exactly what saving an empty string does. Only a
    field the client omitted resolves to the currently saved value.
    """
    if key in payload:
        return str(payload[key] or "").strip()
    return saved


async def _probe(
    *,
    target: str,
    url: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    context: Dict[str, Any],
    parse_reply,
) -> Dict[str, Any]:
    """POST a minimal completion request and classify the outcome.

    Never raises and never echoes the API key — only the upstream status and a
    trimmed body excerpt, which is what makes a failure actionable.
    """
    import httpx

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return _fail(
            target,
            "timeout",
            f"请求超时（{_TEST_TIMEOUT_SECONDS}s）：端点不可达或响应过慢",
            **context,
        )
    except httpx.HTTPError as exc:
        return _fail(
            target,
            "network_error",
            f"网络错误：{_excerpt(type(exc).__name__ + ': ' + str(exc), 200)}",
            **context,
        )

    latency_ms = int((time.monotonic() - start) * 1000)
    if response.status_code >= 400:
        return _fail(
            target,
            f"http_{response.status_code}",
            f"上游返回 HTTP {response.status_code}：{_excerpt(response.text)}",
            status_code=response.status_code,
            latency_ms=latency_ms,
            **context,
        )

    try:
        data = response.json()
    except ValueError:
        return _fail(
            target,
            "bad_response",
            f"上游返回了非 JSON 响应：{_excerpt(response.text, 200)}",
            status_code=response.status_code,
            latency_ms=latency_ms,
            **context,
        )

    return {
        "ok": True,
        "target": target,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "reply": _excerpt(parse_reply(data), 200),
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
        **context,
    }


def _anthropic_reply_text(data: Dict[str, Any]) -> str:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        return ""
    return " ".join(
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _openai_reply_text(data: Dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


async def _test_anthropic(slot: AnthropicSlot, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Probe one endpoint slot with the form's values (saved config fills gaps)."""
    target = slot.group
    saved = lambda key: str(getattr(settings, key) or "").strip()  # noqa: E731

    provider = _pick(payload, "provider") or saved(slot.provider_key)
    if not provider:
        return _fail(target, "missing_provider", "尚未选择 provider")
    if provider not in ANTHROPIC_PROVIDERS:
        return _fail(
            target,
            "invalid_provider",
            f"{slot.provider_key} 必须是 {list(ANTHROPIC_PROVIDERS)} 之一",
        )

    base_url = _resolve_base_url(
        provider, _field(payload, "base_url", saved(slot.base_url_key))
    )
    model = _resolve_model(provider, _field(payload, "model", saved(slot.model_key)))
    # Secrets follow save()'s rule instead: blank keeps the stored key.
    api_key = _pick(payload, "api_key") or saved(slot.api_key_key)
    context = {"provider": provider, "base_url": base_url, "model": model}

    if not api_key:
        return _fail(target, "missing_api_key", "尚未配置 API Key", **context)
    if not base_url:
        return _fail(target, "missing_base_url", "Base URL 为空", **context)
    if not model:
        return _fail(target, "missing_model", "模型 id 为空", **context)
    placeholder = _URL_PLACEHOLDER_RE.search(base_url)
    if placeholder:
        return _fail(
            target,
            "placeholder_base_url",
            f"Base URL 仍包含占位符 {placeholder.group(0)}，请替换为实际值",
            **context,
        )

    return await _probe(
        target=target,
        url=f"{base_url.rstrip('/')}/v1/messages",
        # Mirror what the Claude Agent SDK sends (ANTHROPIC_API_KEY → x-api-key),
        # so a green test means the agent path itself will authenticate.
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        body={
            "model": model,
            "max_tokens": _TEST_MAX_TOKENS,
            "messages": [{"role": "user", "content": _TEST_PROMPT}],
        },
        context=context,
        parse_reply=_anthropic_reply_text,
    )


async def _test_ocr(payload: Dict[str, Any]) -> Dict[str, Any]:
    # OCR has no provider profile to fall back to, so a blank field is simply
    # unconfigured and reported as such below.
    base_url = _field(payload, "base_url", str(settings.ocr_base_url or "").strip())
    model = _field(payload, "model", str(settings.ocr_model or "").strip())
    api_key = _pick(payload, "api_key") or str(settings.ocr_api_key or "").strip()
    context = {"base_url": base_url, "model": model}

    if not api_key:
        return _fail("ocr", "missing_api_key", "尚未配置 OCR API Key", **context)
    if not base_url:
        return _fail("ocr", "missing_base_url", "OCR Base URL 为空", **context)
    if not model:
        return _fail("ocr", "missing_model", "OCR 模型 id 为空", **context)

    # A text-only ping: it exercises the same endpoint/key/model triple as
    # ``ocr_service.extract_text`` without shipping an image to the upstream.
    return await _probe(
        target="ocr",
        url=f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body={
            "model": model,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": _TEST_PROMPT}],
        },
        context=context,
        parse_reply=_openai_reply_text,
    )


async def test_connection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Probe one configured endpoint; returns a result dict, never raises.

    ``payload['target']`` selects ``anthropic`` (the primary agent chain),
    ``anthropic_backup`` (the failover endpoint) or ``ocr``; the remaining keys
    (``provider`` / ``base_url`` / ``model`` / ``api_key``) are optional
    overrides for values not yet saved.
    """
    target = (str(payload.get("target") or "anthropic")).strip().lower()
    slot = SLOT_BY_GROUP.get(target)
    if slot is not None:
        return await _test_anthropic(slot, payload)
    if target == "ocr":
        return await _test_ocr(payload)
    raise ValueError("target 必须是 'anthropic' 或 'ocr'")
