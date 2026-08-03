"""Regression tests: AskUserQuestion must work for *every* chat agent.

The user preference「指令不清晰时允许 Agent 向我提问」is global, but the
capability originally shipped wired to DeviceAgent only, so a vague prompt to
the log-analysis agent (e.g. "请定位问题") was answered by guessing instead of
asking. These tests pin the three structural pieces that were missing:

1. the ask tool + its prompt guidance reach log_analysis / project_expert /
   package_search when a binding is supplied, and are absent when it is not;
2. ``PermissionBroker`` can be resolved from a different event loop, because
   those agents run under ``asyncio.to_thread → asyncio.run``;
3. the workflow agents' guidance says clarifying outranks their mandatory
   step-by-step workflow.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional

import pytest

from app.agents.clarification import (
    ASK_SDK_NAME,
    BUILTIN_ASK_TOOL_NAME,
    ClarificationBinding,
    ClarificationPrefs,
    clarification_guidance,
    setup_clarification,
)
from app.agents.hitl_broker import PermissionBroker


# ─────────────────────── Preferences ───────────────────────────────


class _FakeUser:
    def __init__(self, enabled=True, max_rounds=5, on_timeout="cancel"):
        self.clarification_enabled = enabled
        self.clarification_max_rounds = max_rounds
        self.clarification_on_timeout = on_timeout


def test_prefs_default_to_enabled_for_anonymous_users():
    prefs = ClarificationPrefs.from_user(None)
    assert prefs.enabled is True
    assert prefs.active is True


def test_prefs_follow_the_user_record():
    off = ClarificationPrefs.from_user(_FakeUser(enabled=False))
    assert off.active is False

    # max_rounds=0 means "never actually ask" even with the switch on.
    zero = ClarificationPrefs.from_user(_FakeUser(enabled=True, max_rounds=0))
    assert zero.enabled is True
    assert zero.active is False


def test_binding_is_none_when_preference_is_off():
    assert (
        ClarificationBinding.for_chat_run(
            user=_FakeUser(enabled=False), run_id="run-1", session_id="s-1"
        )
        is None
    )


def test_binding_is_none_without_a_run_id():
    """No run_id means the resolve endpoint could never find the broker."""
    assert (
        ClarificationBinding.for_chat_run(
            user=_FakeUser(), run_id="", session_id="s-1"
        )
        is None
    )


# ─────────────────────── Prompt guidance ───────────────────────────


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_workflow_guidance_overrides_the_mandatory_workflow(locale):
    """The investigative agents' prompts mandate a fixed multi-step workflow;
    without this carve-out the model reads that as "never pause to ask"."""
    plain = clarification_guidance(locale, max_rounds=3)
    workflow = clarification_guidance(locale, max_rounds=3, workflow_agent=True)

    assert workflow.startswith(plain)
    assert len(workflow) > len(plain)
    # Names the exact failure mode: a bare "locate the problem" style request.
    needle = "请定位问题" if locale == "zh" else "locate the problem"
    assert needle in workflow


def test_guidance_carries_the_round_cap():
    assert "3" in clarification_guidance("zh", max_rounds=3)


# ─────────────────────── setup_clarification ───────────────────────


@pytest.fixture
def sdk_stub(monkeypatch):
    """Stub the SDK so these tests never need claude-agent-sdk installed."""
    import app.agents.clarification as clarification_mod

    def fake_build(**kwargs):
        return {"server": "fake", **kwargs}, ASK_SDK_NAME

    monkeypatch.setattr(clarification_mod, "build_clarification_mcp_server", fake_build)


def test_setup_returns_none_when_disabled(sdk_stub):
    assert (
        setup_clarification(
            ClarificationPrefs.disabled(),
            emit=None,
            seq_counter=None,
            task_id="t",
            run_id="run-1",
        )
        is None
    )


def test_setup_returns_none_for_a_missing_binding(sdk_stub):
    """The Celery entry point passes no prefs at all — it must not ask."""
    assert (
        setup_clarification(
            None, emit=None, seq_counter=None, task_id="t", run_id="run-1"
        )
        is None
    )


def test_setup_registers_the_broker_and_exposes_the_tool(sdk_stub):
    registered: Dict[str, Any] = {}
    unregistered: List[str] = []

    runtime = setup_clarification(
        ClarificationPrefs(enabled=True, max_rounds=2),
        emit=None,
        seq_counter=None,
        task_id="task-1",
        run_id="run-1",
        session_id="sess-1",
        register_broker=lambda rid, b: registered.__setitem__(rid, b),
        unregister_broker=unregistered.append,
        workflow_agent=True,
    )

    assert runtime is not None
    # The resolve endpoint looks brokers up by run_id — registration is what
    # makes an answer routable back to the waiting agent.
    assert registered["run-1"] is runtime.broker
    assert runtime.sdk_tool_name == ASK_SDK_NAME
    assert "mcp__ask__AskUserQuestion" in runtime.prompt_addendum

    servers, tools = runtime.apply({"project_repo": object()}, ["Bash", "Read"])
    assert "ask" in servers and "project_repo" in servers
    assert ASK_SDK_NAME in tools
    assert tools[:2] == ["Bash", "Read"]

    runtime.close()
    assert unregistered == ["run-1"]


def test_apply_does_not_mutate_the_callers_collections(sdk_stub):
    runtime = setup_clarification(
        ClarificationPrefs(enabled=True),
        emit=None,
        seq_counter=None,
        task_id="t",
        run_id="run-1",
    )
    assert runtime is not None
    servers_in: Dict[str, Any] = {}
    tools_in: List[str] = ["Bash"]
    runtime.apply(servers_in, tools_in)
    assert servers_in == {}
    assert tools_in == ["Bash"]


def test_apply_is_idempotent_across_failover_rebuilds(sdk_stub):
    """package_search rebuilds options per routed candidate."""
    runtime = setup_clarification(
        ClarificationPrefs(enabled=True),
        emit=None,
        seq_counter=None,
        task_id="t",
        run_id="run-1",
    )
    assert runtime is not None
    servers, tools = runtime.apply(None, ["Bash"])
    servers, tools = runtime.apply(servers, tools)
    assert tools.count(ASK_SDK_NAME) == 1


# ─────────────────────── Cross-loop resolution ─────────────────────


def test_broker_resolves_across_event_loops():
    """log_analysis / project_expert / package_search run the SDK loop inside
    ``asyncio.to_thread → asyncio.run``, so the FastAPI handler that resolves a
    clarification is on a *different, running* loop in a different thread. A
    plain ``future.set_result`` would never wake the waiter."""
    broker = PermissionBroker()
    opened = threading.Event()
    result: Dict[str, Any] = {}

    async def agent_side() -> None:
        future = broker.open_clarification("req-1")
        opened.set()
        result["decision"] = await asyncio.wait_for(future, timeout=5.0)

    def agent_thread() -> None:
        asyncio.run(agent_side())

    worker = threading.Thread(target=agent_thread)
    worker.start()
    assert opened.wait(timeout=5.0)

    # Resolve from the main thread, the way the HTTP endpoint does.
    for _ in range(200):
        if broker.resolve("req-1", {"answers": [{"question_index": 0}]}):
            break
        threading.Event().wait(0.01)
    else:  # pragma: no cover - would mean resolve never found the request
        pytest.fail("broker.resolve never matched the pending request")

    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert result["decision"] == {"answers": [{"question_index": 0}]}


def test_broker_close_denies_pending_requests_from_another_thread():
    broker = PermissionBroker()
    opened = threading.Event()
    result: Dict[str, Any] = {}

    async def agent_side() -> None:
        future = broker.open_clarification("req-1")
        opened.set()
        result["decision"] = await asyncio.wait_for(future, timeout=5.0)

    worker = threading.Thread(target=lambda: asyncio.run(agent_side()))
    worker.start()
    assert opened.wait(timeout=5.0)

    broker.close()
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert result["decision"]["decision"] == "deny"
    assert result["decision"]["reason"] == "run_complete"


# ─────────────────────── Agent wiring ──────────────────────────────


@pytest.mark.parametrize(
    "module_path, agent_name",
    [
        ("app.agents.log_analysis.agent", "LogAnalysisAgent"),
        ("app.agents.project_expert.agent", "ProjectExpertAgent"),
        ("app.agents.package_search.agent", "PackageSearchAgent"),
    ],
)
def test_every_workspace_agent_accepts_a_clarification_binding(module_path, agent_name):
    """All three investigative agents must expose the same entry point — this is
    what makes the global preference genuinely global rather than per-agent."""
    import importlib
    import inspect

    agent_cls = getattr(importlib.import_module(module_path), agent_name)
    for method in ("run", "run_sync"):
        params = inspect.signature(getattr(agent_cls, method)).parameters
        assert "clarification_binding" in params, f"{agent_name}.{method}"
        assert params["clarification_binding"].default is None


def test_builtin_ask_tool_name_is_the_bare_name():
    """The SDK's own AskUserQuestion is not wired to our broker or SSE card, so
    agents must disallow it explicitly; only the mcp__ask__ tool is valid."""
    assert BUILTIN_ASK_TOOL_NAME == "AskUserQuestion"
    assert ASK_SDK_NAME == "mcp__ask__AskUserQuestion"
