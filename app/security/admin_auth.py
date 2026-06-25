"""
Lightweight admin authentication helpers.

The goal is to provide an internal-only login flow without bringing in heavy
dependencies. Credentials are read from a YAML file so that operations can
rotate passwords without code changes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import HTTPException, status

from app.config import settings


ADMIN_TOKEN_HEADER = "Authorization"
ADMIN_TOKEN_PREFIX = "Bearer "


@dataclass
class AdminUser:
    username: str
    password: Optional[str] = None
    password_hash: Optional[str] = None
    disabled: bool = False
    roles: List[str] = None


def _pbkdf2_hash(password: str, iterations: int = 260_000) -> Tuple[str, str]:
    """
    Create a pbkdf2_sha256 hash string for storage.
    Returns (salt, hash_hex).
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return salt, digest.hex()


def build_password_hash(password: str, iterations: int = 260_000) -> str:
    """
    Utility to produce a hash string that can be placed in admin_auth.yaml.
    Format: pbkdf2_sha256$<iterations>$<salt>$<hash_hex>
    """
    salt, digest_hex = _pbkdf2_hash(password, iterations=iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest_hex}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify either a plain password or a pbkdf2_sha256 hash."""
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iter_str, salt, digest_hex = stored.split("$", 3)
            iterations = int(iter_str)
            derived = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                iterations,
            ).hex()
            return hmac.compare_digest(derived, digest_hex)
        except Exception:
            return False
    return hmac.compare_digest(password, stored)


class AdminAuthManager:
    """
    Minimal auth manager that validates credentials from a YAML file and
    issues HMAC-signed bearer tokens.
    """

    def __init__(
        self,
        config_path: str,
        secret_key: str,
        default_ttl_minutes: int = 120,
    ) -> None:
        self._config_path = self._resolve_config_path(config_path)
        self._secret = secret_key.encode("utf-8")
        self._default_ttl_minutes = default_ttl_minutes
        self._config_mtime: Optional[float] = None
        self._users: List[AdminUser] = []
        self._token_ttl_minutes: int = default_ttl_minutes
        self._load_config()

    def _resolve_config_path(self, raw_path: str) -> Path:
        if os.path.isabs(raw_path):
            return Path(raw_path)
        project_root = Path(__file__).resolve().parents[1]  # app/
        return (project_root.parent / raw_path).resolve()

    def _load_config(self) -> None:
        """Load YAML config with admin users."""
        try:
            cfg = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            # No config file present: keep empty user list
            self._config_mtime = None
            self._users = []
            self._token_ttl_minutes = self._default_ttl_minutes
            return
        except Exception as exc:  # pragma: no cover - defensive logging
            raise RuntimeError(f"Failed to read admin auth config: {exc}") from exc

        self._config_mtime = self._config_path.stat().st_mtime
        users_raw = cfg.get("users", []) if isinstance(cfg, dict) else []
        self._token_ttl_minutes = (
            cfg.get("token_ttl_minutes") or self._default_ttl_minutes
            if isinstance(cfg, dict)
            else self._default_ttl_minutes
        )

        users: List[AdminUser] = []
        for item in users_raw:
            if not isinstance(item, dict):
                continue
            user = AdminUser(
                username=str(item.get("username", "")).strip(),
                password=item.get("password"),
                password_hash=item.get("password_hash"),
                disabled=bool(item.get("disabled", False)),
                roles=item.get("roles") or [],
            )
            if user.username:
                users.append(user)
        self._users = users

    def _ensure_loaded(self) -> None:
        """Reload config when file changes on disk."""
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            return
        if self._config_mtime is None or mtime != self._config_mtime:
            self._load_config()

    def _find_user(self, username: str) -> Optional[AdminUser]:
        for u in self._users:
            if u.username == username:
                return u
        return None

    def verify_credentials(self, username: str, password: str) -> Tuple[str, float]:
        """Validate username/password and return (token, expires_at_ts)."""
        self._ensure_loaded()
        user = self._find_user(username)
        if not user or user.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        stored = user.password_hash or user.password
        if not stored or not _verify_password(password, stored):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )
        return self._issue_token(user.username)

    def _issue_token(self, username: str) -> Tuple[str, float]:
        expires_at = int(time.time() + self._token_ttl_minutes * 60)
        payload = f"{username}:{expires_at}:{secrets.token_hex(8)}"
        signature = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).digest()
        token = (
            base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8").rstrip("=")
            + "."
            + base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
        )
        return token, float(expires_at)

    def _parse_token(self, token: str) -> Tuple[str, int]:
        try:
            payload_b64, signature_b64 = token.split(".", 1)
            payload_bytes = base64.urlsafe_b64decode(self._add_padding(payload_b64))
            signature_bytes = base64.urlsafe_b64decode(self._add_padding(signature_b64))
            expected_sig = hmac.new(self._secret, payload_bytes, hashlib.sha256).digest()
            if not hmac.compare_digest(signature_bytes, expected_sig):
                raise ValueError("Invalid signature")
            payload = payload_bytes.decode("utf-8")
            username, exp_str, _nonce = payload.split(":", 2)
            return username, int(exp_str)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

    @staticmethod
    def _add_padding(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return (value + padding).encode("utf-8")

    def validate_token(self, token: str) -> str:
        """Validate the bearer token and return username."""
        username, exp_ts = self._parse_token(token)
        if exp_ts < int(time.time()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Login session expired. Please sign in again.",
            )
        self._ensure_loaded()
        user = self._find_user(username)
        if not user or user.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is not allowed",
            )
        return username

    def token_ttl_minutes(self) -> int:
        return self._token_ttl_minutes

    def list_config_users(self) -> List[AdminUser]:
        """Return admin users from YAML config."""
        self._ensure_loaded()
        return [
            AdminUser(
                username=u.username,
                password=u.password,
                password_hash=u.password_hash,
                disabled=u.disabled,
                roles=list(u.roles or []),
            )
            for u in self._users
        ]


auth_manager = AdminAuthManager(
    config_path=settings.admin_auth_config_path,
    secret_key=settings.secret_key,
    default_ttl_minutes=settings.admin_token_ttl_minutes,
)
