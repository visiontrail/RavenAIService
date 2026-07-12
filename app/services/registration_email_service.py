"""Runtime-configurable email restrictions for self-service registration."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services import runtime_settings_service


DEFAULT_VALIDATION_MESSAGE = "邮箱地址不符合注册要求"
MAX_REGEX_LENGTH = 512
MAX_MESSAGE_LENGTH = 255

# Deliberately small baseline check. The administrator regex provides any
# organization-specific policy, while this prevents plainly malformed values
# from being stored when no custom regex is configured.
_BASIC_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class RegistrationEmailSettings:
    email_regex: str
    email_validation_message: str


def get_settings() -> RegistrationEmailSettings:
    values = runtime_settings_service.get_all()
    email_regex = str(values.get("registration_email_regex") or "")
    message = str(
        values.get("registration_email_validation_message")
        or DEFAULT_VALIDATION_MESSAGE
    )
    return RegistrationEmailSettings(
        email_regex=email_regex,
        email_validation_message=message,
    )


def save_settings(
    *,
    email_regex: str,
    email_validation_message: str,
) -> RegistrationEmailSettings:
    pattern = str(email_regex or "")
    message = str(email_validation_message or "").strip()
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"邮箱正则表达式不能超过 {MAX_REGEX_LENGTH} 个字符")
    if not message:
        raise ValueError("邮箱校验提示不能为空")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"邮箱校验提示不能超过 {MAX_MESSAGE_LENGTH} 个字符")
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"邮箱正则表达式无效：{exc}") from exc

    runtime_settings_service.update(
        {
            "registration_email_regex": pattern,
            "registration_email_validation_message": message,
        }
    )
    return RegistrationEmailSettings(
        email_regex=pattern,
        email_validation_message=message,
    )


def has_basic_email_format(email: str) -> bool:
    return _BASIC_EMAIL_REGEX.fullmatch(email) is not None


def get_policy_validation_error(email: str) -> str | None:
    """Return the configured message when the email fails the custom policy."""
    current = get_settings()
    if not current.email_regex:
        return None
    try:
        matches = re.fullmatch(current.email_regex, email) is not None
    except re.error:
        # Invalid patterns are rejected on write. Treat a manually corrupted
        # settings file as no custom policy so registration remains available.
        return None
    return None if matches else current.email_validation_message
