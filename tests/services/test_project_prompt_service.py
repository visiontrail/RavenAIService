"""Tests for app/services/project_prompt_service.py.

Project-level system prompts are the second tier of the layered prompting model
(Agent-level base prompt from prompts_config.yaml + project-level addendum here),
mirroring the agent/project skill tiers.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def isolated_prompts_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(
        settings, "project_prompts_data_dir", str(tmp_path / "project_prompts")
    )
    return tmp_path


def test_get_unset_returns_empty(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    data = svc.get_project_prompt("myproj")
    assert data["exists"] is False
    assert data["content"] == ""
    assert data["project_code"] == "myproj"
    assert data["updated_at"] is None
    assert svc.get_project_prompt_text("myproj") == ""
    assert svc.build_project_prompt_addendum("myproj") == ""


def test_set_and_get_normalizes_code(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    saved = svc.set_project_prompt("MyProj", "只关注鉴权模块的日志。")
    assert saved["exists"] is True
    assert saved["project_code"] == "myproj"  # normalized to lower-case
    assert saved["content"] == "只关注鉴权模块的日志。"
    assert saved["updated_at"] is not None

    # Reading by a differently-cased code resolves to the same store.
    again = svc.get_project_prompt("MYPROJ")
    assert again["content"] == "只关注鉴权模块的日志。"
    assert svc.get_project_prompt_text("myproj") == "只关注鉴权模块的日志。"


def test_addendum_includes_content_and_label(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "RULE: never propose code fixes.")

    addendum = svc.build_project_prompt_addendum("myproj", project_name="My Project")
    assert "RULE: never propose code fixes." in addendum
    assert "My Project" in addendum

    # Falls back to the project_code as the label when no name is given.
    addendum2 = svc.build_project_prompt_addendum("myproj")
    assert "myproj" in addendum2
    assert "RULE: never propose code fixes." in addendum2


def test_empty_content_clears(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "something")
    assert svc.get_project_prompt("myproj")["exists"] is True

    cleared = svc.set_project_prompt("myproj", "   ")
    assert cleared["exists"] is False
    assert cleared["content"] == ""
    assert svc.build_project_prompt_addendum("myproj") == ""


def test_delete(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "something")
    svc.delete_project_prompt("myproj")
    assert svc.get_project_prompt("myproj")["exists"] is False


def test_oversized_rejected(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    big = "x" * (svc.MAX_PROJECT_PROMPT_CHARS + 1)
    with pytest.raises(svc.ProjectPromptValidationError):
        svc.set_project_prompt("myproj", big)


def test_empty_project_code_rejected(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    with pytest.raises(svc.ProjectPromptValidationError):
        svc.get_project_prompt("  ")
    # The convenience text/addendum helpers never raise on bad/empty input.
    assert svc.get_project_prompt_text("") == ""
    assert svc.get_project_prompt_text(None) == ""
    assert svc.build_project_prompt_addendum(None) == ""


# ─────────────────── Agent-scoped layer (code workflow) ────────────────────


def test_agent_scoped_layers_are_isolated(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "EXPERT-ONLY", agent_key="project_expert")

    # Stored under the agent's own layer; other layers stay empty.
    assert svc.get_project_prompt_text("myproj", "project_expert") == "EXPERT-ONLY"
    assert svc.get_project_prompt_text("myproj", "log_analysis") == ""
    assert svc.get_project_prompt_text("myproj", None) == ""
    assert svc.get_project_prompt("myproj", "project_expert")["agent_key"] == "project_expert"


def test_invalid_agent_key_rejected(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    with pytest.raises(svc.ProjectPromptValidationError):
        svc.get_project_prompt("myproj", "bogus_agent")
    # The convenience helpers swallow the bad key rather than raising.
    assert svc.get_project_prompt_text("myproj", "bogus_agent") == ""


def test_addendum_merges_agent_and_shared_layers(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "SHARED-RULE")
    svc.set_project_prompt("myproj", "EXPERT-WORKFLOW", agent_key="project_expert")

    expert = svc.build_project_prompt_addendum("myproj", "project_expert")
    assert "EXPERT-WORKFLOW" in expert
    assert "SHARED-RULE" in expert

    # A different agent only sees the shared layer (no expert workflow).
    log = svc.build_project_prompt_addendum("myproj", "log_analysis")
    assert "EXPERT-WORKFLOW" not in log
    assert "SHARED-RULE" in log

    # No agent_key -> shared layer only (backward-compatible behavior).
    shared_only = svc.build_project_prompt_addendum("myproj")
    assert "EXPERT-WORKFLOW" not in shared_only
    assert "SHARED-RULE" in shared_only


def test_addendum_agent_layer_without_shared(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    svc.set_project_prompt("myproj", "ONLY-WORKFLOW", agent_key="log_analysis")
    addendum = svc.build_project_prompt_addendum("myproj", "log_analysis")
    assert "ONLY-WORKFLOW" in addendum


def test_load_code_workflow_template_per_agent(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    # Templates come from the real prompts_config.yaml; each known agent has one.
    for agent in svc.CODE_WORKFLOW_AGENT_KEYS:
        text = svc.load_code_workflow_template(agent)
        assert text, f"expected a code-workflow template for {agent}"
        assert "repo" in text.lower()
    # Unknown agents resolve to empty without raising.
    assert svc.load_code_workflow_template("nope") == ""


def test_seed_code_workflow_is_idempotent(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    # First seed writes the template; second seed is a no-op (does not clobber).
    assert svc.seed_code_workflow_prompt("myproj", "project_expert") is True
    seeded = svc.get_project_prompt_text("myproj", "project_expert")
    assert seeded

    # An admin edit must survive a re-seed.
    svc.set_project_prompt("myproj", "ADMIN-EDIT", agent_key="project_expert")
    assert svc.seed_code_workflow_prompt("myproj", "project_expert") is False
    assert svc.get_project_prompt_text("myproj", "project_expert") == "ADMIN-EDIT"

    # overwrite=True forces a refresh from the template.
    assert svc.seed_code_workflow_prompt("myproj", "project_expert", overwrite=True) is True
    assert svc.get_project_prompt_text("myproj", "project_expert") != "ADMIN-EDIT"


def test_seed_project_code_workflows_all_agents(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    seeded = svc.seed_project_code_workflows("myproj")
    assert sorted(seeded) == sorted(svc.CODE_WORKFLOW_AGENT_KEYS)
    for agent in svc.CODE_WORKFLOW_AGENT_KEYS:
        assert svc.get_project_prompt_text("myproj", agent)
