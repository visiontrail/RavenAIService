"""Owner scope resolution for chat agent runs.

A run's ``owner_scope`` is the key the backend uses to isolate active-run
registry, snapshots, permission brokers, workspaces and sidebar overlay
between users. Two users SHALL never share the same scope; one user across
sessions SHALL share the same scope.

Rules:

- Authenticated user → ``user:<user_id>``.
- Anonymous user → ``anon:<token>``, where ``token`` is either:
  - provided by the client as ``X-Client-Scope`` header (preferred for
    SPA requests like SSE that already set custom headers), OR
  - read from the ``rai_client_scope`` cookie, OR
  - server-generated and pushed back via Set-Cookie so subsequent
    requests from the same browser land in the same scope.

The anonymous mode survives page reloads (cookie persists) but not
browsers / private windows; that matches the design's stated retention
guarantee for anonymous runs (in-process recovery only).
"""

from __future__ import annotations

import secrets
from typing import Any, Optional

from fastapi import Request, Response


CLIENT_SCOPE_COOKIE = "rai_client_scope"
CLIENT_SCOPE_HEADER = "X-Client-Scope"
# Anonymous token TTL — cookie lifetime in seconds. 7 days is enough for
# multi-tab continuity but short enough to bound stale-anon scopes.
_ANON_COOKIE_MAX_AGE = 7 * 24 * 3600


def owner_scope_for_user(user: Any) -> Optional[str]:
    """Return ``user:<id>`` if ``user`` looks like an authenticated user."""
    if user is None:
        return None
    uid = getattr(user, "id", None)
    if not uid:
        return None
    return f"user:{uid}"


def resolve_owner_scope(
    request: Optional[Request],
    response: Optional[Response],
    user: Any,
) -> str:
    """Resolve owner_scope for an HTTP request.

    Authenticated requests are unambiguous (``user:<id>``). Anonymous
    requests prefer the client-supplied ``X-Client-Scope`` header so SPAs
    can pin a scope explicitly; fall back to the cookie; finally generate
    a new token and push it back via ``response.set_cookie`` so the next
    request lands in the same scope.
    """
    scope = owner_scope_for_user(user)
    if scope:
        return scope

    token: Optional[str] = None
    if request is not None:
        header_token = request.headers.get(CLIENT_SCOPE_HEADER)
        if header_token:
            token = header_token.strip() or None
        if not token:
            cookie_token = request.cookies.get(CLIENT_SCOPE_COOKIE)
            if cookie_token:
                token = cookie_token.strip() or None

    if not token:
        token = secrets.token_urlsafe(16)
        if response is not None:
            # ``httponly=False`` so the SPA can read it back if needed for
            # cross-tab coordination; the value is not security-sensitive
            # (it only proves "same browser"), not a session token.
            response.set_cookie(
                CLIENT_SCOPE_COOKIE,
                token,
                max_age=_ANON_COOKIE_MAX_AGE,
                httponly=False,
                samesite="lax",
            )

    return f"anon:{token}"


__all__ = [
    "CLIENT_SCOPE_COOKIE",
    "CLIENT_SCOPE_HEADER",
    "owner_scope_for_user",
    "resolve_owner_scope",
]
