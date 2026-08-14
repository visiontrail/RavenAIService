"""Tamper-evident confirmation tokens for Configuration Manager builds."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from copy import deepcopy
from typing import Any, Optional

from app.config import settings


TOKEN_FIELD = "confirmation_token"
TOKEN_VERSION = 1
DEFAULT_TTL_SECONDS = 30 * 60


class PackageConfirmationError(ValueError):
    """The confirmed plan is missing, expired, or changed after confirmation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_payload(plan: dict[str, Any]) -> bytes:
    unsigned = deepcopy(plan)
    unsigned.pop(TOKEN_FIELD, None)
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _signature(plan: dict[str, Any]) -> str:
    secret = str(settings.package_confirmation_secret or "").strip()
    if str(settings.environment).casefold() == "production":
        if len(secret.encode("utf-8")) < 32 or hmac.compare_digest(
            secret.encode("utf-8"),
            str(settings.secret_key).encode("utf-8"),
        ):
            raise PackageConfirmationError(
                "misconfigured_secret",
                "生产环境必须配置至少 32 字节且与登录密钥独立的整包确认密钥",
            )
    if not secret:
        secret = str(settings.secret_key)
    return hmac.new(
        secret.encode("utf-8"),
        _canonical_payload(plan),
        hashlib.sha256,
    ).hexdigest()


def sign_confirmed_plan(
    plan: dict[str, Any],
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Return a signed copy whose complete content is bound to the token."""
    if not isinstance(plan, dict) or not plan.get("plan_hash"):
        raise PackageConfirmationError("missing_plan_hash", "确认计划缺少 plan_hash")
    if not plan.get("confirmation_hash"):
        raise PackageConfirmationError(
            "missing_confirmation_hash", "计划尚未完成逐项用户确认"
        )
    issued_at = float(now if now is not None else time.time())
    signed = deepcopy(plan)
    signed.pop(TOKEN_FIELD, None)
    signed["confirmation_token_version"] = TOKEN_VERSION
    signed["confirmation_issued_at"] = issued_at
    signed["confirmation_expires_at"] = issued_at + max(1.0, float(ttl_seconds))
    signed[TOKEN_FIELD] = _signature(signed)
    return signed


def verify_confirmed_plan(
    plan: dict[str, Any],
    *,
    expected_run_id: Optional[str] = None,
    expected_session_id: Optional[str] = None,
    expected_user_id: Optional[str] = None,
    now: Optional[float] = None,
) -> None:
    """Raise when a plan cannot authorize a build/publication right now."""
    if not isinstance(plan, dict):
        raise PackageConfirmationError("missing_plan", "缺少已确认计划")
    token = str(plan.get(TOKEN_FIELD) or "")
    if not token:
        raise PackageConfirmationError("missing_token", "缺少服务端打包确认签名")
    if int(plan.get("confirmation_token_version") or 0) != TOKEN_VERSION:
        raise PackageConfirmationError("unsupported_token", "打包确认签名版本不受支持")
    if not hmac.compare_digest(token, _signature(plan)):
        raise PackageConfirmationError(
            "tampered_plan", "项目、文件映射或其它打包参数在确认后发生变化"
        )
    expires_at = float(plan.get("confirmation_expires_at") or 0)
    current = float(now if now is not None else time.time())
    if expires_at <= current:
        raise PackageConfirmationError("expired", "打包确认已过期，请重新确认")

    checks = (
        ("run_id", expected_run_id),
        ("session_id", expected_session_id),
        ("user_id", expected_user_id),
    )
    for field, expected in checks:
        if expected is None:
            continue
        actual = plan.get(field)
        if str(actual or "") != str(expected):
            raise PackageConfirmationError(
                "scope_mismatch", f"打包确认与当前 {field} 不匹配"
            )


__all__ = [
    "PackageConfirmationError",
    "sign_confirmed_plan",
    "verify_confirmed_plan",
]
