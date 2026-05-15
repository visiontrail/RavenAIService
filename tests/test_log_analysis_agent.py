"""Integration tests for LogAnalysisAgent (mock claude_agent_sdk.query)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────── Fake SDK Message Types ────────────────────

@dataclass
class FakeToolUse:
    name: str
    input: Any


@dataclass
class FakeAssistantMessage:
    tool_uses: List[FakeToolUse] = field(default_factory=list)
    usage: Optional[Any] = None


@dataclass
class FakeToolResult:
    tool_use_id: str
    content: Any


@dataclass
class FakeToolResultMessage:
    tool_results: List[FakeToolResult] = field(default_factory=list)


@dataclass
class FakeResultMessage:
    result: str


def _make_good_result_json() -> str:
    payload = {
        "status": "ok",
        "summary": "Found issue in module X",
        "severity": "error",
        "root_cause_hypotheses": [
            {"hypothesis": "Null pointer in handler", "evidence": ["repo:src/main.c:42"], "confidence": 0.9}
        ],
        "recommended_actions": ["Fix null check"],
        "related_keywords": ["null", "handler"],
    }
    return f"```json\n{json.dumps(payload)}\n```"


async def _fake_query_ok(*args, **kwargs) -> AsyncIterator[Any]:
    """Simulates: AssistantMessage(lookup_project_repo) → ToolResultMessage → AssistantMessage(git clone) → ResultMessage"""
    yield FakeAssistantMessage(
        tool_uses=[FakeToolUse(name="mcp__project_repo__lookup_project_repo", input={"project_code": "foo"})]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(
            tool_use_id="1",
            content=[{"type": "text", "text": json.dumps({
                "project_code": "foo",
                "project_name": "Foo",
                "repo_url": "https://gitlab.example/foo.git",
                "clone_url": "https://oauth2:secret-token@gitlab.example/foo.git",
                "default_branch": "main",
                "auth_required": True,
            })}],
        )]
    )
    yield FakeAssistantMessage(
        tool_uses=[FakeToolUse(name="Bash", input={"command": "git clone $CLONE_URL repo"})]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(tool_use_id="2", content="Cloning into 'repo'...")]
    )
    yield FakeResultMessage(result=_make_good_result_json())


async def _fake_query_schema_mismatch(*args, **kwargs) -> AsyncIterator[Any]:
    yield FakeResultMessage(result="I analyzed the logs and found some issues but cannot format as JSON.")


async def _fake_query_not_registered(*args, **kwargs) -> AsyncIterator[Any]:
    yield FakeAssistantMessage(
        tool_uses=[FakeToolUse(name="mcp__project_repo__lookup_project_repo", input={"project_code": "foo"})]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(tool_use_id="1", content='{"error": "not_found", "project_code": "foo"}')]
    )
    # Agent retries with project_name
    yield FakeAssistantMessage(
        tool_uses=[FakeToolUse(name="mcp__project_repo__lookup_project_repo", input={"project_code": "Foo Project"})]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(tool_use_id="2", content='{"error": "not_found", "project_code": "foo project"}')]
    )
    error_result = json.dumps({
        "status": "error",
        "error_kind": "project_repo_not_registered",
        "summary": "Project not registered",
        "severity": "error",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": [],
    })
    yield FakeResultMessage(result=f"```json\n{error_result}\n```")


# ─────────────────────── Fixtures ──────────────────────────────────

@pytest.fixture
def workspace_ctx():
    import tempfile, os, json as _json
    from app.agents.log_analysis.workspace import WorkspaceContext

    tmp = tempfile.mkdtemp()
    task_json = os.path.join(tmp, "task.json")
    _json.dump({"log_id": 1, "question": "What failed?", "log_type": "generic", "hints": ""}, open(task_json, "w"))
    os.makedirs(os.path.join(tmp, "repo"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)

    ctx = WorkspaceContext(
        task_id="test-task-id",
        temp_dir=tmp,
        logs_dir=os.path.join(tmp, "logs"),
        repo_dir=os.path.join(tmp, "repo"),
        task_json_path=task_json,
    )
    ctx.metadata = {"log_type": "generic", "question": "What failed?"}
    yield ctx

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def _patch_build_options():
    fake_options = MagicMock()
    return patch("app.agents.log_analysis.agent.build_options", return_value=fake_options)


def _patch_mcp_server():
    return patch("app.agents.log_analysis.agent.get_mcp_server", return_value=MagicMock())


def _patch_prompts():
    system = "You are a test agent."
    user_tmpl = "Question: {question} log_type: {log_type} task_id: {task_id} hints: {hints}"
    return patch("app.agents.log_analysis.agent.get_prompts", return_value=(system, user_tmpl))


def _patch_settings():
    s = MagicMock()
    s.anthropic_model = "deepseek-v4-pro"
    s.anthropic_provider = "deepseek"
    s.anthropic_request_timeout_seconds = 600
    from app.agents.anthropic_client import PROVIDER_PROFILES
    with patch("app.agents.log_analysis.agent.settings", s), \
         patch("app.agents.log_analysis.agent.PROVIDER_PROFILES", PROVIDER_PROFILES):
        yield s


# ─────────────────────── Tests ─────────────────────────────────────

class TestLogAnalysisAgentRun:
    @pytest.mark.asyncio
    async def test_successful_run_parses_json(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_ok
        fake_sdk.ClaudeAgentOptions = MagicMock

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.agents.log_analysis.agent.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            from app.agents.anthropic_client import PROVIDER_PROFILES
            with patch("app.agents.log_analysis.agent.PROVIDER_PROFILES", PROVIDER_PROFILES):
                result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "ok"
        assert result["engine"] == "claude-agent-sdk"
        assert result["schema_version"] == 2
        assert result["summary"] == "Found issue in module X"
        assert result["severity"] == "error"
        assert len(result["root_cause_hypotheses"]) == 1

    @pytest.mark.asyncio
    async def test_tool_trace_masks_token(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_ok

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.agents.log_analysis.agent.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            from app.agents.anthropic_client import PROVIDER_PROFILES
            with patch("app.agents.log_analysis.agent.PROVIDER_PROFILES", PROVIDER_PROFILES):
                result = await LogAnalysisAgent().run(workspace_ctx)

        # tool_trace should not contain plaintext token
        trace_str = json.dumps(result["tool_trace"])
        assert "secret-token" not in trace_str, "Token must be masked in tool_trace"
        assert "https://***@" in trace_str or "oauth2:secret" not in trace_str

    @pytest.mark.asyncio
    async def test_schema_mismatch_when_no_json(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_schema_mismatch

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.agents.log_analysis.agent.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            from app.agents.anthropic_client import PROVIDER_PROFILES
            with patch("app.agents.log_analysis.agent.PROVIDER_PROFILES", PROVIDER_PROFILES):
                result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "schema_mismatch"
        assert "cannot format" in result["raw"]

    @pytest.mark.asyncio
    async def test_project_repo_not_registered(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_not_registered

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.agents.log_analysis.agent.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            from app.agents.anthropic_client import PROVIDER_PROFILES
            with patch("app.agents.log_analysis.agent.PROVIDER_PROFILES", PROVIDER_PROFILES):
                result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "error"
        assert result["error_kind"] == "project_repo_not_registered"


class TestRunSync:
    def test_run_sync_timeout(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        async def _slow_run(_):
            await asyncio.sleep(9999)

        with patch.object(LogAnalysisAgent, "run", _slow_run), \
             patch("app.agents.log_analysis.agent.settings", MagicMock(
                 anthropic_request_timeout_seconds=0.01,
             )):
            result = LogAnalysisAgent().run_sync(workspace_ctx)

        assert result["status"] == "error"
        assert result["error_kind"] == "timeout"


class TestFastFailCeleryTask:
    def _make_log_record(self, archive_path=None):
        r = MagicMock()
        r.id = 1
        r.archive_path = archive_path
        r.is_deleted = False
        r.metadata_json = None
        r.file_path = "/tmp/test.log"
        return r

    def _make_session(self, log_record):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = log_record
        return session

    def test_missing_archive_returns_error_kind(self):
        from app.tasks.ai_analysis import run_ai_analysis_task

        log_record = self._make_log_record(archive_path=None)

        with patch("app.tasks.ai_analysis.SessionLocal") as MockSession, \
             patch("app.tasks.ai_analysis.settings") as mock_settings, \
             patch("app.tasks.ai_analysis.current_task") as mock_task:
            mock_settings.max_retry_attempts = 0
            mock_settings.anthropic_model = "deepseek-v4-pro"
            mock_settings.anthropic_request_timeout_seconds = 600
            mock_task.request.id = "test-task"
            session = self._make_session(log_record)
            MockSession.return_value = session

            result = run_ai_analysis_task.run(log_record.id, "test query")

        assert result["error_kind"] == "missing_archive"

    def test_missing_metadata_json_returns_error_kind(self):
        import tarfile
        import tempfile
        import io
        from pathlib import Path

        tmpdir = tempfile.mkdtemp()
        archive = Path(tmpdir) / "test.tar.gz"

        with tarfile.open(str(archive), "w:gz") as tf:
            data = b"no metadata here"
            info = tarfile.TarInfo(name="app.log")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        log_record = self._make_log_record(archive_path=str(archive))

        with patch("app.tasks.ai_analysis.SessionLocal") as MockSession, \
             patch("app.tasks.ai_analysis.settings") as mock_settings, \
             patch("app.tasks.ai_analysis.current_task") as mock_task, \
             patch("app.agents.log_analysis.workspace.settings") as ws_settings:
            mock_settings.max_retry_attempts = 0
            mock_settings.anthropic_model = "deepseek-v4-pro"
            mock_settings.anthropic_request_timeout_seconds = 600
            mock_task.request.id = "test-task"
            ws_settings.code_repo_clone_base_dir = tmpdir
            ws_settings.ai_analysis_max_extract_bytes = 100 * 1024 * 1024
            session = self._make_session(log_record)
            MockSession.return_value = session

            result = run_ai_analysis_task.run(log_record.id, "test query")

        assert result["error_kind"] == "missing_metadata_json"

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
