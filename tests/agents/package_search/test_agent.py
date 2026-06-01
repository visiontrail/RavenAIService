"""Tests for PackageSearchAgent.

We stub the SDK loop (``PackageSearchAgent._run_sdk_loop``) with a
hand-rolled async generator that yields fake ``AssistantMessage`` /
``ResultMessage`` objects, then assert:

- the agent emits ``run_start`` / ``step_start`` / ``step_end`` /
  ``run_complete`` trace events in the right order;
- fenced JSON is parsed and IDs are validated against the real
  ``RavenPackageService.get_package`` lookup;
- invalid / hallucinated IDs are filtered, with a warning entry
  appended to ``tool_trace``;
- when the model omits the fenced block, the warning says
  ``missing structured answer`` and the ID arrays are empty;
- when the fenced block exists but is malformed, the warning says
  ``unparsable structured answer`` and the ID arrays are empty.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List

import pytest

from app.agents.package_search.agent import PackageSearchAgent


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


class _Usage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0


# ──────────────── fixture: stub the service for ID validation ────────────────


@pytest.fixture
def stub_service(monkeypatch):
    """Stub ``raven_package_service.get_package`` so we don't depend on disk."""
    from app.services import raven_package_service as svc_module

    known_ids = {"pkg-real-1", "pkg-real-2", "pkg-real-3"}

    def fake_get_package(pid):
        return {"id": pid} if pid in known_ids else None

    monkeypatch.setattr(svc_module.raven_package_service, "get_package", fake_get_package)
    return known_ids


@pytest.fixture
def stub_options(monkeypatch):
    """Bypass ``_build_options`` so the test does not touch ClaudeAgentOptions."""
    def fake_build(self, *, system_prompt, max_turns=None):
        return (object(), "fake-model", "fake-provider")

    monkeypatch.setattr(PackageSearchAgent, "_build_options", fake_build)


def _make_agent(messages: List[Any]) -> PackageSearchAgent:
    """Return an agent whose ``_run_sdk_loop`` yields the canned messages."""
    agent = PackageSearchAgent()

    async def fake_loop(self, prompt, options):
        for m in messages:
            yield m

    agent._run_sdk_loop = fake_loop.__get__(agent, PackageSearchAgent)  # type: ignore[method-assign]
    return agent


def _run(agent: PackageSearchAgent, query: str = "find packages"):
    return asyncio.get_event_loop().run_until_complete(agent.run(query))


# ──────────────── tests ────────────────


def test_run_parses_fenced_json_and_validates_ids(stub_service, stub_options):
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
        _Message([_TextBlock(answer_text)], usage=_Usage(input_tokens=20, output_tokens=15)),
    ]
    agent = _make_agent(messages)
    result = asyncio.run(agent.run("find katx"))

    assert result["recommended_package_ids"] == ["pkg-real-1"]
    assert result["relevant_package_ids"] == ["pkg-real-1", "pkg-real-2"]
    assert result["notes"] == "best matches by name"
    assert result["model"] == "fake-model"
    assert result["usage"]["input_tokens"] == 30
    assert result["usage"]["output_tokens"] == 20

    # tool_trace MUST contain one entry per step_start
    names = [entry.get("name") for entry in result["tool_trace"] if "name" in entry]
    assert names == ["mcp__package_search__list_packages"]

    # No warning entry when everything validates
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == []


def test_run_accumulates_dict_usage_payload(stub_service, stub_options):
    """Claude-compatible providers may expose SDK usage as a plain dict."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1"], "relevant_package_ids": []}\n'
        "```\n"
    )
    messages = [
        _Message(
            [_TextBlock(answer_text)],
            usage={
                "prompt_tokens": 33,
                "completion_tokens": 7,
                "cache_read_input_tokens": 11,
                "cache_creation_input_tokens": 5,
            },
        ),
    ]
    agent = _make_agent(messages)
    result = asyncio.run(agent.run("find katx"))

    assert result["usage"] == {
        "input_tokens": 33,
        "output_tokens": 7,
        "cache_read_tokens": 11,
        "cache_write_tokens": 5,
    }


def test_run_filters_invalid_ids_and_emits_warning(stub_service, stub_options):
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": ["pkg-real-1", "fake-id-x"],'
        ' "relevant_package_ids": ["pkg-real-2", "another-fake"]}\n'
        "```\n"
    )
    agent = _make_agent([
        _Message([_TextBlock(answer_text)]),
    ])
    result = asyncio.run(agent.run("q"))

    assert result["recommended_package_ids"] == ["pkg-real-1"]
    assert result["relevant_package_ids"] == ["pkg-real-2"]
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert len(warnings) == 1
    assert "filtered 2 invalid ids" in warnings[0]["message"]


def test_run_warns_on_missing_fenced_block(stub_service, stub_options):
    agent = _make_agent([
        _Message([_TextBlock("Sorry, I cannot answer.")]),
    ])
    result = asyncio.run(agent.run("q"))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == [{"type": "warning", "message": "missing structured answer"}]


def test_run_warns_on_unparsable_fenced_block(stub_service, stub_options):
    answer_text = "```json\n{this is not valid JSON}\n```"
    agent = _make_agent([_Message([_TextBlock(answer_text)])])
    result = asyncio.run(agent.run("q"))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == [{"type": "warning", "message": "unparsable structured answer"}]


def test_run_warns_when_fields_wrong_type(stub_service, stub_options):
    """If ``recommended_package_ids`` is not a list, treat as unparsable."""
    answer_text = (
        "```json\n"
        '{"recommended_package_ids": "pkg-real-1",'
        ' "relevant_package_ids": null}\n'
        "```\n"
    )
    agent = _make_agent([_Message([_TextBlock(answer_text)])])
    result = asyncio.run(agent.run("q"))

    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings[-1]["message"] == "unparsable structured answer"


def test_stream_yields_events_and_final(stub_service, stub_options):
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
        _Message([_TextBlock(answer_text)]),
    ]
    agent = _make_agent(messages)

    async def collect():
        out: list[dict] = []
        async for event in agent.stream("q"):
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
