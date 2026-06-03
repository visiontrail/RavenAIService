"""Unit tests for the Bug Fix Coding Agent (task 5.5).

Covers output-JSON extraction, merge_requests normalization, token redaction,
provider/API-base inference, and the system-prompt contract guarantees.
"""

from __future__ import annotations

from app.agents.bug_fix import agent as bf_agent
from app.agents.bug_fix import git_tools
from app.agents.bug_fix import prompts


# ───────────────────── output JSON extraction ──────────────────────

def test_extract_final_json_from_fenced_block():
    text = (
        "Here is the result.\n"
        "```json\n"
        '{"status": "succeeded", "merge_requests": [{"branch_name": "b"}]}\n'
        "```\n"
    )
    parsed = bf_agent._extract_final_json(text)
    assert parsed["status"] == "succeeded"
    assert parsed["merge_requests"][0]["branch_name"] == "b"


def test_extract_final_json_takes_last_block():
    text = (
        "```json\n{\"status\": \"failed\", \"merge_requests\": []}\n```\n"
        "more text\n"
        "```json\n{\"status\": \"succeeded\", \"merge_requests\": [{\"branch_name\": \"x\"}]}\n```"
    )
    parsed = bf_agent._extract_final_json(text)
    assert parsed["status"] == "succeeded"


def test_extract_final_json_bare_object_fallback():
    text = 'prefix {"status": "succeeded", "merge_requests": []} suffix'
    parsed = bf_agent._extract_final_json(text)
    assert parsed["status"] == "succeeded"


def test_extract_final_json_returns_none_on_garbage():
    assert bf_agent._extract_final_json("no json here") is None


# ──────────────────── merge_requests normalization ─────────────────

def test_normalize_drops_items_without_branch():
    out = bf_agent._normalize_merge_requests(
        [{"title": "no branch"}, {"branch_name": "good"}]
    )
    assert len(out) == 1
    assert out[0]["branch_name"] == "good"


def test_normalize_redacts_tokens_in_url_and_description():
    out = bf_agent._normalize_merge_requests(
        [
            {
                "branch_name": "b",
                "mr_url": "https://oauth2:secret@host/foo/-/merge_requests/1",
                "description": "see https://oauth2:secret@host/foo.git",
            }
        ]
    )
    assert "secret" not in out[0]["mr_url"]
    assert "https://***@host" in out[0]["mr_url"]
    assert "secret" not in out[0]["description"]


def test_normalize_handles_non_list():
    assert bf_agent._normalize_merge_requests(None) == []


# ───────────────────────── provider inference ──────────────────────

def test_infer_provider_gitlab(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "bug_fix_git_provider", None)
    assert git_tools.infer_provider("https://gitlab.example.com/a/b.git") == "gitlab"


def test_infer_provider_github(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "bug_fix_git_provider", None)
    assert git_tools.infer_provider("https://github.com/a/b.git") == "github"


def test_infer_provider_config_override(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "bug_fix_git_provider", "gitlab")
    assert git_tools.infer_provider("https://unknown.host/a/b.git") == "gitlab"


def test_infer_api_base_gitlab(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "bug_fix_git_api_base", None)
    base = git_tools.infer_api_base("https://gitlab.example.com/a/b.git", "gitlab")
    assert base == "https://gitlab.example.com/api/v4"


def test_infer_api_base_github_dotcom(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "bug_fix_git_api_base", None)
    base = git_tools.infer_api_base("https://github.com/a/b.git", "github")
    assert base == "https://api.github.com"


def test_gitlab_project_path_strips_git_suffix():
    assert git_tools._gitlab_project_path("https://h/group/proj.git") == "group/proj"


# ─────────────────────── system prompt contract ────────────────────

def test_system_prompt_enforces_minimal_change_and_no_default_branch():
    system, _ = prompts.get_prompts()
    assert "最小改动" in system
    assert "默认分支" in system
    # multi-MR split guidance
    assert "merge_requests" in system
    # never auto-merge
    assert "合并" in system


def test_allowed_tools_include_write_capable_tools():
    for tool in ("Edit", "Write", "Bash", "Read", "Grep", "Glob"):
        assert tool in bf_agent.ALLOWED_TOOLS


def test_result_helper_redacts_error_tokens():
    res = bf_agent._result(
        status="failed",
        merge_requests=[],
        error="clone failed for https://oauth2:secret@host/x.git",
    )
    assert "secret" not in res["error"]
