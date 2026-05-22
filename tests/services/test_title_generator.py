"""Unit tests for :mod:`app.services.title_generator_service`.

These cover the *fallback* paths — the parts that must not raise when input
is empty, the LLM call fails, or the prompt-config template is missing.
The happy LLM path is exercised end-to-end via the chat integration tests.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import title_generator_service as tg


@pytest.mark.asyncio
async def test_summarize_user_message_empty_input_returns_default():
    """Empty input must yield ``"新对话"`` without invoking the LLM."""
    out = await tg.summarize_user_message("", max_length=16)
    assert out == "新对话"


@pytest.mark.asyncio
async def test_summarize_user_message_whitespace_only_returns_default():
    out = await tg.summarize_user_message("   \n  \t  ", max_length=16)
    assert out == "新对话"


@pytest.mark.asyncio
async def test_summarize_user_message_falls_back_when_llm_fails(monkeypatch):
    """When ``_run_query`` raises, we must return a truncated form of the input
    rather than propagating the exception."""

    async def _boom(prompt, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr(tg, "_run_query", _boom)

    out = await tg.summarize_user_message("这是一条很长的用户输入用于测试摘要回退路径", max_length=8)
    # Falls back to truncated input (first 8 chars).
    assert out == "这是一条很长的用"


@pytest.mark.asyncio
async def test_summarize_user_message_uses_llm_output_when_available(monkeypatch):
    async def _ok(prompt, **kwargs):  # noqa: ARG001
        return "  网络故障排查  "

    monkeypatch.setattr(tg, "_run_query", _ok)

    out = await tg.summarize_user_message("网络一直断连，请帮我排查原因", max_length=16)
    assert out == "网络故障排查"


@pytest.mark.asyncio
async def test_generate_session_title_returns_none_for_empty_pair():
    """Both user and assistant content empty → return None (caller keeps default)."""
    out = await tg.generate_session_title("", "", max_length=16)
    assert out is None


@pytest.mark.asyncio
async def test_generate_session_title_returns_none_when_llm_fails(monkeypatch):
    async def _boom(prompt, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated LLM failure")

    monkeypatch.setattr(tg, "_run_query", _boom)

    out = await tg.generate_session_title("用户提问", "助手回答", max_length=16)
    assert out is None


@pytest.mark.asyncio
async def test_generate_session_title_returns_none_when_prompt_template_missing(monkeypatch):
    """If the YAML title prompt template can't be rendered we must not crash."""

    def _boom():
        raise RuntimeError("prompt_config corrupt")

    monkeypatch.setattr(
        "app.services.prompts_config_service.get_chat_title_prompt_template", _boom
    )

    out = await tg.generate_session_title("用户提问", "助手回答", max_length=16)
    assert out is None


@pytest.mark.asyncio
async def test_generate_session_title_uses_llm_output_when_available(monkeypatch):
    async def _ok(prompt, **kwargs):  # noqa: ARG001
        return "排查网络问题"

    monkeypatch.setattr(tg, "_run_query", _ok)
    # Always return a usable template so we don't depend on prompts_config.yaml
    # contents in the test runner.
    monkeypatch.setattr(
        "app.services.prompts_config_service.get_chat_title_prompt_template",
        lambda: "U:{user_content}\nA:{ai_content}\nN:{max_length}",
    )

    out = await tg.generate_session_title("用户问网络", "助手回答", max_length=16)
    assert out == "排查网络问题"


def test_normalize_title_strips_quotes_and_punctuation():
    """The helper that post-processes LLM output must strip surrounding noise."""
    assert tg._normalize_title('  "排查网络问题。" ', 16) == "排查网络问题"
    # Multi-line input gets flattened (whitespace joined with single space)
    # before the max_length cap is applied.
    assert tg._normalize_title("第一行\n第二行", 16) == "第一行 第二行"
    assert tg._normalize_title("非常非常非常非常长的标题文本", 4) == "非常非常"
    assert tg._normalize_title("", 16) == ""
