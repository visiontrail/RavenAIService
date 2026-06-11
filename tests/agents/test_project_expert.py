from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.agents.project_expert.workspace import WorkspaceContext


@dataclass
class FakeToolUse:
    name: str
    input: Any
    id: Optional[str] = None


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


def _repo(**overrides):
    data = {
        "id": 7,
        "project_code": "foo",
        "project_name": "Foo Service",
        "repo_url": "https://gitlab.example/foo.git",
        "default_branch": "main",
        "enabled": True,
        "git_token": "secret-token",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _result_json(answer: str = "见 repo/app/main.py:10") -> str:
    payload = {
        "status": "ok",
        "question_type": "qa",
        "answer": answer,
        "summary": answer,
        "severity": "info",
        "root_cause_hypotheses": [],
        "recommended_actions": [],
        "related_keywords": [],
    }
    return f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


async def _fake_query_with_clone(*_args, **_kwargs) -> AsyncIterator[Any]:
    yield FakeAssistantMessage(
        tool_uses=[
            FakeToolUse(
                name="mcp__project_repo__lookup_project_repo",
                input={"project_code": "foo"},
                id="lookup-1",
            )
        ]
    )
    yield FakeToolResultMessage(
        tool_results=[
            FakeToolResult(
                tool_use_id="lookup-1",
                content=[
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "project_code": "foo",
                                "clone_url": "https://oauth2:secret-token@gitlab.example/foo.git",
                                "default_branch": "main",
                            }
                        ),
                    }
                ],
            )
        ]
    )
    yield FakeAssistantMessage(
        tool_uses=[
            FakeToolUse(
                name="Bash",
                input={
                    "command": "git clone --depth 1 https://oauth2:secret-token@gitlab.example/foo.git repo"
                },
                id="clone-1",
            )
        ]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(tool_use_id="clone-1", content="Cloning into 'repo'...")]
    )
    yield FakeResultMessage(result=_result_json())


async def _fake_query_reuse_existing_repo(*_args, **_kwargs) -> AsyncIterator[Any]:
    yield FakeAssistantMessage(
        tool_uses=[
            FakeToolUse(
                name="Bash",
                input={"command": "git -C repo status --short && rg auth repo"},
                id="reuse-1",
            )
        ]
    )
    yield FakeToolResultMessage(
        tool_results=[FakeToolResult(tool_use_id="reuse-1", content="repo/app/main.py:10: auth")]
    )
    yield FakeResultMessage(result=_result_json("复用 repo/.git 后定位到 repo/app/main.py:10"))


async def _fake_query_unescaped_answer_quotes(*_args, **_kwargs) -> AsyncIterator[Any]:
    yield FakeResultMessage(result=(
        "基于对灵犀10操作维护项目源码的调查，以下是关于重构的回答：\n"
        "```json\n"
        "{\n"
        '  "status": "ok",\n'
        '  "question_type": "qa",\n'
        '  "answer": "在灵犀10（LX10）操作维护这个项目中，**"重构"有明确的专有含义：它指的是「在轨软件重构」**，即通过地面指令远程替换/重新加载星载基带处理器上运行的不同软件版本。根据 `repo/README.md:71-78`，它包括基带软件、核心网版本、DVB馈电版本、Ka相控阵软件和客户定制启动脚本的重构。",\n'
        '  "summary": "重构在该项目中主要指在轨软件重构。",\n'
        '  "severity": "info",\n'
        '  "root_cause_hypotheses": [],\n'
        '  "recommended_actions": [],\n'
        '  "related_keywords": ["重构", "在轨软件重构"]\n'
        "}\n"
        "```"
    ))


async def _fake_query_plain_skill_answer(*_args, **_kwargs) -> AsyncIterator[Any]:
    yield FakeResultMessage(result="TURQUOISE-MONGOOSE-9")


def _patch_agent_common(fake_query):
    fake_sdk = SimpleNamespace(query=fake_query)
    return patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk})


def _make_ctx(tmp_path: Path) -> WorkspaceContext:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    task_json = tmp_path / "task.json"
    task_json.write_text(
        json.dumps(
            {
                "question": "鉴权在哪里实现？",
                "hints": "",
                "repo_info": {
                    "project_code": "foo",
                    "repo_url": "https://gitlab.example/foo.git",
                    "default_branch": "main",
                    "source": "user_selected_project_repo",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return WorkspaceContext(
        task_id="task-1",
        temp_dir=str(tmp_path),
        repo_dir=str(repo_dir),
        task_json_path=str(task_json),
        metadata={"question": "鉴权在哪里实现？", "hints": ""},
    )


def _decode_sse_event(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk[len("data: "):].strip())


def test_workspace_contains_only_repo_and_task_json_without_token(monkeypatch, tmp_path):
    from app.agents.project_expert import workspace

    monkeypatch.setattr(workspace.settings, "code_repo_clone_base_dir", str(tmp_path))

    ctx = workspace.prepare(project_repo=_repo(), question="鉴权在哪里实现？", hints="hint")
    root = Path(ctx.temp_dir)
    task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))

    assert sorted(item.name for item in root.iterdir()) == ["repo", "task.json"]
    assert Path(ctx.repo_dir).is_dir()
    assert not (root / "logs").exists()
    assert task_data["repo_info"]["source"] == "user_selected_project_repo"
    assert task_data["repo_info"]["project_code"] == "foo"
    assert "secret-token" not in json.dumps(task_data, ensure_ascii=False)

    workspace.cleanup(ctx)
    workspace.cleanup(ctx)
    assert not root.exists()


@pytest.mark.asyncio
async def test_agent_uses_expected_tools_materializes_project_skills_and_masks_tokens(tmp_path):
    from app.agents.project_expert.agent import ALLOWED_TOOLS, ProjectExpertAgent

    ctx = _make_ctx(tmp_path)
    trace_events: list[dict] = []
    captured_prompt: dict[str, str] = {}
    build_options = MagicMock(return_value=MagicMock())

    async def fake_query_with_prompt_capture(*args, **kwargs) -> AsyncIterator[Any]:
        captured_prompt["prompt"] = kwargs.get("prompt") or (args[0] if args else "")
        async for message in _fake_query_with_clone(*args, **kwargs):
            yield message

    with _patch_agent_common(fake_query_with_prompt_capture), \
        patch("app.agents.anthropic_client.build_options", build_options), \
        patch(
            "app.services.skills_service.materialize_enabled_skills",
            return_value=["repo-reader"],
        ) as materialize, \
        patch(
            "app.services.skills_service.enabled_skill_overviews",
            return_value=[{"name": "repo-reader", "description": "读取仓库源码文件"}],
        ), \
        patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock()):
        result = await ProjectExpertAgent().run(ctx, trace_emitter=trace_events.append)

    assert result["engine"] == "claude-agent-sdk"
    assert result["status"] == "ok"
    assert "repo/app/main.py:10" in result["answer"]
    materialize.assert_called_once()
    assert materialize.call_args.args[0] == "project_expert"
    assert materialize.call_args.args[1] == ctx.temp_dir

    kwargs = build_options.call_args.kwargs
    assert kwargs["allowed_tools"] == ALLOWED_TOOLS
    assert kwargs["cwd"] == ctx.temp_dir
    assert kwargs["setting_sources"] == ["project"]
    assert "可用的 Skill（按需加载）" in kwargs["system_prompt"]
    assert "可用的 Skill（按需加载）" in captured_prompt["prompt"]
    assert "`repo-reader`：读取仓库源码文件" in captured_prompt["prompt"]
    assert '"skill": "repo-reader"' in captured_prompt["prompt"]
    assert "最终输出仍必须遵守第 5 步的围栏 JSON schema" in captured_prompt["prompt"]

    trace_text = json.dumps(result["trace_events"], ensure_ascii=False)
    assert "secret-token" not in trace_text
    assert "https://***@gitlab.example/foo.git" in trace_text


@pytest.mark.asyncio
async def test_agent_followup_reuses_existing_repo_without_clone(tmp_path):
    from app.agents.project_expert.agent import ProjectExpertAgent

    ctx = _make_ctx(tmp_path)
    (Path(ctx.repo_dir) / ".git").mkdir()

    with _patch_agent_common(_fake_query_reuse_existing_repo), \
        patch("app.agents.anthropic_client.build_options", return_value=MagicMock()), \
        patch("app.services.skills_service.materialize_enabled_skills", return_value=[]), \
        patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock()):
        result = await ProjectExpertAgent().run(ctx)

    trace_text = json.dumps(result["trace_events"], ensure_ascii=False)
    assert "git clone" not in trace_text
    assert "git -C repo status" in trace_text
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_recovers_grounded_answer_with_unescaped_inner_quotes(tmp_path):
    from app.agents.project_expert.agent import ProjectExpertAgent

    ctx = _make_ctx(tmp_path)

    with _patch_agent_common(_fake_query_unescaped_answer_quotes), \
        patch("app.agents.anthropic_client.build_options", return_value=MagicMock()), \
        patch("app.services.skills_service.materialize_enabled_skills", return_value=[]), \
        patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock()):
        result = await ProjectExpertAgent().run(ctx)

    assert result["status"] == "ok"
    assert result["question_type"] == "qa"
    assert '**"重构"有明确的专有含义' in result["answer"]
    assert "repo/README.md:71-78" in result["answer"]
    assert "星载基带处理器" in result["answer"]
    assert result["answer"] != "在灵犀10（LX10）操作维护这个项目中，**"


@pytest.mark.asyncio
async def test_agent_wraps_plain_text_skill_answer(tmp_path):
    from app.agents.project_expert.agent import ProjectExpertAgent

    ctx = _make_ctx(tmp_path)

    with _patch_agent_common(_fake_query_plain_skill_answer), \
        patch("app.agents.anthropic_client.build_options", return_value=MagicMock()), \
        patch(
            "app.services.skills_service.materialize_enabled_skills",
            return_value=["skill-verifier"],
        ), \
        patch(
            "app.services.skills_service.enabled_skill_overviews",
            return_value=[{"name": "skill-verifier", "description": ""}],
        ), \
        patch("app.agents.log_analysis.mcp_tools.get_mcp_server", return_value=MagicMock()):
        result = await ProjectExpertAgent().run(ctx)

    assert result["status"] == "ok"
    assert result["question_type"] == "qa"
    assert result["answer"] == "TURQUOISE-MONGOOSE-9"
    assert result["summary"] == "TURQUOISE-MONGOOSE-9"
    assert result["parse_warning"] == "plain_text_skill_answer_wrapped"
    assert result["loaded_skills"] == ["skill-verifier"]


@pytest.mark.asyncio
async def test_service_requires_project_repo_for_new_session():
    from app.services.project_expert_chat_service import ProjectExpertChatService

    service = ProjectExpertChatService()
    events = []
    async for chunk in service.stream(
        message="鉴权在哪里？",
        session_id="session-required",
        history_json=None,
        remember=False,
        project_repo_id=None,
        db=None,
        user=None,
    ):
        event = _decode_sse_event(chunk)
        events.append(event)
        if event.get("event") == "error":
            break

    assert events[-1]["event"] == "error"
    assert events[-1]["reason"] == "project_repo_required"
    assert "session-required" not in service._jobs


@pytest.mark.asyncio
async def test_service_reuses_workspace_and_emits_notice_on_project_switch(monkeypatch, tmp_path):
    from app.services.project_expert_chat_service import ProjectExpertChatService

    ctx = _make_ctx(tmp_path)
    meta = {
        "session_id": "session-followup",
        "task_id": ctx.task_id,
        "temp_dir": ctx.temp_dir,
        "repo_dir": ctx.repo_dir,
        "task_json_path": ctx.task_json_path,
        "project_repo_id": 1,
        "project_code": "foo",
        "project_name": "Foo Service",
    }

    class FastAgent:
        def run_sync(self, seen_ctx, _cancel_event=None, _trace_emitter=None):
            assert seen_ctx.temp_dir == ctx.temp_dir
            return {
                "engine": "claude-agent-sdk",
                "model": "fake-model",
                "schema_version": 3,
                "status": "ok",
                "error_kind": None,
                "question_type": "qa",
                "answer": "继续基于已克隆代码回答。",
                "summary": "ok",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                "tool_trace": [],
                "trace_events": [],
                "trace_summary": {},
                "raw": "ok",
                "duration_seconds": 0.0,
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            }

    service = ProjectExpertChatService()
    monkeypatch.setattr(service, "_load_context", lambda *_a, **_kw: (ctx, meta))
    monkeypatch.setattr(service, "_save_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_touch_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_persist_exchange", lambda *_a, **_kw: None)

    async def fake_history_hint(**_kwargs):
        return ""

    monkeypatch.setattr(service, "_build_history_hint", fake_history_hint)
    monkeypatch.setattr(
        "app.services.project_expert_chat_service.ProjectExpertAgent",
        FastAgent,
    )
    monkeypatch.setattr(
        "app.services.project_expert_chat_service._AGENT_PROGRESS_INTERVAL_SECONDS",
        0.01,
    )

    events = []
    async for chunk in service.stream(
        message="继续看鉴权",
        session_id="session-followup",
        history_json=None,
        remember=False,
        project_repo_id=2,
        db=None,
        user=None,
    ):
        event = _decode_sse_event(chunk)
        events.append(event)
        if event.get("event") == "done":
            break

    notices = [
        event for event in events
        if event.get("event") == "agent_trace" and event.get("type") == "system_notice"
    ]
    assert any(event.get("kind") == "project_switch_ignored" for event in notices)
    assert events[-1]["event"] == "done"
    assert service.get_status("session-followup")["status"] == "done"


@pytest.mark.asyncio
async def test_service_cancel_and_result_polling(monkeypatch, tmp_path):
    from app.services.project_expert_chat_service import ProjectExpertChatService

    ctx = _make_ctx(tmp_path)
    meta = {
        "session_id": "session-cancel",
        "task_id": ctx.task_id,
        "temp_dir": ctx.temp_dir,
        "repo_dir": ctx.repo_dir,
        "task_json_path": ctx.task_json_path,
        "project_repo_id": 1,
    }
    captured = {}

    class CancellableAgent:
        def run_sync(self, _ctx, cancel_event=None, _trace_emitter=None):
            captured["event"] = cancel_event
            for _ in range(200):
                if cancel_event is not None and cancel_event.is_set():
                    break
                time.sleep(0.01)
            return {
                "engine": "claude-agent-sdk",
                "model": "fake-model",
                "schema_version": 3,
                "status": "cancelled",
                "error_kind": "cancelled",
                "question_type": "other",
                "answer": "本轮分析已被用户取消。",
                "summary": "cancelled",
                "severity": "info",
                "root_cause_hypotheses": [],
                "recommended_actions": [],
                "related_keywords": [],
                "tool_trace": [],
                "trace_events": [],
                "trace_summary": {},
                "raw": "cancelled",
                "duration_seconds": 0.0,
                "token_usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            }

    service = ProjectExpertChatService()
    monkeypatch.setattr(service, "_load_context", lambda *_a, **_kw: (ctx, meta))
    monkeypatch.setattr(service, "_save_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_touch_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(service, "_persist_exchange", lambda *_a, **_kw: None)

    async def fake_history_hint(**_kwargs):
        return ""

    monkeypatch.setattr(service, "_build_history_hint", fake_history_hint)
    monkeypatch.setattr(
        "app.services.project_expert_chat_service.ProjectExpertAgent",
        CancellableAgent,
    )

    stream = service.stream(
        message="继续看鉴权",
        session_id="session-cancel",
        history_json=None,
        remember=False,
        project_repo_id=1,
        db=None,
        user=None,
    )
    events = []

    async def consume():
        async for chunk in stream:
            event = _decode_sse_event(chunk)
            events.append(event)
            if event.get("event") == "done":
                break

    consumer = asyncio.create_task(consume())
    for _ in range(50):
        if captured.get("event") is not None:
            break
        await asyncio.sleep(0.02)

    assert service.get_status("session-cancel")["status"] == "running"
    assert service.cancel("session-cancel") is True
    await asyncio.wait_for(consumer, timeout=5)

    status = service.get_status("session-cancel")
    assert status["status"] == "done"
    assert status["cancel_requested"] is True
    assert status["result"]["status"] == "cancelled"
    assert events[-1]["event"] == "done"


def test_project_expert_stream_endpoint_contract_has_no_file_parameter():
    from app.api.ai_chat import project_expert_stream_endpoint

    signature = inspect.signature(project_expert_stream_endpoint)
    assert "file" not in signature.parameters
    assert {"message", "session_id", "history", "remember", "project_repo_id"}.issubset(
        signature.parameters
    )
