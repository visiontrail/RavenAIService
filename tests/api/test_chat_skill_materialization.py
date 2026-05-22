"""End-to-end test for task 12.3: a Skill installed for ``device_agent`` is
materialized into ``<workspace>/.claude/skills/<name>/SKILL.md`` before
``claude_agent_sdk.query`` runs.

Approach:
1. Point ``skills_data_dir`` at a temp directory.
2. Call ``skills_service.install_skill`` with a minimal zip (``SKILL.md`` only).
3. Drive ``POST /chat`` with a mocked SDK ``query`` that captures
   ``options.cwd`` and asserts the SKILL.md exists at that path *while* the
   query is running (workspace is cleaned up after).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ai_chat as ai_chat_api
from app.api.users import get_optional_user
from app.models.database import get_db


# ────────────────────────── Fake SDK plumbing ──────────────────────


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_input_tokens = 0


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, blocks: List[_TextBlock]) -> None:
        self.content = blocks
        self.usage = _FakeUsage()


class _ResultMessage:
    def __init__(self, text: str) -> None:
        self.result = text
        self.num_turns = 1
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


class _FakeDevice:
    def __init__(self) -> None:
        self.capabilities = {"protocol_version": 2, "mcp": {"servers": []}}


# ─────────────────────── Fixtures ─────────────────────────────────


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    application.dependency_overrides[get_optional_user] = lambda: None

    async def _no_db():
        yield None

    application.dependency_overrides[get_db] = _no_db
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def anthropic_ok(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr(
        "app.config.settings.anthropic_model", "claude-sonnet-4-6", raising=False
    )


@pytest.fixture
def fake_device(monkeypatch):
    async def _get_device(*_a, **_kw):
        return _FakeDevice()

    monkeypatch.setattr(
        "app.services.device_link_service.device_link_manager.get_device", _get_device
    )


def _minimal_skill_zip() -> bytes:
    """Build a zip containing a single top-level ``SKILL.md`` with a valid
    frontmatter ``name`` field. ``skills_service`` will accept this as a Skill."""
    buf = io.BytesIO()
    skill_md = (
        "---\n"
        "name: device-troubleshooter\n"
        "description: Minimal test skill\n"
        "---\n"
        "\n"
        "# device-troubleshooter\n"
        "\n"
        "Body content for the test skill.\n"
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
    return buf.getvalue()


# ───────────────────────── Test ────────────────────────────────────


def test_enabled_device_agent_skill_is_materialized_before_query(
    tmp_path, client, anthropic_ok, fake_device, monkeypatch
):
    """An enabled Skill for ``device_agent`` is materialized at
    ``<workspace>/.claude/skills/<name>/SKILL.md`` *during* the SDK ``query``
    call (workspace is wiped on ``finally``, so we must observe it mid-run)."""

    # 1. Redirect skill storage to a temp dir; install + enable a skill.
    monkeypatch.setattr("app.config.settings.skills_data_dir", str(tmp_path / "skills"))

    from app.services import skills_service

    entry = skills_service.install_skill(
        "device_agent", zip_bytes=_minimal_skill_zip(), source_filename="dt.zip"
    )
    assert entry["name"] == "device-troubleshooter"
    assert entry["enabled"] is True

    # 2. Capture options.cwd from the fake SDK query and verify the SKILL.md
    #    exists at <cwd>/.claude/skills/<name>/SKILL.md right then.
    observed: Dict[str, Any] = {}

    async def _fake_query(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        cwd = Path(getattr(options, "cwd", ""))
        observed["cwd"] = cwd
        skill_md = cwd / ".claude" / "skills" / "device-troubleshooter" / "SKILL.md"
        observed["skill_md_exists"] = skill_md.is_file()
        observed["skill_md_text"] = (
            skill_md.read_text(encoding="utf-8") if observed["skill_md_exists"] else ""
        )
        # setting_sources must include 'project' when a skill is materialized
        observed["setting_sources"] = list(getattr(options, "setting_sources", []) or [])
        yield _AssistantMessage([_TextBlock("done")])
        yield _ResultMessage("done")

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query)

    # 3. Drive a chat run.
    resp = client.post(
        "/chat",
        json={
            "message": "请检查设备",
            "session_id": "sess-skill-1",
            "target_device_id": "dev-1",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text

    # 4. Verify the skill was on disk while query ran.
    assert observed.get("skill_md_exists") is True, (
        f"SKILL.md was not materialized; observed={observed}"
    )
    assert "device-troubleshooter" in observed.get("skill_md_text", "")
    assert "project" in observed.get("setting_sources", []), (
        "setting_sources should contain 'project' when skills are materialized"
    )

    # 5. After the run, the per-session workspace must be cleaned up.
    assert not observed["cwd"].exists(), (
        f"workspace {observed['cwd']} should have been cleaned up after run"
    )


def test_disabled_skill_is_not_materialized(
    tmp_path, client, anthropic_ok, fake_device, monkeypatch
):
    """When a Skill exists but is disabled, no materialized SKILL.md should
    appear under the workspace and ``setting_sources`` must not include
    ``project``."""

    monkeypatch.setattr("app.config.settings.skills_data_dir", str(tmp_path / "skills"))

    from app.services import skills_service

    entry = skills_service.install_skill(
        "device_agent", zip_bytes=_minimal_skill_zip(), source_filename="dt.zip"
    )
    skills_service.set_skill_enabled("device_agent", entry["id"], enabled=False)

    observed: Dict[str, Any] = {}

    async def _fake_query(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        cwd = Path(getattr(options, "cwd", ""))
        skills_root = cwd / ".claude" / "skills"
        # Skills root may exist (workspace pre-creates it) but should be empty.
        observed["skill_dir_children"] = (
            sorted(p.name for p in skills_root.iterdir())
            if skills_root.exists()
            else []
        )
        observed["setting_sources"] = list(getattr(options, "setting_sources", []) or [])
        yield _ResultMessage("ok")

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query)

    resp = client.post(
        "/chat",
        json={
            "message": "hi",
            "session_id": "sess-skill-2",
            "target_device_id": "dev-1",
            "remember": False,
        },
    )
    assert resp.status_code == 200, resp.text
    assert observed.get("skill_dir_children") == [], (
        f"disabled skill should not be materialized: {observed}"
    )
    assert "project" not in observed.get("setting_sources", [])
