"""Unit tests for app/agents/general_agent/agent.py — GeneralAgent.run_stream / run."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.agents.general_agent.agent import (
    GeneralAgent,
    GeneralAgentContext,
    SYSTEM_PROMPT,
    _format_history_block,
    _resolve_small_fast_model,
)


# ─────────────────────── Fake SDK messages ─────────────────────────


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


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
    assert len(events) == 2


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
    """The system prompt mentions Raven AI and restricts scope."""
    assert "Raven AI" in SYSTEM_PROMPT
    assert "设备操作" in SYSTEM_PROMPT
    assert "日志分析" in SYSTEM_PROMPT
