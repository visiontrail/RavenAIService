"""Tests for ``answer_delta`` emission from partial-streaming ``StreamEvent``.

Covers the OpenSpec change ``stream-all-chat-responses`` task 6.1:

- A ``StreamEvent`` carrying a native ``content_block_delta`` text increment
  is translated into an ``answer_delta`` trace event.
- Concatenating every ``answer_delta.text_chunk`` in ``seq`` order equals the
  full assistant answer (and the authoritative ``run_complete.final_text``).
- Non-text deltas (e.g. ``input_json_delta``) produce no ``answer_delta``.
- When the provider does not surface partial messages (no ``StreamEvent`` at
  all), no ``answer_delta`` is emitted — clients fall back to ``final_text``.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from app.agents.package_search.agent import PackageSearchAgent
from app.agents.package_search.workspace import WorkspaceContext


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    """Fake AssistantMessage: has a ``content`` list, no ``event``."""

    def __init__(self, blocks: list) -> None:
        self.content = blocks


class _ResultMessage:
    """Fake terminal ResultMessage: carries the final answer text."""

    def __init__(self, result: str) -> None:
        self.content = None
        self.result = result


class _StreamEvent:
    """Fake partial-streaming StreamEvent: an ``event`` dict, no ``content``."""

    def __init__(self, event: dict) -> None:
        self.event = event


def _text_delta(text: str) -> _StreamEvent:
    return _StreamEvent(
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
    )


def _input_json_delta(partial: str) -> _StreamEvent:
    return _StreamEvent(
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": partial},
        }
    )


@pytest.fixture
def stub_options(monkeypatch):
    def fake_build(self, *, system_prompt, project_code, cwd):
        return (object(), "fake-model", "fake-provider")

    monkeypatch.setattr(PackageSearchAgent, "_build_options", fake_build)


def _make_ctx(tmp_path) -> WorkspaceContext:
    return WorkspaceContext(
        task_id="task-1",
        temp_dir=str(tmp_path),
        repo_dir=str(tmp_path / "repo"),
        task_json_path=str(tmp_path / "task.json"),
        project_code="proj-a",
        metadata={"question": "q", "hints": ""},
    )


def _make_agent(messages: List[Any]) -> PackageSearchAgent:
    agent = PackageSearchAgent()

    async def fake_loop(self, prompt, options):
        for m in messages:
            yield m

    agent._run_sdk_loop = fake_loop.__get__(agent, PackageSearchAgent)  # type: ignore[method-assign]
    return agent


def _answer_deltas(trace_events: List[dict]) -> List[dict]:
    deltas = [e for e in trace_events if e.get("type") == "answer_delta"]
    # Must be ordered by seq; concatenation relies on it.
    return sorted(deltas, key=lambda e: e["seq"])


def test_stream_events_become_answer_delta_equal_to_final(stub_options, tmp_path):
    full = "根据日志分析，根因是失锁。"
    messages = [
        _text_delta("根据"),
        _text_delta("日志分析，"),
        _input_json_delta('{"q":'),  # non-text delta — must be ignored
        _text_delta("根因是失锁。"),
        _ResultMessage(full),  # terminal ResultMessage → state.final_text
    ]
    agent = _make_agent(messages)
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    deltas = _answer_deltas(result["trace_events"])
    assert [d["text_chunk"] for d in deltas] == ["根据", "日志分析，", "根因是失锁。"]
    # Concatenation equals the full answer body.
    assert "".join(d["text_chunk"] for d in deltas) == full
    # final_text remains the authoritative full text.
    assert result["answer"] == full
    run_complete = next(e for e in result["trace_events"] if e["type"] == "run_complete")
    assert run_complete["final_text"].strip() == full


def test_no_stream_events_emits_no_answer_delta(stub_options, tmp_path):
    """Provider-downgrade equivalent: only complete messages, no StreamEvents."""
    full = "整段返回的答复。"
    agent = _make_agent([_Message([_TextBlock(full)]), _ResultMessage(full)])
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))

    assert _answer_deltas(result["trace_events"]) == []
    # The authoritative answer is still available for whole-segment render.
    assert result["answer"] == full


def test_text_delta_extraction_ignores_non_text(stub_options, tmp_path):
    """Only text_delta increments translate; other deltas yield nothing."""
    agent = _make_agent(
        [
            _input_json_delta('{"a":1}'),
            _StreamEvent({"type": "content_block_start", "index": 0}),
            _ResultMessage("done"),
        ]
    )
    result = asyncio.run(agent.run(_make_ctx(tmp_path)))
    assert _answer_deltas(result["trace_events"]) == []
