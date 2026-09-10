from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents import required_skill_policy as policy
from app.services import skills_service as skills


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    from app.config import settings

    for key in ("skills_data_dir", "project_skills_data_dir", "project_prompts_data_dir"):
        monkeypatch.setattr(settings, key, str(tmp_path / key))


def package(name, description="telemetry registers"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\nSHADOW CONTENT")
    return stream.getvalue()


@pytest.mark.parametrize("agent", ["log_analysis", "project_expert"])
@pytest.mark.parametrize("question,limit", [("", 3), ("?", 0), ("继续", 3)])
def test_empty_deployment_always_loads_full_pinned_skill(agent, question, limit, tmp_path):
    names = skills.materialize_relevant_enabled_skills(agent, tmp_path, query_text=question, max_skills=limit)
    assert names == ["humanizer-zh"]
    prompt, evidence = policy.load_required_skill_prompt(agent, tmp_path)
    original = (policy._SKILLS_ROOT / "humanizer-zh" / "SKILL.md").read_bytes()
    assert hashlib.sha256(original).hexdigest() == "e0edbdbc9008644263d5573fb59beac95794e188fd99c35012bfd79e9ae4beeb"
    assert original.decode() in prompt
    assert "围栏 JSON schema" in prompt
    assert "never invent personal experiences" in prompt
    assert evidence[0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence[0]["load_method"] == "server_prompt"


def test_required_skill_does_not_consume_optional_limit_or_allow_project_shadow(tmp_path):
    for name in ("telemetry-one", "telemetry-two", "telemetry-three"):
        skills.install_skill("project_expert", zip_bytes=package(name), source_filename="test.zip")
    skills.install_project_skill("test", zip_bytes=package("humanizer-zh"), source_filename="shadow.zip")
    names = skills.materialize_relevant_enabled_skills(
        "project_expert", tmp_path, query_text="telemetry registers", max_skills=3, project_code="test",
    )
    assert len(names) == 4
    text = (tmp_path / ".claude/skills/humanizer-zh/SKILL.md").read_text()
    assert "SHADOW CONTENT" not in text
    prompt, _ = policy.load_required_skill_prompt("project_expert", tmp_path)
    assert text in prompt


@pytest.mark.parametrize("agent", ["general_agent", "device_agent", "package_search"])
def test_unrelated_agents_have_no_required_humanizer(agent, tmp_path):
    assert policy.load_required_skill_prompt(agent, tmp_path) == ("", [])
    assert "humanizer-zh" not in skills.select_relevant_skill_names(agent, query_text="?")


@pytest.mark.parametrize("agent", ["log_analysis", "project_expert"])
def test_admin_can_preview_required_skill_but_cannot_mutate(agent):
    entry = next(item for item in skills.list_skills(agent) if item["name"] == "humanizer-zh")
    assert entry["required"] and entry["enabled"]
    assert "Humanizer-zh" in skills.read_skill_file(agent, entry["id"], "SKILL.md")["content"]
    for action in (
        lambda: skills.delete_skill(agent, entry["id"]),
        lambda: skills.set_skill_enabled(agent, entry["id"], False),
        lambda: skills.install_skill(agent, zip_bytes=package("humanizer-zh"), source_filename="shadow.zip", overwrite=True),
    ):
        with pytest.raises(skills.SkillConflictError):
            action()


@pytest.mark.parametrize("agent_key", ["log_analysis", "project_expert"])
@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.asyncio
async def test_each_agent_turn_injects_full_rules_after_custom_prompts(agent_key, locale, tmp_path, monkeypatch):
    if agent_key == "project_expert":
        from app.agents.project_expert.agent import ProjectExpertAgent as Agent
        from tests.agents.test_project_expert import _make_ctx
        ctx = _make_ctx(tmp_path)
    else:
        from app.agents.log_analysis.agent import LogAnalysisAgent as Agent
        from app.agents.log_analysis.workspace import WorkspaceContext
        (tmp_path / "repo").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "task.json").write_text(json.dumps({"question": "?", "log_type": "generic"}))
        ctx = WorkspaceContext(task_id="required-test", temp_dir=str(tmp_path), repo_dir=str(tmp_path / "repo"), logs_dir=str(tmp_path / "logs"), task_json_path=str(tmp_path / "task.json"))
    ctx.locale = locale
    captured = []
    plain_text = False

    async def fake_query(*, prompt, make_options, **kwargs):
        captured.append(make_options(None))
        if plain_text:
            yield SimpleNamespace(result="This plain text is not a structured Agent result.")
            return
        yield SimpleNamespace(result='```json\n' + json.dumps({"status": "ok", "question_type": "qa", "answer": "证据不足。", "summary": "证据不足。", "severity": "info", "root_cause_hypotheses": [], "recommended_actions": [], "related_keywords": []}) + '\n```')

    with patch("app.agents.routed_query.routed_query", fake_query), \
         patch("app.agents.anthropic_client.build_options", side_effect=lambda **kw: kw), \
         patch("app.services.model_router.candidates", return_value=[]), \
         patch("app.services.project_prompt_service.build_project_prompt_addendum", return_value="CUSTOM_PROJECT_PROMPT"), \
         patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock()):
        for question in ("?", "继续"):
            ctx.metadata["question"] = question
            events = []
            result = await Agent().run(ctx, trace_emitter=events.append)
            assert result["status"] == "ok"
            notices = [event for event in events if event.get("kind") == "required_skill_loaded"]
            assert len(notices) == 1
            assert notices[0]["load_method"] == "server_prompt"
        plain_text = True
        with patch("app.services.skills_service._enabled_entries", side_effect=OSError("optional registry unavailable")):
            result = await Agent().run(ctx)
        assert result["status"] == "schema_mismatch"
    full_text = (policy._SKILLS_ROOT / "humanizer-zh/SKILL.md").read_text()
    assert len(captured) == 3
    for options in captured:
        assert options["system_prompt"].count(full_text) == 1
        assert options["setting_sources"] == ["project"]

    # Even if optional Skill setup suppresses an exception, a missing mandatory
    # package must stop the run before querying the model.
    monkeypatch.setattr(policy, "_SKILLS_ROOT", tmp_path / "missing")
    with patch("app.agents.routed_query.routed_query", fake_query):
        with pytest.raises(FileNotFoundError):
            await Agent().run(ctx)
    assert len(captured) == 3
