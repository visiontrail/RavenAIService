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
            {"hypothesis": "Null pointer in handler", "evidence": ["repo:src/main.c:42"]}
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
    return patch("app.agents.anthropic_client.build_options", return_value=fake_options)


def _patch_mcp_server():
    return patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock())


def _patch_prompts():
    system = "You are a test agent."
    user_tmpl = "Question: {question} log_type: {log_type} task_id: {task_id} hints: {hints}"
    return patch("app.agents.log_analysis.prompts.get_prompts", return_value=(system, user_tmpl))


def _patch_skills():
    return patch("app.services.skills_service.materialize_enabled_skills", return_value=[])


# ─────────────────────── Tests ─────────────────────────────────────

class TestLogAnalysisAgentRun:
    @pytest.mark.asyncio
    async def test_successful_run_parses_json(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_ok
        fake_sdk.ClaudeAgentOptions = MagicMock

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "ok"
        assert result["engine"] == "claude-agent-sdk"
        assert result["schema_version"] == 3
        assert result["summary"] == "Found issue in module X"
        assert result["severity"] == "error"
        assert len(result["root_cause_hypotheses"]) == 1

    @pytest.mark.asyncio
    async def test_run_logs_workflow_events(self, workspace_ctx, caplog):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_ok
        fake_sdk.ClaudeAgentOptions = MagicMock

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            with caplog.at_level("INFO"):
                await LogAnalysisAgent().run(workspace_ctx)

        workflow_logs = [record.message for record in caplog.records if "LogAnalysisAgent workflow" in record.message]
        assert any("event=run_start" in message for message in workflow_logs)
        assert any("event=tool_call" in message and "lookup_project_repo" in message for message in workflow_logs)
        assert any("event=tool_result" in message for message in workflow_logs)
        assert any("event=run_complete" in message for message in workflow_logs)

    @pytest.mark.asyncio
    async def test_tool_trace_masks_token(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_ok

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
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

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "schema_mismatch"
        assert "cannot format" in result["raw"]

    @pytest.mark.asyncio
    async def test_project_repo_not_registered(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_not_registered

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "error"
        assert result["error_kind"] == "project_repo_not_registered"

    @pytest.mark.asyncio
    async def test_uses_context_question_over_task_json_question(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        prompts: List[str] = []

        async def _fake_query_capture(*args, **kwargs) -> AsyncIterator[Any]:
            prompts.append(kwargs.get("prompt") or args[0])
            yield FakeResultMessage(result=_make_good_result_json())

        workspace_ctx.metadata["question"] = "克隆代码仓库并告诉我最新两次修改"

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_capture

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            result = await LogAnalysisAgent().run(workspace_ctx)

        assert result["status"] == "ok"
        assert prompts
        assert "克隆代码仓库" in prompts[0]
        assert "What failed?" not in prompts[0]

    @pytest.mark.asyncio
    async def test_deepseek_does_not_register_mcp_server(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_schema_mismatch

        with _patch_build_options() as mock_build_options, \
             _patch_mcp_server() as mock_get_mcp_server, \
             _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            await LogAnalysisAgent().run(workspace_ctx)

        mock_get_mcp_server.assert_not_called()
        kwargs = mock_build_options.call_args.kwargs
        assert kwargs["mcp_servers"] is None
        assert "mcp__project_repo__lookup_project_repo" not in kwargs["allowed_tools"]

    @pytest.mark.asyncio
    async def test_bash_tool_is_unrestricted_for_temp_workspace(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_schema_mismatch

        with _patch_build_options() as mock_build_options, \
             _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=600,
             )):
            await LogAnalysisAgent().run(workspace_ctx)

        kwargs = mock_build_options.call_args.kwargs
        assert kwargs["permission_mode"] == "bypassPermissions"
        assert "Bash" in kwargs["allowed_tools"]
        assert not any(tool.startswith("Bash(") for tool in kwargs["allowed_tools"])
        assert "hooks" not in kwargs


class TestRuntimeTooling:
    def test_dockerfile_installs_agent_cli_tools(self):
        from pathlib import Path

        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        for package in ("git", "ripgrep", "jq"):
            assert package in dockerfile


class TestRunSync:
    def test_run_sync_timeout(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent

        async def _slow_run(self, _, cancel_event=None):
            await asyncio.sleep(9999)

        with patch.object(LogAnalysisAgent, "run", _slow_run), \
             patch("app.config.settings", MagicMock(
                 anthropic_request_timeout_seconds=0.01,
             )):
            result = LogAnalysisAgent().run_sync(workspace_ctx)

        assert result["status"] == "error"
        assert result["error_kind"] == "timeout"


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_event_aborts_between_messages(self, workspace_ctx):
        """Agent should observe cancel_event between SDK messages and return cancelled."""
        from app.agents.log_analysis.agent import LogAnalysisAgent
        import threading

        cancel_event = threading.Event()

        async def _fake_query_drip(*args, **kwargs):
            # First message comes through normally.
            yield FakeAssistantMessage(
                tool_uses=[FakeToolUse(name="Read", input={"path": "x"})]
            )
            # User cancels between messages.
            cancel_event.set()
            yield FakeToolResultMessage(
                tool_results=[FakeToolResult(tool_use_id="1", content="data")]
            )
            yield FakeResultMessage(result=_make_good_result_json())

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query_drip

        with _patch_build_options(), _patch_mcp_server(), _patch_prompts(), _patch_skills(), \
             patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}), \
             patch("app.config.settings", MagicMock(
                 anthropic_model="deepseek-v4-pro",
                 anthropic_provider="deepseek",
                 anthropic_request_timeout_seconds=3600,
             )):
            result = await LogAnalysisAgent().run(workspace_ctx, cancel_event=cancel_event)

        assert result["status"] == "cancelled"
        assert result["error_kind"] == "cancelled"
        # The first tool_call should have been recorded before cancel was observed.
        assert any(entry.get("name") == "Read" for entry in result["tool_trace"])

    def test_run_sync_passes_cancel_event(self, workspace_ctx):
        from app.agents.log_analysis.agent import LogAnalysisAgent
        import threading

        received: dict = {}

        async def _capture_run(self, ctx, cancel_event=None):
            received["evt"] = cancel_event
            return {
                "engine": "claude-agent-sdk",
                "model": "fake",
                "schema_version": 3,
                "status": "ok",
                "question_type": "other",
                "answer": "",
                "summary": "",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                "tool_trace": [],
                "raw": "",
                "duration_seconds": 0.0,
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            }

        evt = threading.Event()
        with patch.object(LogAnalysisAgent, "run", _capture_run), \
             patch("app.config.settings", MagicMock(anthropic_request_timeout_seconds=10)):
            LogAnalysisAgent().run_sync(workspace_ctx, cancel_event=evt)

        assert received["evt"] is evt


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
        from app.tasks.ai_analysis import run_ai_analysis_task

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
             patch("app.config.settings") as cfg_settings:
            mock_settings.max_retry_attempts = 0
            mock_settings.anthropic_model = "deepseek-v4-pro"
            mock_settings.anthropic_request_timeout_seconds = 600
            mock_task.request.id = "test-task"
            cfg_settings.code_repo_clone_base_dir = tmpdir
            cfg_settings.ai_analysis_max_extract_bytes = 100 * 1024 * 1024
            session = self._make_session(log_record)
            MockSession.return_value = session

            result = run_ai_analysis_task.run(log_record.id, "test query")

        assert result["error_kind"] == "missing_metadata_json"

        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
