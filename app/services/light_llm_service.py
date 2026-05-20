"""
Lightweight LLM helper.

Provides a shared ChatOpenAI client tuned for short, low-latency tasks
(such as immediate conversation summaries / session titles).

The model is resolved from runtime settings (admin-overridable) with a
fallback chain: runtime override → settings.llm_light_* → main LLM defaults.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from app.services import runtime_settings_service

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHED_CLIENT: Optional[ChatOpenAI] = None
_CACHED_SIGNATURE: Optional[tuple] = None


def reset_cached_client() -> None:
    """Drop the cached LLM so the next call rebuilds with fresh settings."""
    global _CACHED_CLIENT, _CACHED_SIGNATURE
    with _LOCK:
        _CACHED_CLIENT = None
        _CACHED_SIGNATURE = None


def _build_client(config: dict) -> ChatOpenAI:
    api_key = config.get("api_key")
    base_url = config.get("base_url")
    model = config.get("model")
    if not api_key or not base_url or not model:
        raise RuntimeError(
            "轻量级模型未配置：缺少 model/base_url/api_key（请检查 settings 或运行期配置）"
        )

    # langchain_openai picks up these envs for some sub-clients; keep them in sync.
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_BASE"] = base_url

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=float(config.get("temperature", 0.2)),
        streaming=False,
        timeout=20,
    )


def get_light_llm() -> ChatOpenAI:
    """Return a cached lightweight LLM client. Rebuilt when settings change."""
    global _CACHED_CLIENT, _CACHED_SIGNATURE
    config = runtime_settings_service.get_effective_light_config()
    signature = (
        config.get("model"),
        config.get("base_url"),
        config.get("api_key"),
        config.get("temperature"),
    )
    with _LOCK:
        if _CACHED_CLIENT is not None and _CACHED_SIGNATURE == signature:
            return _CACHED_CLIENT
        client = _build_client(config)
        _CACHED_CLIENT = client
        _CACHED_SIGNATURE = signature
        logger.info("light_llm: using model %s", config.get("model"))
        return client


def _extract_text(result: Any) -> str:
    raw = getattr(result, "content", result)
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(raw)


_SUMMARY_PROMPT = (
    "你是会话标题生成助手。请根据下面用户输入的内容，生成一个简短的中文摘要标题，"
    "长度不超过 {max_length} 个字，必须概括用户的核心诉求或问题。\n"
    "要求：\n"
    "- 只输出标题文本，不要解释、不要引号、不要标点符号结尾、不要 emoji、不要换行。\n"
    "- 不要复述完整问题，使用名词短语或动宾短语。\n\n"
    "用户内容：\n{user_content}"
)


async def summarize_user_message(user_content: str, max_length: int = 16) -> str:
    """Generate a short Chinese title for the given user message.

    Falls back to a truncated form of the message when the LLM call fails.
    """
    cleaned_input = " ".join((user_content or "").strip().split())
    fallback = cleaned_input[:max_length] if cleaned_input else "新对话"

    if not cleaned_input:
        return fallback

    try:
        llm = get_light_llm()
        prompt = _SUMMARY_PROMPT.format(
            user_content=cleaned_input[:1200],
            max_length=max_length,
        )
        result = await llm.ainvoke(prompt)
        text = _extract_text(result)
        normalized = " ".join(text.strip().split())
        normalized = normalized.split("\n", 1)[0].strip().strip("“”\"'`：:。.")
        if not normalized:
            return fallback
        return normalized[:max_length]
    except Exception as exc:  # noqa: BLE001
        logger.warning("light_llm: 生成摘要失败，使用回退: %s", exc)
        return fallback
