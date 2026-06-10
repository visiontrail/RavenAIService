"""Tests for per-language prompt-body selection (``app.i18n.prompts``) and the
locale-aware agent prompt loaders."""

from __future__ import annotations

import pytest

from app.i18n.prompts import response_language_directive, select_localized_body


# --- response_language_directive --------------------------------------------


def test_response_language_directive_selects_locale():
    zh = response_language_directive("zh")
    en = response_language_directive("en")
    assert "简体中文" in zh
    assert "English" in en
    assert zh != en
    # No surrounding whitespace — callers decide how to join it on.
    assert zh == zh.strip()
    assert en == en.strip()


def test_response_language_directive_normalizes_loose_locale():
    assert response_language_directive("en-US") == response_language_directive("en")
    assert response_language_directive("zh-Hans") == response_language_directive("zh")


@pytest.mark.parametrize("locale", [None, "", "fr", "ja", "klingon"])
def test_response_language_directive_falls_back_to_default_zh(locale):
    assert response_language_directive(locale) == response_language_directive("zh")


# --- select_localized_body --------------------------------------------------


def test_legacy_flat_string_returned_stripped_regardless_of_locale():
    body = "  plain body  "
    assert select_localized_body(body, "en") == "plain body"
    assert select_localized_body(body, "zh") == "plain body"
    assert select_localized_body(body, None) == "plain body"


def test_map_selects_requested_locale():
    body = {"zh": "中文正文", "en": "English body"}
    assert select_localized_body(body, "en") == "English body"
    assert select_localized_body(body, "zh") == "中文正文"


def test_map_normalizes_loose_locale():
    body = {"zh": "中文", "en": "English"}
    assert select_localized_body(body, "en-US") == "English"
    assert select_localized_body(body, "ZH_CN") == "中文"


def test_missing_variant_falls_back_to_default_zh():
    body = {"zh": "中文正文"}  # no en authored yet
    assert select_localized_body(body, "en") == "中文正文"


def test_unknown_locale_falls_back_to_default():
    body = {"zh": "中文", "en": "English"}
    # ``ja`` is unsupported -> normalize() -> zh
    assert select_localized_body(body, "ja") == "中文"


def test_only_non_default_variant_is_last_resort():
    body = {"en": "English only"}  # default zh missing entirely
    assert select_localized_body(body, "zh") == "English only"


@pytest.mark.parametrize("body", [None, {}, 123, [], {"zh": "   "}])
def test_empty_or_unexpected_bodies_return_empty_string(body):
    assert select_localized_body(body, "en") == ""


# --- agent loaders ----------------------------------------------------------


def test_log_analysis_loader_selects_locale_with_fallback():
    from app.agents.log_analysis import prompts as p

    p._PROMPTS_CACHE.clear()
    p._PROMPTS_CACHE.update(
        {
            "claude_agent_log_analysis": {
                "generic": {
                    "system_prompt": {"zh": "中文SYS", "en": "EN SYS"},
                    "user_prompt_template": {"zh": "中文USER"},  # en missing
                }
            }
        }
    )
    try:
        sys_en, user_en = p.get_prompts(locale="en")
        assert sys_en == "EN SYS"
        assert user_en == "中文USER"  # falls back to zh

        sys_zh, user_zh = p.get_prompts(locale="zh")
        assert sys_zh == "中文SYS"
        assert user_zh == "中文USER"
    finally:
        p._PROMPTS_CACHE.clear()


def test_project_expert_loader_handles_legacy_flat_string():
    from app.agents.project_expert import prompts as p

    p._PROMPTS_CACHE.clear()
    p._PROMPTS_CACHE.update(
        {
            "claude_agent_project_expert": {
                "generic": {
                    "system_prompt": "legacy flat system",
                    "user_prompt_template": "legacy flat user",
                }
            }
        }
    )
    try:
        # A flat string is returned unchanged for any locale.
        assert p.get_prompts(locale="en") == ("legacy flat system", "legacy flat user")
        assert p.get_prompts(locale="zh") == ("legacy flat system", "legacy flat user")
    finally:
        p._PROMPTS_CACHE.clear()


def test_device_loader_selects_locale_and_keeps_risk_rules():
    from app.agents.device_agent import prompts as p

    p._PROMPTS_CACHE.clear()
    p._PROMPTS_CACHE.update(
        {
            "claude_agent_device": {
                "default": {
                    "system_prompt": {"zh": "设备中文", "en": "device english"},
                    "user_prompt_template": "{user_message}",
                    "risk_rules": [
                        {"server": "*", "tool": "*delete*", "risk": "destructive"}
                    ],
                }
            }
        }
    )
    try:
        sys_en, user_en = p.get_prompts(locale="en")
        assert sys_en == "device english"
        assert user_en == "{user_message}"

        rules = p.get_risk_rules()
        assert rules == [{"server": "*", "tool": "*delete*", "risk": "destructive"}]
    finally:
        p._PROMPTS_CACHE.clear()


def test_package_search_get_prompts_falls_back_to_zh():
    from app.agents.package_search import prompts as p

    p._PROMPTS_CACHE.clear()
    try:
        sys_en, user_en = p.get_prompts("en")  # only zh authored -> falls back
        sys_zh, user_zh = p.get_prompts("zh")
        assert sys_en == sys_zh
        assert user_en == user_zh
        assert "recommended_package_ids" in sys_zh
        assert "{question}" in user_zh
    finally:
        p._PROMPTS_CACHE.clear()
