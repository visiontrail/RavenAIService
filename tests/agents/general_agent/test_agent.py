"""Unit tests for app/agents/general_agent/agent.py — GeneralAgent.run_stream / run."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.agents.general_agent.agent import (
    GeneralAgent,
    GeneralAgentContext,
    VALID_SUGGESTED_AGENTS,
    _extract_suggested_agent,
    _format_history_block,
    _resolve_small_fast_model,
)
from app.agents.general_agent.prompts import get_prompts


# ─────────────────────── Fake SDK messages ─────────────────────────


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


class _FakeToolUseBlock:
    def __init__(self, name: str, tool_input: Dict[str, Any], block_id: str):
        self.name = name
        self.input = tool_input
        self.id = block_id


class _FakeToolResultBlock:
    def __init__(self, tool_use_id: str, text: str):
        self.tool_use_id = tool_use_id
        self.content = [{"type": "text", "text": text}]
        self.is_error = False


class _FakeContentMessage:
    def __init__(self, *blocks: Any):
        self.content = list(blocks)


class _FakeResultMessage:
    content = None

    def __init__(self, result: str):
        self.result = result


# ─────────────────────── Helpers ─────────────────────────────────


def _fake_query_factory(answer_text: str):
    async def _q(*, prompt, options):  # noqa: ARG001
        yield _FakeAssistantMessage(answer_text)

    return _q


def _fake_query_turn_limit_factory(partial_text: str):
    """Yield some text, then raise the SDK's max-turns error (recoverable)."""

    async def _q(*, prompt, options):  # noqa: ARG001
        if partial_text:
            yield _FakeAssistantMessage(partial_text)
        raise Exception(
            "Claude Code returned an error result: Reached maximum number of turns (4)"
        )

    return _q


# ─────────────────────── _format_history_block ────────────────────


class TestFormatHistoryBlock:
    def test_empty_history(self):
        assert _format_history_block([], 10) == ""

    def test_role_normalization(self):
        out = _format_history_block(
            [
                {"role": "user", "content": "hi"},
                {"role": "AI", "content": "hello"},
            ],
            10,
        )
        assert "[user] hi" in out
        assert "[assistant] hello" in out


# ─────────────────────── _resolve_small_fast_model ────────────────


def test_resolve_small_fast_model_from_settings(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "my-model")
    assert _resolve_small_fast_model() == "my-model"


def test_resolve_small_fast_model_from_provider(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", None)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    model = _resolve_small_fast_model()
    assert model == "claude-haiku-4-5-20251001"


# ─────────────────────── GeneralAgent.run_stream ──────────────────


@pytest.mark.asyncio
async def test_run_stream_happy_path(monkeypatch):
    """GeneralAgent emits run_start + run_complete with the answer text."""
    fake_query = _fake_query_factory("你好，我是 Raven AI 助手")

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(
        session_id="sess-general-1",
        user_message="这个系统怎么用？",
    )

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    types = [e["type"] for e in events]
    assert types[0] == "run_start"
    assert types[-1] == "run_complete"
    assert events[0]["model"] == "test-model"
    assert "Raven AI" in events[-1]["final_text"]


@pytest.mark.asyncio
async def test_run_returns_tuple(monkeypatch):
    """GeneralAgent.run() returns (events, final_text, model)."""
    fake_query = _fake_query_factory("回答内容")

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(
        session_id="sess-general-2",
        user_message="帮助",
    )

    events, final_text, model = await GeneralAgent().run(ctx)
    assert final_text == "回答内容"
    assert model == "test-model"
    assert events[0]["type"] == "run_start"
    assert events[-1]["type"] == "run_complete"
    assert any(event["type"] == "thinking_delta" for event in events)


@pytest.mark.asyncio
async def test_run_stream_recovers_from_turn_limit(monkeypatch):
    """达到最大轮次时不应整体失败，应回退到已产出的文本。"""
    fake_query = _fake_query_turn_limit_factory("根据已了解的信息，部分回答如下…")

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(session_id="sess-general-3", user_message="一个技术问题")

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "error" not in types
    assert types[-1] == "run_complete"
    assert "部分回答" in events[-1]["final_text"]


@pytest.mark.asyncio
async def test_run_stream_turn_limit_uses_fallback_when_empty(monkeypatch):
    """达到最大轮次且无有效文本时，使用兜底引导回答。"""
    fake_query = _fake_query_turn_limit_factory("")

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(session_id="sess-general-4", user_message="不相关的通用问题")

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    types = [e["type"] for e in events]
    assert "error" not in types
    assert types[-1] == "run_complete"
    final = events[-1]["final_text"]
    assert "系统使用助手" in final
    assert "日志分析" in final


@pytest.mark.asyncio
async def test_system_prompt_contains_key_guidance():
    """The system prompt mentions Raven AI, all four specialist agents, and the marker."""
    system_prompt, _ = get_prompts("zh")
    assert "Raven AI" in system_prompt
    assert "设备操作" in system_prompt
    assert "日志分析" in system_prompt
    assert "配置管理员" in system_prompt
    assert "项目专家" in system_prompt
    # The structured marker contract must be described to the model.
    assert "SUGGESTED_AGENT" in system_prompt
    assert "mcp__project_repo__discover_projects" in system_prompt
    assert "当前系统还没有适合回答这个问题的项目" in system_prompt
    for key in VALID_SUGGESTED_AGENTS:
        assert key in system_prompt


@pytest.mark.asyncio
async def test_general_agent_allows_only_safe_project_discovery(monkeypatch):
    fake_query = _fake_query_factory("请使用项目专家。\n[[SUGGESTED_AGENT:project_expert]]")
    build_options = MagicMock(return_value=MagicMock())
    mcp_server = MagicMock()

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    with patch("app.agents.anthropic_client.build_options", build_options), patch(
        "app.agents.log_analysis.mcp_tools.get_project_discovery_mcp_server",
        return_value=mcp_server,
    ):
        async for _ in GeneralAgent().run_stream(
            GeneralAgentContext(session_id="catalog", user_message="foo 项目的鉴权在哪？")
        ):
            pass

    kwargs = build_options.call_args.kwargs
    assert kwargs["allowed_tools"] == ["mcp__project_repo__discover_projects"]
    assert kwargs["mcp_servers"] == {"project_repo": mcp_server}
    assert "mcp__project_repo__lookup_project_repo" not in kwargs["allowed_tools"]
    assert all(tool not in kwargs["allowed_tools"] for tool in ("Bash", "Read", "Grep"))


@pytest.mark.asyncio
async def test_general_agent_projects_tool_loop_into_trace(monkeypatch):
    async def fake_query(*, prompt, options):  # noqa: ARG001
        yield _FakeContentMessage(
            _FakeToolUseBlock(
                "mcp__project_repo__discover_projects",
                {"query": "foo"},
                "tool-1",
            )
        )
        yield _FakeContentMessage(
            _FakeToolResultBlock(
                "tool-1",
                '{"projects":[{"project_code":"foo"}]}',
            )
        )
        yield _FakeResultMessage(
            "请使用项目专家并选择 foo。\n[[SUGGESTED_AGENT:project_expert]]"
        )

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "small-model")

    events = [
        event
        async for event in GeneralAgent().run_stream(
            GeneralAgentContext(session_id="loop", user_message="foo 项目怎么改？")
        )
    ]

    step_start = next(event for event in events if event["type"] == "step_start")
    step_end = next(event for event in events if event["type"] == "step_end")
    assert step_start["tool_name"] == "mcp__project_repo__discover_projects"
    assert step_end["step_id"] == step_start["step_id"]
    assert events[-1]["suggested_agent_type"] == "project_expert"
    assert events[-1]["final_text"] == "请使用项目专家并选择 foo。"


@pytest.mark.asyncio
async def test_general_agent_materializes_agent_skills_without_project(monkeypatch):
    fake_query = _fake_query_factory("系统使用说明\n[[SUGGESTED_AGENT:none]]")
    build_options = MagicMock(return_value=MagicMock())
    materialize = MagicMock(return_value=["routing_helper"])
    overviews = MagicMock(
        return_value=[{"name": "routing_helper", "description": "路由规则"}]
    )

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "small-model")

    with patch("app.agents.anthropic_client.build_options", build_options), patch(
        "app.services.skills_service.materialize_enabled_skills", materialize
    ), patch(
        "app.services.skills_service.enabled_skill_overviews", overviews
    ):
        events = [
            event
            async for event in GeneralAgent().run_stream(
                GeneralAgentContext(session_id="skills", user_message="怎么用？")
            )
        ]

    materialize.assert_called_once()
    assert materialize.call_args.args[0] == "general_agent"
    assert materialize.call_args.kwargs.get("project_code") is None
    kwargs = build_options.call_args.kwargs
    assert kwargs["model"] == "small-model"
    assert kwargs["allowed_tools"] == [
        "mcp__project_repo__discover_projects",
        "Skill",
    ]
    assert kwargs["setting_sources"] == ["project"]
    assert events[0]["loaded_skills"] == ["routing_helper"]
    assert events[-1]["loaded_skills"] == ["routing_helper"]


def test_general_agent_never_falls_back_to_primary_model(monkeypatch):
    from app.agents.anthropic_client import AnthropicConfigurationError

    monkeypatch.setattr("app.config.settings.anthropic_provider", "custom")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", None)
    monkeypatch.setattr("app.config.settings.anthropic_model", "large-primary-model")

    with pytest.raises(AnthropicConfigurationError, match="refusing to use the primary"):
        _resolve_small_fast_model()


def test_general_agent_is_not_project_scoped():
    from app.services.project_prompt_service import PROJECT_AGENT_KEYS
    from app.services.skills_service import SUPPORTED_AGENTS

    assert "general_agent" in SUPPORTED_AGENTS
    assert "general_agent" not in PROJECT_AGENT_KEYS


# ─────────────────────── _extract_suggested_agent ─────────────────


class TestExtractSuggestedAgent:
    def test_trailing_marker_parsed_and_stripped(self):
        text = "该需求需要使用「日志分析」，请先在上方选择。\n[[SUGGESTED_AGENT:log_analysis]]"
        clean, suggested = _extract_suggested_agent(text)
        assert suggested == "log_analysis"
        assert "SUGGESTED_AGENT" not in clean
        assert clean.endswith("请先在上方选择。")

    def test_none_marker_yields_no_suggestion(self):
        clean, suggested = _extract_suggested_agent("系统使用说明……\n[[SUGGESTED_AGENT:none]]")
        assert suggested is None
        assert "SUGGESTED_AGENT" not in clean

    def test_missing_marker_safe(self):
        clean, suggested = _extract_suggested_agent("没有标记的普通回答")
        assert suggested is None
        assert clean == "没有标记的普通回答"

    def test_illegal_key_safe(self):
        clean, suggested = _extract_suggested_agent("答案\n[[SUGGESTED_AGENT:banana]]")
        assert suggested is None
        assert "SUGGESTED_AGENT" not in clean

    def test_case_insensitive_and_whitespace(self):
        clean, suggested = _extract_suggested_agent("答案 [[ suggested_agent : Device ]]")
        assert suggested == "device"
        assert "suggested_agent" not in clean.lower()

    def test_multiple_markers_all_stripped_last_wins(self):
        text = "x[[SUGGESTED_AGENT:device]]y\n[[SUGGESTED_AGENT:package_search]]"
        clean, suggested = _extract_suggested_agent(text)
        assert suggested == "package_search"
        assert "SUGGESTED_AGENT" not in clean

    def test_empty_text(self):
        clean, suggested = _extract_suggested_agent("")
        assert clean == ""
        assert suggested is None


# ─────────────────────── suggestion propagation ───────────────────


@pytest.mark.asyncio
async def test_run_stream_emits_suggested_agent(monkeypatch):
    """A B-class answer with a marker surfaces suggested_agent_type and a clean body."""
    fake_query = _fake_query_factory(
        "该需求需要使用「配置管理员」，请先在上方选择对应 Agent。\n[[SUGGESTED_AGENT:package_search]]"
    )
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(session_id="sess-suggest-1", user_message="查一下 xxx 包最新版本")

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    complete = events[-1]
    assert complete["type"] == "run_complete"
    assert complete["suggested_agent_type"] == "package_search"
    assert "SUGGESTED_AGENT" not in complete["final_text"]


@pytest.mark.asyncio
async def test_run_stream_none_suggestion_for_system_question(monkeypatch):
    """An A-class answer (with none marker) yields suggested_agent_type=None."""
    fake_query = _fake_query_factory("你可以在左侧打开日志分析功能……\n[[SUGGESTED_AGENT:none]]")
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(session_id="sess-suggest-2", user_message="日志分析怎么用？")

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    complete = events[-1]
    assert complete["suggested_agent_type"] is None
    assert "SUGGESTED_AGENT" not in complete["final_text"]


@pytest.mark.asyncio
async def test_fallback_clears_suggestion(monkeypatch):
    """When the model produces no usable text, fall back with no suggestion."""
    fake_query = _fake_query_turn_limit_factory("")
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr("app.config.settings.anthropic_small_fast_model", "test-model")

    ctx = GeneralAgentContext(session_id="sess-suggest-3", user_message="不相关问题")

    events: List[Dict[str, Any]] = []
    async for ev in GeneralAgent().run_stream(ctx):
        events.append(ev)

    complete = events[-1]
    assert complete["suggested_agent_type"] is None
    assert "项目专家" in complete["final_text"]


# ─────────────────────── service-layer propagation ────────────────


@pytest.mark.asyncio
async def test_ai_chat_service_returns_suggested_agent(monkeypatch):
    """ChatResponse.suggested_agent_type is populated from the run_complete event."""
    from app.models.chat import ChatRequest
    from app.services.ai_chat_service import ai_chat_service

    async def fake_run(self, ctx):  # noqa: ANN001, ARG001
        events = [
            {"type": "run_start", "model": "m"},
            {
                "type": "run_complete",
                "final_text": "请先选择日志分析",
                "suggested_agent_type": "log_analysis",
            },
        ]
        return events, "请先选择日志分析", "m"

    monkeypatch.setattr(
        "app.agents.general_agent.agent.GeneralAgent.run", fake_run
    )

    resp = await ai_chat_service.chat(
        ChatRequest(message="分析这份日志为什么报错", remember=False),
        db=None,
        user=None,
    )
    assert resp.suggested_agent_type == "log_analysis"


@pytest.mark.asyncio
async def test_chat_run_service_general_done_carries_suggestion(monkeypatch):
    """The general run's done frame + snapshot carry suggested_agent_type."""
    import time

    from app.services.chat_run_service import (
        ChatRunJob,
        RUN_STATUS_RUNNING,
        chat_run_service,
    )

    async def fake_stream(self, ctx):  # noqa: ANN001, ARG001
        yield {"type": "run_start", "model": "m"}
        yield {
            "type": "run_complete",
            "final_text": "请先选择项目专家",
            "suggested_agent_type": "project_expert",
        }

    monkeypatch.setattr(
        "app.agents.general_agent.agent.GeneralAgent.run_stream", fake_stream
    )
    # Skip terminal DB persistence.
    monkeypatch.setattr(
        "app.models.database.db_manager.session_factory", None, raising=False
    )

    job = ChatRunJob(
        run_id="rid-suggest",
        session_id="sid-suggest",
        user_id=None,
        owner_scope="anon:test",
        agent_kind="general",
        status=RUN_STATUS_RUNNING,
        started_at=time.monotonic(),
        user_message="这个项目的鉴权在哪里实现",
        request_payload={},
    )
    ctx_kwargs = {
        "session_id": "sid-suggest",
        "user_message": "这个项目的鉴权在哪里实现",
        "history": [],
        "system_prompt_override": None,
        "run_id": "rid-suggest",
        "owner_scope": "anon:test",
        "remember": False,
    }

    await chat_run_service._run_general_job(job, ctx_kwargs)  # noqa: SLF001

    assert job.suggested_agent_type == "project_expert"
    done_frames = [e for e in job.events if e.get("event") == "done"]
    assert done_frames and done_frames[-1]["suggested_agent_type"] == "project_expert"
    snapshot = chat_run_service._snapshot_payload(job)  # noqa: SLF001
    assert snapshot["suggested_agent_type"] == "project_expert"
