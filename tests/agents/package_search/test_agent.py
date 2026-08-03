"""Tests for the rebuilt (project-bound) PackageSearchAgent.

We stub the SDK loop (``PackageSearchAgent._run_sdk_loop``) with a
hand-rolled async generator that yields fake ``AssistantMessage`` /
``ResultMessage`` objects, then assert:

- the agent emits ``run_start`` / ``step_start`` / ``step_end`` /
  ``run_complete`` trace events in the right order;
- fenced JSON is parsed and IDs are validated against the real
  ``RavenPackageService.get_package`` lookup **scoped to the run's
  project** — cross-project IDs are dropped like hallucinated ones;
- invalid / hallucinated IDs are filtered, with a warning entry
  appended to ``tool_trace``;
- when the model omits the fenced block, the warning says
  ``missing structured answer`` and the ID arrays are empty;
- when the fenced block exists but is malformed, the warning says
  ``unparsable structured answer`` and the ID arrays are empty;
- a set ``cancel_event`` terminates the loop at the next message
  boundary with a ``cancelled`` result + trace event.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, List

import pytest

from app.agents.package_search.agent import PackageSearchAgent
from app.agents.package_search.workspace import WorkspaceContext


PROJECT = "proj-a"


# ──────────────── fake SDK message blocks ────────────────


class _ToolUseBlock:
    def __init__(self, *, name: str, tool_input: dict, block_id: str = "tool-1") -> None:
        self.name = name
        self.input = tool_input
        self.id = block_id


class _ToolResultBlock:
    def __init__(self, *, tool_use_id: str, text: str, is_error: bool = False) -> None:
        self.tool_use_id = tool_use_id
        self.content = [{"type": "text", "text": text}]
        self.is_error = is_error


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    def __init__(self, blocks: list, usage: Any = None) -> None:
        self.content = blocks
        if usage is not None:
            self.usage = usage


class _ResultMessage:
    """Fake terminal ResultMessage: carries the final answer text."""

    def __init__(self, result: str) -> None:
        self.content = None
        self.result = result


class _Usage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0


# ──────────────── fixtures ────────────────


@pytest.fixture
def stub_service(monkeypatch):
    """Stub ``raven_package_service.get_package`` so we don't depend on disk.

    ``pkg-real-*`` belong to the run's project; ``pkg-other`` is a real
    package of *another* project (must be intercepted by the agent).
    """
    from app.services import raven_package_service as svc_module

    catalog = {
        "pkg-real-1": {"id": "pkg-real-1", "projectCode": PROJECT},
        "pkg-real-2": {"id": "pkg-real-2", "projectCode": PROJECT},
        "pkg-real-3": {"id": "pkg-real-3", "projectCode": PROJECT},
        "pkg-other": {"id": "pkg-other", "projectCode": "proj-b"},
    }

    def fake_get_package(pid):
        return catalog.get(pid)

    monkeypatch.setattr(svc_module.raven_package_service, "get_package", fake_get_package)
    return catalog


@pytest.fixture
def stub_options(monkeypatch):
    """Bypass ``_build_options`` so the test does not touch ClaudeAgentOptions."""
    def fake_build(self, *, system_prompt, project_code, cwd, endpoint=None, clarification=None):
        return (object(), "fake-model", "fake-provider")

    monkeypatch.setattr(PackageSearchAgent, "_build_options", fake_build)


def _make_ctx(tmp_path, *, project_code: str = PROJECT, question: str = "q") -> WorkspaceContext:
    return WorkspaceContext(
        task_id="task-1",
        temp_dir=str(tmp_path),
        repo_dir=str(tmp_path / "repo"),
        task_json_path=str(tmp_path / "task.json"),
        project_code=project_code,
        metadata={"question": question, "hints": ""},
    )


def _make_agent(messages: List[Any]) -> PackageSearchAgent:
    """Return an agent whose ``_run_sdk_loop`` yields the canned messages."""
    agent = PackageSearchAgent()

    async def fake_loop(self, prompt, options):
        for m in messages:
            yield m

    agent._run_sdk_loop = fake_loop.__get__(agent, PackageSearchAgent)  # type: ignore[method-assign]
    return agent


# ──────────────── tests ────────────────


def test_run_parses_fenced_json_and_validates_ids(stub_service, stub_options, tmp_path):
    answer_text = (
        "Here are the matches.\n"
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1"],'
        ' "relevant_package_ids": ["pkg-real-1", "pkg-real-2"],'
        ' "notes": "best matches by name"}\n'
        "```\n"
    )
    messages = [
        _Message([
            _ToolUseBlock(name="mcp__package_search__list_packages",
                          tool_input={"limit": 5}, block_id="tu1"),
        ], usage=_Usage(input_tokens=10, output_tokens=5)),
        _Message([
            _ToolResultBlock(tool_use_id="tu1", text='{"total": 1, "items": []}'),
        ]),
        _ResultMessage(answer_text),
    ]
    agent = _make_agent(messages)
    result = asyncio.run(agent.run(_make_ctx(tmp_path, question="find katx")))

    assert result["status"] == "ok"
    assert result["recommended_package_ids"] == ["pkg-real-1"]
    assert result["relevant_package_ids"] == ["pkg-real-1", "pkg-real-2"]
    assert result["notes"] == "best matches by name"
    assert result["model"] == "fake-model"
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["output_tokens"] == 5
    assert result["session_id"] == "task-1"

    # tool_trace MUST contain one entry per step_start
    names = [entry.get("name") for entry in result["tool_trace"] if "name" in entry]
    assert names == ["mcp__package_search__list_packages"]

    # No warning entry when everything validates
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == []

    # Trace event ordering
    types = [e.get("type") for e in result["trace_events"]]
    assert types.index("run_start") < types.index("step_start")
    assert types.index("step_start") < types.index("step_end")
    assert types[-1] == "run_complete"


def test_run_accumulates_dict_usage_payload(stub_service, stub_options, tmp_path):
    """Claude-compatible providers may expose SDK usage as a plain dict."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1"], "relevant_package_ids": []}\n'
        "```\n"
    )
    messages = [
        _Message(
            [_TextBlock("thinking out loud")],
            usage={
                "prompt_tokens": 33,
                "completion_tokens": 7,
                "cache_read_input_tokens": 11,
                "cache_creation_input_tokens": 5,
            },
        ),
        _ResultMessage(answer_text),
    ]
    agent = _make_agent(messages)
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert result["usage"] == {
        "input_tokens": 33,
        "output_tokens": 7,
        "cache_read_tokens": 11,
        "cache_write_tokens": 5,
    }


def test_run_filters_invalid_ids_and_emits_warning(stub_service, stub_options, tmp_path):
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1", "fake-id-x"],'
        ' "relevant_package_ids": ["pkg-real-2", "another-fake"]}\n'
        "```\n"
    )
    agent = _make_agent([_ResultMessage(answer_text)])
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert result["recommended_package_ids"] == ["pkg-real-1"]
    assert result["relevant_package_ids"] == ["pkg-real-2"]
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert len(warnings) == 1
    assert "filtered 2 invalid ids" in warnings[0]["message"]


def test_run_intercepts_cross_project_ids(stub_service, stub_options, tmp_path):
    """A real package ID belonging to another project is dropped like a fake."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1", "pkg-other"],'
        ' "relevant_package_ids": ["pkg-other"]}\n'
        "```\n"
    )
    agent = _make_agent([_ResultMessage(answer_text)])
    result = asyncio.run(agent.run(_make_ctx(tmp_path, project_code=PROJECT)))

    assert result["recommended_package_ids"] == ["pkg-real-1"]
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert any("filtered 2 invalid ids" in w["message"] for w in warnings)


def test_run_warns_on_missing_fenced_block(stub_service, stub_options, tmp_path):
    agent = _make_agent([_ResultMessage("Sorry, I cannot answer.")])
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    assert result["answer"] == "Sorry, I cannot answer."
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == [{"type": "warning", "message": "missing structured answer"}]


def test_run_warns_on_unparsable_fenced_block(stub_service, stub_options, tmp_path):
    answer_text = "```json\n{this is not valid JSON}\n```"
    agent = _make_agent([_ResultMessage(answer_text)])
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == [{"type": "warning", "message": "unparsable structured answer"}]


def test_run_warns_when_fields_wrong_type(stub_service, stub_options, tmp_path):
    """If ``recommended_package_ids`` is not a list, treat as unparsable."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": "pkg-real-1",'
        ' "relevant_package_ids": null}\n'
        "```\n"
    )
    agent = _make_agent([_ResultMessage(answer_text)])
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings[-1]["message"] == "unparsable structured answer"


def test_cancel_event_terminates_run(stub_service, stub_options, tmp_path):
    """A pre-set cancel_event stops the loop at the first message boundary."""
    messages = [
        _Message([
            _ToolUseBlock(name="mcp__package_search__list_packages",
                          tool_input={}, block_id="tu1"),
        ]),
        _ResultMessage("should never be reached"),
    ]
    agent = _make_agent(messages)
    cancel_event = threading.Event()
    cancel_event.set()
    result = asyncio.run(agent.run(_make_ctx(tmp_path), cancel_event=cancel_event))

    assert result["status"] == "cancelled"
    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    assert result["answer"] == ""
    types = [e.get("type") for e in result["trace_events"]]
    # Two-phase cancel: a system_notice first, then the terminal event.
    assert "system_notice" in types
    assert types[-1] == "cancelled"


def test_trace_emitter_receives_events(stub_service, stub_options, tmp_path):
    """Every trace event is also pushed to the injected trace_emitter."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": [], "relevant_package_ids": []}\n'
        "```\n"
    )
    agent = _make_agent([_ResultMessage(answer_text)])
    seen: list[dict] = []
    result = asyncio.run(
        agent.run(_make_ctx(tmp_path), trace_emitter=seen.append)
    )
    assert [e.get("type") for e in seen] == [
        e.get("type") for e in result["trace_events"]
    ]
    assert seen[0]["type"] == "run_start"


def test_stream_yields_events_and_final(stub_service, stub_options, tmp_path):
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1"], "relevant_package_ids": []}\n'
        "```\n"
    )
    messages = [
        _Message([
            _ToolUseBlock(name="mcp__package_search__list_packages",
                          tool_input={"limit": 5}, block_id="tu1"),
        ]),
        _Message([
            _ToolResultBlock(tool_use_id="tu1", text='{"total": 0, "items": []}'),
        ]),
        _ResultMessage(answer_text),
    ]
    agent = _make_agent(messages)
    ctx = _make_ctx(tmp_path)

    async def collect():
        out: list[dict] = []
        async for event in agent.stream(ctx):
            out.append(event)
        return out

    events = asyncio.run(collect())
    types = [e.get("type") for e in events]
    assert "run_start" in types
    assert "step_start" in types
    assert "step_end" in types
    assert "run_complete" in types
    assert types[-1] == "final"
    final = events[-1]
    assert final["data"]["recommended_package_ids"] == ["pkg-real-1"]
    assert final["data"]["relevant_package_ids"] == []
