"""
Anthropic 标准 LLM 配置层与 ClaudeAgentOptions 构建入口。

支持多个上游服务商（provider），首发 `anthropic` 与 `deepseek` 两个 profile。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────── Exceptions ────────────────────────────────

class AnthropicConfigurationError(Exception):
    """Anthropic 配置不完整或非法时抛出。"""


class ProviderCapabilityError(Exception):
    """调用方请求的特性在当前 provider 下不被支持时抛出。"""


# ─────────────────────── Provider Profile ──────────────────────────

@dataclass(frozen=True)
class ProviderProfile:
    name: str
    default_base_url: str
    default_model: str
    default_small_fast_model: Optional[str]
    supports_image_input: bool
    supports_document_input: bool
    supports_mcp_server_tools: bool
    thinking_budget_tokens_effective: bool
    disable_parallel_tool_use_effective: bool
    notes: str = ""


PROVIDER_PROFILES: Dict[str, ProviderProfile] = {
    "anthropic": ProviderProfile(
        name="anthropic",
        default_base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-6",
        default_small_fast_model="claude-haiku-4-5-20251001",
        supports_image_input=True,
        supports_document_input=True,
        supports_mcp_server_tools=True,
        thinking_budget_tokens_effective=True,
        disable_parallel_tool_use_effective=True,
        notes="Anthropic 官方端点，能力全开",
    ),
    "deepseek": ProviderProfile(
        name="deepseek",
        default_base_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-v4-pro",
        default_small_fast_model="deepseek-v4-flash",
        supports_image_input=False,
        supports_document_input=False,
        supports_mcp_server_tools=False,
        thinking_budget_tokens_effective=False,
        disable_parallel_tool_use_effective=False,
        notes="DeepSeek Anthropic 兼容端点；不支持图像/文档输入与 thinking budget",
    ),
}


# ─────────────────────── Public API ────────────────────────────────

def assert_anthropic_configured() -> None:
    """校验 Anthropic 配置完整性，不完整时抛 AnthropicConfigurationError。"""
    from app.config import settings

    if not settings.anthropic_api_key:
        raise AnthropicConfigurationError(
            "anthropic_api_key is not configured. "
            "Set ANTHROPIC_API_KEY environment variable."
        )

    if settings.anthropic_provider == "custom":
        if not settings.anthropic_base_url:
            raise AnthropicConfigurationError(
                "anthropic_base_url is required when anthropic_provider='custom'. "
                "Set ANTHROPIC_BASE_URL environment variable."
            )
        if not settings.anthropic_model:
            raise AnthropicConfigurationError(
                "anthropic_model is required when anthropic_provider='custom'. "
                "Set ANTHROPIC_MODEL environment variable."
            )


def build_options(
    *,
    system_prompt: str,
    allowed_tools: List[str],
    cwd: str,
    max_turns: Optional[int] = None,
    permission_mode: Optional[str] = None,
    add_dirs: Optional[List[str]] = None,
    requires_image_input: bool = False,
    requires_document_input: bool = False,
    thinking_budget_tokens: Optional[int] = None,
    mcp_servers: Optional[Dict[str, Any]] = None,
    setting_sources: Optional[List[str]] = None,
) -> Any:
    """构建 ClaudeAgentOptions，按 caller override → Settings → provider profile 优先级解析参数。

    返回 ClaudeAgentOptions 实例。
    """
    from app.config import settings

    assert_anthropic_configured()

    provider_name = settings.anthropic_provider
    profile = PROVIDER_PROFILES.get(provider_name)
    # custom provider 不在注册表中，使用最严格的能力矩阵
    if profile is None:
        profile = ProviderProfile(
            name="custom",
            default_base_url=settings.anthropic_base_url or "",
            default_model=settings.anthropic_model or "",
            default_small_fast_model=settings.anthropic_small_fast_model,
            supports_image_input=False,
            supports_document_input=False,
            supports_mcp_server_tools=False,
            thinking_budget_tokens_effective=False,
            disable_parallel_tool_use_effective=False,
        )

    # 能力检查
    if requires_image_input and not profile.supports_image_input:
        raise ProviderCapabilityError(
            f"Provider '{provider_name}' does not support image input "
            f"(supports_image_input=False). Switch to a capable provider."
        )
    if requires_document_input and not profile.supports_document_input:
        raise ProviderCapabilityError(
            f"Provider '{provider_name}' does not support document input "
            f"(supports_document_input=False). Switch to a capable provider."
        )

    # 解析 effective 值：caller override → Settings → profile default
    effective_model = (
        settings.anthropic_model
        or profile.default_model
    )
    effective_base_url = (
        settings.anthropic_base_url
        or profile.default_base_url
    )
    effective_max_turns = max_turns if max_turns is not None else settings.anthropic_max_turns
    effective_permission_mode = permission_mode or settings.anthropic_permission_mode

    # thinking_budget_tokens 在不支持的 provider 下静默丢弃
    effective_thinking: Optional[Dict[str, Any]] = None
    if thinking_budget_tokens is not None:
        if not profile.thinking_budget_tokens_effective:
            logger.warning(
                "thinking_budget_tokens=%d is ignored for provider='%s' "
                "(thinking_budget_tokens_effective=False). "
                "The parameter has been dropped.",
                thinking_budget_tokens,
                provider_name,
            )
        else:
            effective_thinking = {"budget_tokens": thinking_budget_tokens}

    # MCP servers 能力检查（不支持的 provider 不注入）
    effective_mcp_servers: Dict[str, Any] = {}
    if mcp_servers:
        if not profile.supports_mcp_server_tools:
            logger.warning(
                "Provider '%s' does not support MCP server tools "
                "(supports_mcp_server_tools=False). "
                "MCP servers will be registered but may not function correctly.",
                provider_name,
            )
        effective_mcp_servers = mcp_servers

    logger.info(
        "Building ClaudeAgentOptions: provider=%s model=%s base_url=%s max_turns=%d",
        provider_name,
        effective_model,
        effective_base_url,
        effective_max_turns,
    )

    # 延迟导入以避免循环依赖，并在 SDK 未安装时给出清晰错误
    try:
        from claude_agent_sdk import ClaudeAgentOptions
    except ImportError as exc:
        raise AnthropicConfigurationError(
            "claude-agent-sdk is not installed. "
            "Run: pip install claude-agent-sdk>=0.1"
        ) from exc

    options_kwargs: Dict[str, Any] = {
        "model": effective_model,
        "system_prompt": system_prompt,
        "allowed_tools": allowed_tools,
        "cwd": cwd,
        "max_turns": effective_max_turns,
        "permission_mode": effective_permission_mode,
        "env": {
            "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            "ANTHROPIC_BASE_URL": effective_base_url,
        },
    }

    if add_dirs:
        options_kwargs["add_dirs"] = add_dirs

    if effective_thinking:
        options_kwargs["thinking"] = effective_thinking

    if effective_mcp_servers:
        options_kwargs["mcp_servers"] = effective_mcp_servers

    if setting_sources:
        options_kwargs["setting_sources"] = list(setting_sources)

    return ClaudeAgentOptions(**options_kwargs)
