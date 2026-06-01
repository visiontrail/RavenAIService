"""Shared SDK token-usage accumulator used across Agent implementations.

Claude Agent SDK assistant/result messages carry a ``usage`` payload with
input/output and cache token fields. Different SDK versions expose them as
object attributes or plain dicts, and name the cache fields differently
(``cache_read_input_tokens`` vs ``cache_read_tokens`` …). This module is the
single place that maps those shapes onto the four canonical counters consumed
by :mod:`app.services.metrics_service`:

    ``input_tokens`` / ``output_tokens`` / ``cache_read_tokens`` / ``cache_write_tokens``

Accumulation is defensive by design: missing, unknown, non-numeric, or negative
values contribute ``0`` and never raise, so an Agent loop can call it on every
message without guarding.
"""

from __future__ import annotations

from typing import Any, Dict

CANONICAL_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)

# Source attribute / dict key on an SDK ``usage`` payload → canonical field.
_USAGE_SOURCES = {
    "input_tokens": "input_tokens",
    "prompt_tokens": "input_tokens",
    "output_tokens": "output_tokens",
    "completion_tokens": "output_tokens",
    "cache_read_input_tokens": "cache_read_tokens",
    "cache_read_tokens": "cache_read_tokens",
    "cache_creation_input_tokens": "cache_write_tokens",
    "cache_write_tokens": "cache_write_tokens",
}


def new_token_usage() -> Dict[str, int]:
    """Return a fresh zeroed accumulator with the four canonical counters."""
    return {field: 0 for field in CANONICAL_FIELDS}


def _coerce_int(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return count if count > 0 else 0


def accumulate_usage(usage: Any, token_usage: Dict[str, int]) -> None:
    """Add one SDK ``usage`` payload (object or dict) into ``token_usage`` in place.

    Safe to call with ``None`` or an unexpected shape — such calls are no-ops.
    To avoid double-counting when both an alias and the canonical key are
    present (e.g. ``prompt_tokens`` and ``input_tokens``), each canonical field
    is written at most once per call, preferring the first source that is
    actually present on the payload.
    """
    if not usage:
        return
    usage_dict = None
    if isinstance(usage, dict):
        usage_dict = {
            key.strip().lower(): value
            for key, value in usage.items()
            if isinstance(key, str)
        }
    seen: set[str] = set()
    for source_key, canonical in _USAGE_SOURCES.items():
        if canonical in seen:
            continue
        if usage_dict is not None:
            if source_key not in usage_dict:
                continue
            value = usage_dict.get(source_key)
        else:
            if not hasattr(usage, source_key):
                continue
            value = getattr(usage, source_key, None)
        token_usage[canonical] += _coerce_int(value)
        seen.add(canonical)


__all__ = ["CANONICAL_FIELDS", "new_token_usage", "accumulate_usage"]
