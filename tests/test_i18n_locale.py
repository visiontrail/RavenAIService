"""Unit tests for backend locale primitives and the request-locale resolver."""

from __future__ import annotations

import pytest

from app.i18n import DEFAULT, SUPPORTED, is_supported, normalize
from app.i18n.deps import resolve_locale


class _User:
    def __init__(self, language: str) -> None:
        self.language = language


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("zh", "zh"),
        ("en", "en"),
        ("en-US", "en"),
        ("EN_us", "en"),
        ("zh-CN", "zh"),
        ("zh_TW", "zh"),
        ("  en  ", "en"),
        ("ja", "zh"),  # unsupported -> default
        ("fr-FR", "zh"),
        ("", "zh"),
        (None, "zh"),
        (123, "zh"),  # non-str -> default
    ],
)
def test_normalize_coerces_to_supported(raw, expected) -> None:
    assert normalize(raw) == expected


def test_supported_and_default_are_consistent() -> None:
    assert DEFAULT in SUPPORTED
    assert is_supported("en")
    assert is_supported("zh")
    assert not is_supported("fr")
    assert not is_supported(None)


def test_resolve_locale_header_wins_over_user() -> None:
    # Explicit header takes priority even when it disagrees with the user pref.
    assert resolve_locale(header_locale="zh", user=_User("en")) == "zh"


def test_resolve_locale_accept_language_when_no_explicit_header() -> None:
    assert resolve_locale(accept_language="en-US,en;q=0.9", user=None) == "en"


def test_resolve_locale_falls_back_to_user_preference() -> None:
    assert resolve_locale(user=_User("en")) == "en"


def test_resolve_locale_falls_back_to_default() -> None:
    assert resolve_locale() == "zh"
    assert resolve_locale(user=None) == "zh"


def test_resolve_locale_unsupported_header_coerced_to_default() -> None:
    assert resolve_locale(header_locale="ja", user=_User("en")) == "zh"
