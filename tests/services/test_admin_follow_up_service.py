"""Temporary review SDK isolation, bounded read-only access and cancellation."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from app.services import admin_follow_up_service as service


def test_workspace_reader_scopes_paths_and_bounds_output(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "source.txt").write_text("first\nneedle\n" + "x" * 30000)
    outside = tmp_path / "secret"
    outside.write_text("private")
    (root / "escape").symlink_to(outside)
    (root / ".git").mkdir()
    reader = service.WorkspaceReader(root)
    assert len(reader.read("source.txt")) == 24000
    assert reader.search("source.txt", "needle") == "2: needle"
    assert "escape" not in reader.listing(".")
    assert ".git" not in reader.listing(".")
    for path in ("../secret", str(outside), "escape", ".git/config"):
        with pytest.raises(ValueError):
            reader.read(path)


def test_sdk_options_disable_history_builtin_tools_and_hooks(tmp_path, monkeypatch):
    from app.agents import anthropic_client

    options = SimpleNamespace(
        env={"ANTHROPIC_API_KEY": "test"}, resume=None, continue_conversation=False
    )
    monkeypatch.setattr(anthropic_client, "build_options", lambda **kwargs: options)
    result = service.make_temporary_options(tmp_path, "/temporary-config", {}, None)
    assert result.tools == []
    assert result.setting_sources == []
    assert json.loads(result.settings)["disableAllHooks"]
    assert result.strict_mcp_config
    assert result.resume is None and not result.continue_conversation
    assert result.extra_args == {"no-session-persistence": None}
    assert result.env["CLAUDE_CONFIG_DIR"] == "/temporary-config"


def terminal(**changes):
    fields = dict(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="temporary-sdk-id",
        result="Answer",
    )
    return ResultMessage(**(fields | changes))


@pytest.mark.asyncio
async def test_stream_uses_fresh_options_and_removes_temporary_config(
    tmp_path, monkeypatch
):
    from app.agents import routed_query as router

    configs = []
    captured = {}
    monkeypatch.setattr(service, "workspace_server", lambda _: {})

    def options(workspace, config_dir, server, endpoint):
        assert workspace == tmp_path
        configs.append(Path(config_dir))
        assert Path(config_dir).is_dir()
        return "options"

    monkeypatch.setattr(service, "make_temporary_options", options)

    async def query(**kwargs):
        captured.update(kwargs)
        kwargs["make_options"](None)
        yield AssistantMessage(content=[TextBlock(text="Answer")], model="test")
        yield terminal()

    monkeypatch.setattr(router, "routed_query", query)
    events = [
        event
        async for event in service.stream_follow_up(
            service.FollowUpContext(
                tmp_path, [{"role": "user", "content": "Original"}]
            ),
            service.FollowUpRequest(question="Why?"),
        )
    ]
    assert events[-1] == {"type": "done", "answer": "Answer"}
    assert captured["require_mcp"] is True
    assert "Original" in captured["prompt"]
    assert all(not path.exists() for path in configs)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_cancellation_closes_sdk_and_removes_temporary_state(
    tmp_path, monkeypatch
):
    from app.agents import routed_query as router

    closed = asyncio.Event()
    started = asyncio.Event()
    configs = []
    monkeypatch.setattr(service, "workspace_server", lambda _: {})

    def options(workspace, config_dir, *args):
        configs.append(Path(config_dir))

    monkeypatch.setattr(service, "make_temporary_options", options)

    async def query(**kwargs):
        kwargs["make_options"](None)
        try:
            started.set()
            await asyncio.Event().wait()
            yield terminal()
        finally:
            closed.set()

    monkeypatch.setattr(router, "routed_query", query)
    iterator = service.stream_follow_up(
        service.FollowUpContext(tmp_path, []), service.FollowUpRequest(question="Why?")
    )
    task = asyncio.create_task(anext(iterator))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert all(not path.exists() for path in configs)


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [None, terminal(is_error=True), terminal(result="")])
async def test_incomplete_or_failed_model_result_is_not_success(
    tmp_path, monkeypatch, result
):
    from app.agents import routed_query as router

    monkeypatch.setattr(service, "workspace_server", lambda _: {})

    async def query(**kwargs):
        if result:
            yield result

    monkeypatch.setattr(router, "routed_query", query)
    with pytest.raises(RuntimeError):
        _ = [
            event
            async for event in service.stream_follow_up(
                service.FollowUpContext(tmp_path, []),
                service.FollowUpRequest(question="Why?"),
            )
        ]


def test_actual_sdk_command_enforces_isolation(tmp_path):
    from app.agents.anthropic_client import PROVIDER_PROFILES
    from app.services.model_router import EndpointChoice
    from claude_agent_sdk._internal.transport.subprocess_cli import (
        SubprocessCLITransport,
    )

    name, profile = next(
        (name, p)
        for name, p in PROVIDER_PROFILES.items()
        if p.supports_mcp_server_tools
    )
    endpoint = EndpointChoice(
        "primary", name, "http://127.0.0.1:1", "test-only-key", "test", None, profile
    )
    options = service.make_temporary_options(
        tmp_path, str(tmp_path / "config"), {}, endpoint
    )
    options.cli_path = "claude"  # Build argv only; never execute or call a provider.
    argv = SubprocessCLITransport(prompt="fixture", options=options)._build_command()
    assert argv[argv.index("--tools") + 1] == ""
    assert "--setting-sources=" in argv or (
        "--setting-sources" in argv and argv[argv.index("--setting-sources") + 1] == ""
    )
    assert "--no-session-persistence" in argv
    assert "--strict-mcp-config" in argv
    assert "--resume" not in argv and "--continue" not in argv
