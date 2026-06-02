"""Verify ProjectExpertAgent and LogAnalysisAgent pass project_code to skill materialization."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


def _build_zip(members: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


_AGENT_SKILL_MD = (
    "---\n"
    "name: agent-skill\n"
    "description: Agent-level skill\n"
    "---\n"
    "Agent body.\n"
).encode("utf-8")

_PROJECT_SKILL_MD = (
    "---\n"
    "name: project-skill\n"
    "description: Project-level skill\n"
    "---\n"
    "Project body.\n"
).encode("utf-8")


@pytest.fixture()
def isolated_skills_dir(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "skills_data_dir", str(tmp_path / "agent_skills"))
    monkeypatch.setattr(settings, "project_skills_data_dir", str(tmp_path / "project_skills"))
    return tmp_path


@pytest.fixture()
def setup_skills(isolated_skills_dir):
    """Install one agent skill and one project skill."""
    from app.services import skills_service

    skills_service.install_skill(
        "project_expert",
        zip_bytes=_build_zip({"SKILL.md": _AGENT_SKILL_MD}),
        source_filename="agent.zip",
    )
    skills_service.install_skill(
        "log_analysis",
        zip_bytes=_build_zip({"SKILL.md": _AGENT_SKILL_MD}),
        source_filename="agent.zip",
    )
    skills_service.install_project_skill(
        "testproj",
        zip_bytes=_build_zip({"SKILL.md": _PROJECT_SKILL_MD}),
        source_filename="proj.zip",
    )


class TestProjectExpertSkillIntegration:

    def test_materialize_with_project_code(self, setup_skills, tmp_path):
        """Simulates what ProjectExpertAgent.run() does: extract project_code and materialize."""
        from app.services import skills_service

        task_data = {
            "repo_info": {"project_code": "testproj", "repo_url": "https://example.com/repo"},
            "question": "How does the telemetry module work?",
        }
        repo_info = task_data.get("repo_info")
        project_code = repo_info.get("project_code") or None if isinstance(repo_info, dict) else None

        cwd = tmp_path / "expert_cwd"
        cwd.mkdir()
        materialized = skills_service.materialize_relevant_enabled_skills(
            "project_expert",
            cwd,
            query_text=task_data.get("question", ""),
            project_code=project_code,
        )
        assert "agent-skill" in materialized
        assert "project-skill" in materialized
        assert (cwd / ".claude" / "skills" / "agent-skill" / "SKILL.md").is_file()
        assert (cwd / ".claude" / "skills" / "project-skill" / "SKILL.md").is_file()

    def test_no_project_code_agent_only(self, setup_skills, tmp_path):
        from app.services import skills_service

        cwd = tmp_path / "expert_cwd_noproject"
        cwd.mkdir()
        materialized = skills_service.materialize_relevant_enabled_skills(
            "project_expert",
            cwd,
            query_text="How does the telemetry module work?",
            project_code=None,
        )
        assert "agent-skill" in materialized
        assert "project-skill" not in materialized


class TestLogAnalysisSkillIntegration:

    def test_materialize_with_project_code(self, setup_skills, tmp_path):
        """Simulates what LogAnalysisAgent.run() does: extract project_code and materialize."""
        from app.services import skills_service

        repo_info = {"project_code": "testproj"}
        project_code = repo_info.get("project_code") or None

        cwd = tmp_path / "log_cwd"
        cwd.mkdir()
        materialized = skills_service.materialize_relevant_enabled_skills(
            "log_analysis",
            cwd,
            query_text="SMU panic log analysis",
            project_code=project_code,
        )
        assert "agent-skill" in materialized
        assert "project-skill" in materialized

    def test_no_project_code_agent_only(self, setup_skills, tmp_path):
        from app.services import skills_service

        cwd = tmp_path / "log_cwd_noproject"
        cwd.mkdir()
        materialized = skills_service.materialize_relevant_enabled_skills(
            "log_analysis",
            cwd,
            query_text="SMU panic log analysis",
            project_code=None,
        )
        assert "agent-skill" in materialized
        assert "project-skill" not in materialized
