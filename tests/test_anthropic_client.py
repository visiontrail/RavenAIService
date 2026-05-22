"""Unit tests for app/agents/anthropic_client.py."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────── Fixtures ──────────────────────────────────

@pytest.fixture
def base_settings():
    """Return a mock settings object with safe defaults."""
    s = MagicMock()
    s.anthropic_api_key = "sk-test"
    s.anthropic_provider = "deepseek"
    s.anthropic_base_url = None
    s.anthropic_model = None
    s.anthropic_small_fast_model = None
    s.anthropic_max_turns = 30
    s.anthropic_permission_mode = "acceptEdits"
    return s


@dataclass
class FakeClaudeAgentOptions:
    model: str
    system_prompt: str
    allowed_tools: List[str]
    cwd: str
    max_turns: int
    permission_mode: str
    env: Dict[str, Any]
    thinking: Optional[Dict[str, Any]] = None
    mcp_servers: Optional[Dict[str, Any]] = None
    add_dirs: Optional[List[str]] = None
    setting_sources: Optional[List[str]] = None
    can_use_tool: Optional[Any] = None
    hooks: Optional[Dict[str, Any]] = None
    max_tokens: Optional[int] = None
    request_timeout_seconds: Optional[int] = None


def _make_fake_sdk():
    """Return a fake claude_agent_sdk module."""
    sdk = MagicMock()
    sdk.ClaudeAgentOptions = FakeClaudeAgentOptions
    return sdk


# ─────────────────────── Tests ─────────────────────────────────────

class TestProviderProfiles:
    def test_deepseek_profile_defaults(self):
        from app.agents.anthropic_client import PROVIDER_PROFILES

        p = PROVIDER_PROFILES["deepseek"]
        assert p.default_base_url == "https://api.deepseek.com/anthropic"
        assert p.default_model == "deepseek-v4-pro"
        assert p.supports_image_input is False
        assert p.thinking_budget_tokens_effective is False
        # SDK 进程内 MCP server 通过标准 tool_use 暴露，DeepSeek 支持
        assert p.supports_mcp_server_tools is True
        assert p.supports_document_input is False
        assert p.disable_parallel_tool_use_effective is False

    def test_anthropic_profile_defaults(self):
        from app.agents.anthropic_client import PROVIDER_PROFILES

        p = PROVIDER_PROFILES["anthropic"]
        assert p.default_base_url == "https://api.anthropic.com"
        assert p.supports_image_input is True
        assert p.supports_document_input is True
        assert p.thinking_budget_tokens_effective is True


class TestAssertAnthropicConfigured:
    def test_missing_api_key_raises(self, base_settings):
        base_settings.anthropic_api_key = None
        with patch("app.config.settings", base_settings):
            from app.agents.anthropic_client import AnthropicConfigurationError, assert_anthropic_configured

            with pytest.raises(AnthropicConfigurationError, match="anthropic_api_key"):
                assert_anthropic_configured()

    def test_custom_provider_missing_base_url(self, base_settings):
        base_settings.anthropic_provider = "custom"
        base_settings.anthropic_base_url = None
        base_settings.anthropic_model = "some-model"
        with patch("app.config.settings", base_settings):
            from app.agents.anthropic_client import AnthropicConfigurationError, assert_anthropic_configured

            with pytest.raises(AnthropicConfigurationError, match="anthropic_base_url"):
                assert_anthropic_configured()

    def test_custom_provider_missing_model(self, base_settings):
        base_settings.anthropic_provider = "custom"
        base_settings.anthropic_base_url = "https://custom.example.com"
        base_settings.anthropic_model = None
        with patch("app.config.settings", base_settings):
            from app.agents.anthropic_client import AnthropicConfigurationError, assert_anthropic_configured

            with pytest.raises(AnthropicConfigurationError, match="anthropic_model"):
                assert_anthropic_configured()

    def test_valid_deepseek_config_passes(self, base_settings):
        with patch("app.config.settings", base_settings):
            from app.agents.anthropic_client import assert_anthropic_configured

            assert_anthropic_configured()  # should not raise


class TestBuildOptions:
    def _build(self, settings_mock, **kwargs) -> FakeClaudeAgentOptions:
        with patch("app.config.settings", settings_mock), \
             patch.dict("sys.modules", {"claude_agent_sdk": _make_fake_sdk()}):
            # Re-import to pick up patched modules
            import importlib
            import app.agents.anthropic_client as mod
            importlib.reload(mod)
            return mod.build_options(
                system_prompt=kwargs.pop("system_prompt", "test prompt"),
                allowed_tools=kwargs.pop("allowed_tools", ["Bash"]),
                cwd=kwargs.pop("cwd", "/tmp/test"),
                **kwargs,
            )

    def test_deepseek_defaults_applied(self, base_settings):
        opts = self._build(base_settings)
        assert opts.model == "deepseek-v4-pro"
        assert opts.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
        assert opts.env["ANTHROPIC_API_KEY"] == "sk-test"

    def test_caller_max_turns_overrides_settings(self, base_settings):
        opts = self._build(base_settings, max_turns=10)
        assert opts.max_turns == 10

    def test_settings_model_overrides_profile(self, base_settings):
        base_settings.anthropic_model = "deepseek-v4-flash"
        opts = self._build(base_settings)
        assert opts.model == "deepseek-v4-flash"

    def test_image_input_rejected_on_deepseek(self, base_settings):
        with patch("app.config.settings", base_settings), \
             patch.dict("sys.modules", {"claude_agent_sdk": _make_fake_sdk()}):
            import importlib
            import app.agents.anthropic_client as mod
            importlib.reload(mod)
            with pytest.raises(mod.ProviderCapabilityError, match="supports_image_input"):
                mod.build_options(
                    system_prompt="s",
                    allowed_tools=["Read"],
                    cwd="/tmp",
                    requires_image_input=True,
                )

    def test_thinking_budget_dropped_on_deepseek_with_warning(self, base_settings, caplog):
        with caplog.at_level(logging.WARNING):
            opts = self._build(base_settings, thinking_budget_tokens=4096)
        assert not hasattr(opts, "thinking") or opts.thinking is None
        assert "thinking_budget_tokens" in caplog.text or "thinking" in caplog.text.lower()

    def test_effective_model_in_options(self, base_settings):
        opts = self._build(base_settings)
        assert opts.model == "deepseek-v4-pro"

    def test_mcp_servers_and_allowed_tools_passthrough_on_deepseek(self, base_settings):
        # SDK 进程内 MCP server 通过标准 tool_use 协议工作，DeepSeek 支持，
        # 因此不应丢弃 mcp_servers 与 mcp__* 工具名。
        mcp_mock = MagicMock()
        opts = self._build(
            base_settings,
            allowed_tools=["Bash", "mcp__project_repo__lookup_project_repo"],
            mcp_servers={"project_repo": mcp_mock},
        )

        assert opts.mcp_servers == {"project_repo": mcp_mock}
        assert opts.allowed_tools == ["Bash", "mcp__project_repo__lookup_project_repo"]


class TestBuildOptionsExtensions:
    """Tests for the can_use_tool / hooks / model / max_tokens / request_timeout_seconds
    additions introduced for DeviceAgent + lightweight Anthropic routing."""

    def _build(self, settings_mock, **kwargs) -> FakeClaudeAgentOptions:
        with patch("app.config.settings", settings_mock), \
             patch.dict("sys.modules", {"claude_agent_sdk": _make_fake_sdk()}):
            import importlib
            import app.agents.anthropic_client as mod
            importlib.reload(mod)
            return mod.build_options(
                system_prompt=kwargs.pop("system_prompt", "test prompt"),
                allowed_tools=kwargs.pop("allowed_tools", ["Bash"]),
                cwd=kwargs.pop("cwd", "/tmp/test"),
                **kwargs,
            )

    def test_can_use_tool_passthrough(self, base_settings):
        async def my_cb(tool_name, tool_input, context):  # pragma: no cover - identity check
            return {"behavior": "allow"}

        opts = self._build(base_settings, can_use_tool=my_cb)
        assert opts.can_use_tool is my_cb

    def test_hooks_passthrough(self, base_settings):
        matcher = MagicMock()
        opts = self._build(base_settings, hooks={"PostToolUse": [matcher]})
        assert opts.hooks == {"PostToolUse": [matcher]}

    def test_default_no_callback_no_hooks(self, base_settings):
        opts = self._build(base_settings)
        assert opts.can_use_tool is None
        assert opts.hooks is None

    def test_permission_mode_default_with_callback(self, base_settings):
        async def cb(*a, **kw):  # pragma: no cover
            return {"behavior": "allow"}

        opts = self._build(base_settings, permission_mode="default", can_use_tool=cb)
        assert opts.permission_mode == "default"
        assert opts.can_use_tool is cb

    def test_caller_model_overrides_settings(self, base_settings):
        base_settings.anthropic_model = None
        opts = self._build(base_settings, model="deepseek-v4-flash")
        assert opts.model == "deepseek-v4-flash"
        assert opts.env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"

    def test_caller_model_overrides_settings_with_log(self, base_settings, caplog):
        base_settings.anthropic_model = "deepseek-v4-pro"
        with caplog.at_level(logging.INFO):
            opts = self._build(base_settings, model="deepseek-v4-flash")
        assert opts.model == "deepseek-v4-flash"
        assert "overridden by caller" in caplog.text

    def test_omitted_model_falls_back_to_settings(self, base_settings):
        base_settings.anthropic_model = "deepseek-v4-pro"
        opts = self._build(base_settings)
        assert opts.model == "deepseek-v4-pro"

    def test_max_tokens_and_request_timeout_passthrough(self, base_settings):
        opts = self._build(base_settings, max_tokens=1024, request_timeout_seconds=30)
        assert opts.max_tokens == 1024
        assert opts.request_timeout_seconds == 30


class TestConfigValidation:
    def test_invalid_provider_fails_at_validation(self):
        """Settings.anthropic_provider rejects unknown values."""
        from app.config import Settings
        import os

        with patch.dict(os.environ, {"ANTHROPIC_PROVIDER": "foo"}, clear=False):
            with pytest.raises(Exception):
                Settings()

    def test_valid_deepseek_provider_accepted(self):
        from app.config import Settings
        import os

        with patch.dict(os.environ, {"ANTHROPIC_PROVIDER": "deepseek"}, clear=False):
            s = Settings()
            assert s.anthropic_provider == "deepseek"
