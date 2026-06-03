"""Tests for prompt-config display metadata."""

from __future__ import annotations


def test_extract_prompt_entries_uses_project_expert_display_names():
    from app.services.prompts_config_service import _extract_prompt_entries

    entries = _extract_prompt_entries(
        {
            "claude_agent_project_expert": {
                "generic": {
                    "system_prompt": "project expert system",
                    "user_prompt_template": "ignored by admin editor",
                }
            }
        }
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry["function_key"] == "claude_agent_project_expert"
    assert entry["function_name"] == "项目专家"
    assert entry["agent_key"] == "generic"
    assert entry["agent_name"] == "通用项目专家 Agent"
    assert entry["prompt_label"] == "系统提示词"
    # Legacy flat string -> single entry with no locale dimension.
    assert entry["locale"] is None


def test_extract_prompt_entries_splits_per_language_bodies():
    from app.services.prompts_config_service import _extract_prompt_entries

    entries = _extract_prompt_entries(
        {
            "claude_agent_project_expert": {
                "generic": {
                    "system_prompt": {"zh": "中文系统", "en": "English system"},
                }
            }
        }
    )

    by_locale = {e["locale"]: e for e in entries}
    assert set(by_locale) == {"zh", "en"}
    assert by_locale["zh"]["id"] == "claude_agent_project_expert.generic.system_prompt.zh"
    assert by_locale["zh"]["path"] == [
        "claude_agent_project_expert",
        "generic",
        "system_prompt",
        "zh",
    ]
    assert by_locale["zh"]["content"] == "中文系统"
    assert by_locale["en"]["content"] == "English system"
    assert by_locale["en"]["prompt_label"] == "系统提示词 (en)"


def test_path_set_can_author_new_language_variant():
    from app.services.prompts_config_service import _path_set

    root = {"a": {"b": {"system_prompt": {"zh": "中文"}}}}
    # Editing one language leaves the other untouched, and a brand-new variant
    # can be added under the existing per-language map.
    _path_set(root, ["a", "b", "system_prompt", "zh"], "中文-改")
    _path_set(root, ["a", "b", "system_prompt", "en"], "English-new")
    assert root["a"]["b"]["system_prompt"] == {"zh": "中文-改", "en": "English-new"}
