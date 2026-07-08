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


def test_load_default_prompt_templates(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    # Templates come from the real prompts_config.yaml. Only the project expert
    # has tiered defaults (repo + repoless); the other agents ship their code
    # workflow inside the base system prompt and have no seeding templates.
    with_repo = svc.load_default_prompt_template("project_expert", has_repo=True)
    without_repo = svc.load_default_prompt_template("project_expert", has_repo=False)
    assert with_repo and "repo" in with_repo.lower()
    assert without_repo and without_repo != with_repo

    for agent in ("log_analysis", "package_search"):
        assert svc.load_default_prompt_template(agent, has_repo=True) == ""
        assert svc.load_default_prompt_template(agent, has_repo=False) == ""

    # Unknown agents resolve to empty without raising.
    assert svc.load_default_prompt_template("nope", has_repo=True) == ""


def test_seed_default_prompt_is_idempotent(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    # First seed writes the template; second seed is a no-op (does not clobber).
    assert svc.seed_default_project_prompt("myproj", "project_expert", has_repo=True) is True
    seeded = svc.get_project_prompt_text("myproj", "project_expert")
    assert seeded
    assert (
        svc.seed_default_project_prompt("myproj", "project_expert", has_repo=True) is False
    )

    # An admin edit must survive a re-seed (for either variant).
    svc.set_project_prompt("myproj", "ADMIN-EDIT", agent_key="project_expert")
    assert (
        svc.seed_default_project_prompt("myproj", "project_expert", has_repo=True) is False
    )
    assert (
        svc.seed_default_project_prompt("myproj", "project_expert", has_repo=False) is False
    )
    assert svc.get_project_prompt_text("myproj", "project_expert") == "ADMIN-EDIT"

    # overwrite=True forces a refresh from the template.
    assert (
        svc.seed_default_project_prompt(
            "myproj", "project_expert", has_repo=True, overwrite=True
        )
        is True
    )
    assert svc.get_project_prompt_text("myproj", "project_expert") != "ADMIN-EDIT"


def test_seed_swaps_unedited_default_on_repo_flip(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    # Repoless project gets the no-repo default.
    assert svc.seed_default_project_prompt("myproj", "project_expert", has_repo=False) is True
    no_repo_default = svc.get_project_prompt_text("myproj", "project_expert")
    assert no_repo_default == svc.load_default_prompt_template(
        "project_expert", has_repo=False
    )

    # Linking a repo swaps the unedited default to the code-workflow variant.
    assert svc.seed_default_project_prompt("myproj", "project_expert", has_repo=True) is True
    assert svc.get_project_prompt_text("myproj", "project_expert") == (
        svc.load_default_prompt_template("project_expert", has_repo=True)
    )

    # And unlinking swaps it back.
    assert svc.seed_default_project_prompt("myproj", "project_expert", has_repo=False) is True
    assert svc.get_project_prompt_text("myproj", "project_expert") == no_repo_default


def test_seed_project_default_prompts_only_expert(isolated_prompts_dir):
    from app.services import project_prompt_service as svc

    seeded = svc.seed_project_default_prompts("myproj", has_repo=True)
    assert seeded == ["project_expert"]
    assert svc.get_project_prompt_text("myproj", "project_expert")
    # The other agents' layers stay empty by default.
    assert svc.get_project_prompt_text("myproj", "log_analysis") == ""
    assert svc.get_project_prompt_text("myproj", "package_search") == ""

    seeded_repoless = svc.seed_project_default_prompts("myproj2", has_repo=False)
    assert seeded_repoless == ["project_expert"]
    assert svc.get_project_prompt_text("myproj2", "project_expert") == (
        svc.load_default_prompt_template("project_expert", has_repo=False)
    )
