"""Lightweight title / summary helper backed by Claude Agent SDK.

Routes short, low-latency requests through the Anthropic small/fast model
(e.g. ``claude-haiku`` / ``deepseek-v4-flash``) by overriding the ``model``
parameter in :func:`app.agents.anthropic_client.build_options`.

Two public entry points:

- :func:`summarize_user_message` — single-input summary (used by
  ``/chat/summarize`` for instant session-title generation).
- :func:`generate_session_title` — user/assistant pair summary
  (used by ``AIChatService`` after a full exchange completes).

Both are best-effort: on any failure (config missing, timeout, SDK error)
they fall back to a sensible truncation of the input.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from typing import Any, Optional

logger = logging.getLogger(__name__)


_SUMMARY_PROMPT = (
    "你是会话标题生成助手。请根据下面用户输入的内容，生成一个简短的中文摘要标题，"
    "长度不超过 {max_length} 个字，必须概括用户的核心诉求或问题。\n"
    "要求：\n"
    "- 只输出标题文本，不要解释、不要引号、不要标点符号结尾、不要 emoji、不要换行。\n"
    "- 不要复述完整问题，使用名词短语或动宾短语。\n\n"
    "用户内容：\n{user_content}"
)


def _resolve_small_fast_model() -> Optional[str]:
    from app.agents.anthropic_client import PROVIDER_PROFILES
    from app.config import settings

    if settings.anthropic_small_fast_model:
        return settings.anthropic_small_fast_model
    profile = PROVIDER_PROFILES.get(settings.anthropic_provider)
    if profile and profile.default_small_fast_model:
        return profile.default_small_fast_model
    return None


def _extract_text_from_messages(messages: list[Any]) -> str:
    """Pick the last assistant text block from a list of SDK messages."""
    out_parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                out_parts.append(text)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                out_parts.append(str(block["text"]))
    return "".join(out_parts)


async def _run_query(prompt: str, *, system_prompt: str = "") -> str:
    """Run one short ``query()`` round with the small/fast model.

    Returns the concatenated assistant text. Raises on failure; callers
    are expected to wrap in a fallback.
    """
    from app.agents.anthropic_client import build_options
    from app.config import settings

    try:
        from claude_agent_sdk import query as sdk_query
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "claude-agent-sdk is required. Install with: pip install claude-agent-sdk>=0.1"
        ) from exc

    model = _resolve_small_fast_model()
    max_tokens = int(getattr(settings, "anthropic_small_fast_max_tokens", 1024))
    timeout_s = int(
        getattr(settings, "anthropic_small_fast_request_timeout_seconds", 30)
    )

    with tempfile.TemporaryDirectory(prefix="title-gen-") as tmpdir:
        options = build_options(
            system_prompt=system_prompt,
            allowed_tools=[],
            cwd=tmpdir,
            max_turns=1,
            permission_mode="bypassPermissions",
            model=model,
            max_tokens=max_tokens,
            request_timeout_seconds=timeout_s,
        )

        async def _drive() -> list[Any]:
            collected: list[Any] = []
            async for message in sdk_query(prompt=prompt, options=options):
                collected.append(message)
            return collected

        messages = await asyncio.wait_for(_drive(), timeout=max(timeout_s + 5, 10))
        return _extract_text_from_messages(messages)


def _normalize_title(raw: str, max_length: int) -> str:
    normalized = " ".join((raw or "").strip().split())
    normalized = normalized.split("\n", 1)[0].strip().strip("“”\"'`：:。.")
    if not normalized:
        return ""
    return normalized[:max_length]


async def summarize_user_message(user_content: str, max_length: int = 16) -> str:
    """Generate a short Chinese title for the given user message.

    Falls back to a truncated form of the message when the LLM call fails.
    """
    cleaned_input = " ".join((user_content or "").strip().split())
    fallback = cleaned_input[:max_length] if cleaned_input else "新对话"

    if not cleaned_input:
        return fallback

    try:
        prompt = _SUMMARY_PROMPT.format(
            user_content=cleaned_input[:1200],
            max_length=max_length,
        )
        raw = await _run_query(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("title_generator: 生成摘要失败，使用回退: %s", exc)
        return fallback

    title = _normalize_title(raw, max_length)
    return title or fallback


async def generate_session_title(
    user_content: str,
    ai_content: str,
    max_length: int = 24,
) -> Optional[str]:
    """Generate a session title from a completed user/assistant exchange.

    Returns ``None`` on failure (callers typically retain the existing
    default title in that case).
    """
    from app.services.prompts_config_service import get_chat_title_prompt_template

    user_clean = " ".join((user_content or "").strip().split())
    ai_clean = " ".join((ai_content or "").strip().split())
    if not user_clean and not ai_clean:
        return None

    try:
        template = get_chat_title_prompt_template()
        prompt = template.format(
            user_content=user_clean[:1200],
            ai_content=ai_clean[:1200],
            max_length=max_length,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("title_generator: 标题提示词渲染失败: %s", exc)
        return None

    try:
        raw = await _run_query(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("title_generator: 生成会话标题失败: %s", exc)
        return None

    title = _normalize_title(raw, max_length)
    return title or None
