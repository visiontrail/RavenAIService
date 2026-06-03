"""Backend internationalization (i18n) primitives.

This module is the single source of truth for *which* languages the system
supports on the backend. Anything that needs to validate, coerce, or fall back
on a locale code should go through :func:`normalize` and the constants here so
adding a future language is a localized data change, not a code change.
"""

from __future__ import annotations

from typing import Optional

# Supported locale codes. Order is not significant.
SUPPORTED: tuple[str, ...] = ("zh", "en")

# Default / fallback locale used whenever a requested or stored locale is
# unknown, unsupported, or absent.
DEFAULT: str = "zh"


def normalize(code: Optional[str]) -> str:
    """Coerce an arbitrary locale code to a supported code.

    Accepts loose inputs such as ``"en-US"``, ``"ZH_CN"``, ``"  en  "`` and
    maps them to a supported base code, falling back to :data:`DEFAULT` when the
    primary language tag is neither ``zh`` nor ``en``. Never raises.
    """
    if not code or not isinstance(code, str):
        return DEFAULT
    # Take the primary language subtag (before ``-`` / ``_``), lowercase it.
    primary = code.strip().lower().replace("_", "-").split("-", 1)[0]
    if primary in SUPPORTED:
        return primary
    if primary.startswith("en"):
        return "en"
    if primary.startswith("zh"):
        return "zh"
    return DEFAULT


def is_supported(code: Optional[str]) -> bool:
    """Return True only when ``code`` is exactly a supported locale code."""
    return isinstance(code, str) and code in SUPPORTED
