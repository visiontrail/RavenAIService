"""Unit tests for the backend message catalog and the ``t`` helper."""

from __future__ import annotations

import pytest

from app.i18n import DEFAULT, SUPPORTED
from app.i18n.messages import MESSAGES, missing_keys, t


def test_catalog_parity() -> None:
    """Every message id SHALL exist in every supported locale."""
    assert missing_keys() == {}
    # And every supported locale has a catalog entry.
    for code in SUPPORTED:
        assert code in MESSAGES


def test_t_selects_requested_locale() -> None:
    assert t("upload.no_file_selected", "zh") == "没有选择文件"
    assert t("upload.no_file_selected", "en") == "No file selected"


def test_t_normalizes_loose_locale() -> None:
    # "en-US" should resolve to the "en" variant, not fall back to zh.
    assert t("upload.file_empty", "en-US") == "File cannot be empty"


def test_t_falls_back_to_default_locale() -> None:
    # Unsupported locale -> normalized to DEFAULT (zh).
    assert t("upload.file_empty", "ja") == MESSAGES[DEFAULT]["upload.file_empty"]
    # None locale -> default.
    assert t("upload.file_empty", None) == MESSAGES[DEFAULT]["upload.file_empty"]


def test_t_unknown_key_returns_key() -> None:
    assert t("does.not.exist", "en") == "does.not.exist"


def test_t_applies_format_args() -> None:
    msg = t("upload.unsupported_type", "en", file_type=".txt", supported=".zip")
    assert ".txt" in msg and ".zip" in msg


def test_t_bad_format_args_degrade_to_template() -> None:
    # Missing a referenced placeholder must not raise; return the raw template.
    msg = t("upload.unsupported_type", "en")
    assert msg == MESSAGES["en"]["upload.unsupported_type"]
