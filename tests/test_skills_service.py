"""Tests for app/services/skills_service.py."""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Dict

import pytest


def _build_zip(members: Dict[str, bytes]) -> bytes:
    """Create an in-memory zip containing the given {arcname: bytes} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


_SKILL_MD = (
    "---\n"
    "name: log-grep-helper\n"
    "description: Helper skill that knows how to grep panic logs\n"
    "---\n"
    "# Body\n"
    "Use this skill to grep for panic patterns.\n"
).encode("utf-8")


@pytest.fixture()
def isolated_skills_dir(tmp_path, monkeypatch):
    """Point skills_service at a fresh tmp dir for each test."""
    from app.config import settings
    from app.services import skills_service

    monkeypatch.setattr(settings, "skills_data_dir", str(tmp_path / "agent_skills"))
    # Service reads via _skills_root(); no further patching needed.
    return tmp_path


def test_list_skills_empty(isolated_skills_dir):
    from app.services import skills_service
    assert skills_service.list_skills("log_analysis") == []


def test_install_skill_top_level_skill_md(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD, "scripts/run.sh": b"#!/bin/sh\n"})
    entry = skills_service.install_skill(
        "log_analysis", zip_bytes=zip_bytes, source_filename="grep.zip"
    )
    assert entry["name"] == "log-grep-helper"
    assert entry["enabled"] is True
    assert entry["source_filename"] == "grep.zip"
    listed = skills_service.list_skills("log_analysis")
    assert len(listed) == 1 and listed[0]["id"] == "log-grep-helper"


def test_install_skill_wrapped_directory(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip(
        {
            "log-grep-helper/SKILL.md": _SKILL_MD,
            "log-grep-helper/reference.txt": b"hello",
        }
    )
    entry = skills_service.install_skill(
        "log_analysis", zip_bytes=zip_bytes, source_filename="wrapped.zip"
    )
    assert entry["name"] == "log-grep-helper"


def test_install_rejects_missing_skill_md(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip({"reference.txt": b"hi"})
    with pytest.raises(skills_service.SkillValidationError):
        skills_service.install_skill(
            "log_analysis", zip_bytes=zip_bytes, source_filename="bad.zip"
        )


def test_install_rejects_missing_frontmatter(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip({"SKILL.md": b"# Just a markdown body, no frontmatter\n"})
    with pytest.raises(skills_service.SkillValidationError):
        skills_service.install_skill(
            "log_analysis", zip_bytes=zip_bytes, source_filename="bad.zip"
        )


def test_install_rejects_zip_slip(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip(
        {"../escape.txt": b"oops", "SKILL.md": _SKILL_MD}
    )
    with pytest.raises(skills_service.SkillValidationError):
        skills_service.install_skill(
            "log_analysis", zip_bytes=zip_bytes, source_filename="evil.zip"
        )


def test_install_conflict_then_overwrite(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    skills_service.install_skill(
        "log_analysis", zip_bytes=zip_bytes, source_filename="a.zip"
    )
    with pytest.raises(skills_service.SkillConflictError):
        skills_service.install_skill(
            "log_analysis", zip_bytes=zip_bytes, source_filename="b.zip"
        )
    entry = skills_service.install_skill(
        "log_analysis", zip_bytes=zip_bytes, source_filename="b.zip", overwrite=True
    )
    assert entry["source_filename"] == "b.zip"


def test_set_enabled_and_delete(isolated_skills_dir):
    from app.services import skills_service
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    skills_service.install_skill(
        "log_analysis", zip_bytes=zip_bytes, source_filename="a.zip"
    )
    updated = skills_service.set_skill_enabled("log_analysis", "log-grep-helper", False)
    assert updated["enabled"] is False

    skills_service.delete_skill("log_analysis", "log-grep-helper")
    assert skills_service.list_skills("log_analysis") == []
    with pytest.raises(skills_service.SkillNotFoundError):
        skills_service.delete_skill("log_analysis", "log-grep-helper")


def test_materialize_enabled_only(isolated_skills_dir, tmp_path):
    from app.services import skills_service

    # Install two skills
    enabled_md = _SKILL_MD
    disabled_md = (
        "---\n"
        "name: archived-skill\n"
        "description: a disabled one\n"
        "---\n"
        "body\n"
    ).encode("utf-8")
    skills_service.install_skill(
        "log_analysis",
        zip_bytes=_build_zip({"SKILL.md": enabled_md}),
        source_filename="enabled.zip",
    )
    skills_service.install_skill(
        "log_analysis",
        zip_bytes=_build_zip({"SKILL.md": disabled_md}),
        source_filename="disabled.zip",
    )
    skills_service.set_skill_enabled("log_analysis", "archived-skill", False)

    cwd = tmp_path / "agent_cwd"
    cwd.mkdir()
    materialized = skills_service.materialize_enabled_skills("log_analysis", str(cwd))
    assert materialized == ["log-grep-helper"]

    target = cwd / ".claude" / "skills" / "log-grep-helper" / "SKILL.md"
    assert target.is_file()
    assert b"name: log-grep-helper" in target.read_bytes()

    # Disabled skill should NOT appear
    assert not (cwd / ".claude" / "skills" / "archived-skill").exists()


def test_select_relevant_skills_prefers_request_specific_match(isolated_skills_dir, tmp_path):
    from app.services import skills_service

    smu_md = (
        "---\n"
        "name: smu-baseband-interfaces\n"
        "description: SMU RS422 baseband file transfer protocol analysis\n"
        "---\n"
        "Use for SMU, RS422, baseband, file transfer failures.\n"
    ).encode("utf-8")
    antenna_md = (
        "---\n"
        "name: ka-phased-array-antenna\n"
        "description: KA phased array antenna calibration and beam logs\n"
        "---\n"
        "Use for antenna calibration, beam position, and phased-array issues.\n"
    ).encode("utf-8")

    skills_service.install_skill(
        "log_analysis",
        zip_bytes=_build_zip({"SKILL.md": smu_md}),
        source_filename="smu.zip",
    )
    skills_service.install_skill(
        "log_analysis",
        zip_bytes=_build_zip({"SKILL.md": antenna_md}),
        source_filename="antenna.zip",
    )

    selected = skills_service.select_relevant_skill_names(
        "log_analysis",
        query_text="从SMU通过RS422发送文件到基带失败，请帮忙分析原因",
    )
    assert selected == ["smu-baseband-interfaces"]

    cwd = tmp_path / "agent_cwd_relevant"
    cwd.mkdir()
    materialized = skills_service.materialize_relevant_enabled_skills(
        "log_analysis",
        cwd,
        query_text="从SMU通过RS422发送文件到基带失败，请帮忙分析原因",
    )
    assert materialized == ["smu-baseband-interfaces"]
    assert (cwd / ".claude" / "skills" / "smu-baseband-interfaces" / "SKILL.md").is_file()
    assert not (cwd / ".claude" / "skills" / "ka-phased-array-antenna").exists()


def test_unknown_agent_rejected(isolated_skills_dir):
    from app.services import skills_service
    with pytest.raises(skills_service.UnknownAgentError):
        skills_service.list_skills("__nope__")


def test_install_zip_too_large(isolated_skills_dir, monkeypatch):
    from app.services import skills_service
    monkeypatch.setattr(skills_service, "MAX_SKILL_ZIP_BYTES", 64)
    big = _build_zip({"SKILL.md": _SKILL_MD, "blob.bin": b"x" * 1024})
    with pytest.raises(skills_service.SkillValidationError):
        skills_service.install_skill(
            "log_analysis", zip_bytes=big, source_filename="big.zip"
        )
