"""Request locale resolution helpers.

The active locale is resolved per request in priority order:

1. an explicit locale header sent by the frontend (``X-App-Locale``), or a
   standard ``Accept-Language`` header as a fallback source,
2. the authenticated user's stored ``language`` preference,
3. the system default (:data:`app.i18n.DEFAULT`).

The pure :func:`resolve_locale` function holds the logic so it can be unit
tested without a FastAPI request; the API layer provides the thin dependency
that wires the current user and request headers into it.
"""

from __future__ import annotations

from typing import Any, Optional

from app.i18n import DEFAULT, normalize

# Custom, app-controlled header carrying the user's explicit locale choice.
# Kept distinct from ``Accept-Language`` so an explicit in-app choice is not
# confused with the browser's advertised languages.
LOCALE_HEADER = "X-App-Locale"


def resolve_locale(
    *,
    header_locale: Optional[str] = None,
    accept_language: Optional[str] = None,
    user: Optional[Any] = None,
) -> str:
    """Resolve the active locale from the available signals.

    ``header_locale`` is the explicit app header. ``accept_language`` is the raw
    ``Accept-Language`` header value (only the first tag is considered).
    ``user`` is any object exposing a ``language`` attribute (or ``None``).
    Always returns a supported code; never raises.
    """
    if header_locale:
        return normalize(header_locale)
    if accept_language:
        first_tag = accept_language.split(",", 1)[0].strip()
        if first_tag:
            return normalize(first_tag)
    user_language = getattr(user, "language", None)
    if user_language:
        return normalize(user_language)
    return DEFAULT
