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
