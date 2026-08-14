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


def test_extract_prompt_entries_uses_package_search_display_names():
    from app.services.prompts_config_service import _extract_prompt_entries

    entries = _extract_prompt_entries(
        {
            "claude_agent_package_search": {
                "generic": {
                    "system_prompt": {"zh": "包检索系统提示词"},
                }
            }
        }
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry["function_key"] == "claude_agent_package_search"
    assert entry["function_name"] == "配置管理员"
    assert entry["agent_key"] == "generic"
    assert entry["agent_name"] == "配置管理员"
    assert entry["prompt_label"] == "系统提示词 (zh)"
    assert entry["locale"] == "zh"


def test_admin_prompt_entries_include_package_search_block():
    """The shipped prompts_config.yaml exposes the package-search block to AdminPrompts."""
    from app.services.prompts_config_service import load_prompts_config

    data = load_prompts_config()
    function_keys = {e["function_key"] for e in data["prompts"]}
    assert "claude_agent_package_search" in function_keys


def test_admin_prompt_entries_include_localized_general_agent_block():
    """GeneralAgent is editable in AdminPrompts through the shared YAML config."""
    from app.services.prompts_config_service import load_prompts_config

    data = load_prompts_config()
    general_entries = [
        entry
        for entry in data["prompts"]
        if entry["function_key"] == "claude_agent_general"
    ]

    assert {entry["locale"] for entry in general_entries} == {"zh", "en"}
    assert all(entry["function_name"] == "通用助手" for entry in general_entries)
    assert all(entry["agent_name"] == "通用路由 Agent" for entry in general_entries)


def test_invalidate_prompt_caches_clears_general_agent_cache():
    from app.agents.general_agent import prompts as general_prompts
    from app.services.prompts_config_service import _invalidate_prompt_caches

    general_prompts.reset_cache()
    system_prompt, user_prompt_template = general_prompts.get_prompts("en")
    assert "Raven AI" in system_prompt
    assert "{user_message}" in user_prompt_template
    assert general_prompts._PROMPTS_CACHE

    _invalidate_prompt_caches()
    assert not general_prompts._PROMPTS_CACHE


def test_invalidate_prompt_caches_clears_package_search_cache():
    """Saving prompts in the admin panel must take effect on the next run."""
    from app.agents.package_search import prompts as pkg_prompts
    from app.services.prompts_config_service import _invalidate_prompt_caches

    pkg_prompts._PROMPTS_CACHE.clear()
    pkg_prompts.get_prompts("zh")  # populate the cache from the real config
    assert pkg_prompts._PROMPTS_CACHE

    _invalidate_prompt_caches()
    assert not pkg_prompts._PROMPTS_CACHE

    # Next load re-reads the file — simulated here by priming a fake body.
    pkg_prompts._PROMPTS_CACHE.update(
        {
            "claude_agent_package_search": {
                "generic": {
                    "system_prompt": {"zh": "新版系统提示词"},
                    "user_prompt_template": {"zh": "新版模板 {question}"},
                }
            }
        }
    )
    try:
        system_prompt, user_prompt_template = pkg_prompts.get_prompts("zh")
        assert system_prompt == "新版系统提示词"
        assert user_prompt_template == "新版模板 {question}"
    finally:
        pkg_prompts._PROMPTS_CACHE.clear()
