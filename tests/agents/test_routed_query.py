"""Tests for the endpoint-aware ``query()`` wrapper.

``model_router.candidates`` / ``record_outcome`` are stubbed so these exercise
the wrapper's own contract: where the commit boundary sits, what is buffered
before it, when failover happens and when it must not.
"""

from __future__ import annotations

import pytest

from app.agents import routed_query as rq
from app.agents.routed_query import AllEndpointsUnavailable
from app.services.model_router import EndpointChoice


# ─────────────────────────── SDK message doubles ───────────────────────────
#
# Shapes mirror what claude_agent_sdk yields; the wrapper classifies by
# attribute presence rather than isinstance, so these are enough.


class InitMessage:
    """``SystemMessage(subtype='init')`` — CLI up, model not yet contacted."""

    subtype = "init"
    data = {"session_id": "s-1"}
    content = None
    event = None


class StreamEvent:
    content = None

    def __init__(self, text: str = "hi") -> None:
        self.event = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": text},
        }


class AssistantMessage:
    event = None

    def __init__(self, text: str = "hello") -> None:
        self.content = [{"type": "text", "text": text}]


class ResultMessage:
    """Terminal frame carrying no assistant content."""

    content = None
    event = None
    subtype = "success"
    data = None

    def __init__(self) -> None:
        self.result = "done"


def profile(**over):
    from app.agents.anthropic_client import PROVIDER_PROFILES

    return PROVIDER_PROFILES["yinhe"]


def choice(slot: str) -> EndpointChoice:
    return EndpointChoice(
        slot=slot,
        provider="yinhe" if slot == "primary" else "deepseek",
        base_url=f"http://{slot}.test",
        api_key=f"sk-{slot}",
        model=f"{slot}-model",
        small_fast_model=None,
        profile=profile(),
    )


@pytest.fixture
def router_stub(monkeypatch):
    """Stub the router; returns a box to set candidates and read outcomes."""
    box = {"candidates": [choice("primary"), choice("backup")], "outcomes": []}

    monkeypatch.setattr(rq.model_router, "candidates", lambda **kw: box["candidates"])
    monkeypatch.setattr(
        rq.model_router,
        "record_outcome",
        lambda slot, **kw: box["outcomes"].append({"slot": slot, **kw}),
    )
    return box


def sdk_yielding(*scripts):
    """Build a fake ``query`` that plays one script per successive call.

    Each script is a list of messages, or an exception instance to raise.
    """
    calls = {"n": 0, "options": []}

    async def fake_query(*, prompt, options):
        index = min(calls["n"], len(scripts) - 1)
        calls["n"] += 1
        calls["options"].append(options)
        for item in scripts[index]:
            if isinstance(item, BaseException):
                raise item
            yield item

    return fake_query, calls


async def drain(**kwargs):
    return [m async for m in rq.routed_query(**kwargs)]


OPTS = lambda c: {"slot": c.slot if c else None}  # noqa: E731


# ─────────────────────────── Commit boundary ───────────────────────────────


async def test_ttft_excludes_cli_startup(router_stub, monkeypatch):
    """The init message resets the clock — it precedes any model round trip.

    Measuring from generator creation would fold subprocess spawn and MCP setup
    into "endpoint latency" and trip the breaker on a healthy endpoint.
    """
    ticks = [0.0, 10.0, 10.25]  # create → init → first stream event
    monkeypatch.setattr(rq, "_now", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])

    fake_query, _ = sdk_yielding([InitMessage(), StreamEvent()])
    await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert router_stub["outcomes"] == [{"slot": "primary", "outcome": "ok", "ttft_ms": 250}]


async def test_buffers_pre_commit_messages_until_commit(router_stub):
    """Nothing may reach the caller before the attempt commits.

    ``_emit_for_message`` turns the init message into a visible system_notice,
    so leaking it from an attempt that later fails over would show the user a
    run that never happened.
    """
    fake_query, _ = sdk_yielding([InitMessage(), AssistantMessage("hi")])
    out = await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert [type(m).__name__ for m in out] == ["InitMessage", "AssistantMessage"]


async def test_assistant_message_commits_when_no_partial_streaming(router_stub):
    fake_query, _ = sdk_yielding([InitMessage(), AssistantMessage(), ResultMessage()])
    out = await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert len(out) == 3
    assert router_stub["outcomes"][0]["outcome"] == "ok"


async def test_unrecognised_message_shape_still_commits(router_stub):
    """Commit is defined by exclusion, so an unknown shape is never swallowed.

    Regression: an earlier version committed only on messages carrying
    ``content``/``event``. A message shaped differently (agents' own doubles
    carry ``tool_uses``) stayed buffered, and a cancel mid-run then dropped it —
    losing a tool call the caller had already accounted for.
    """

    class ToolUseOnly:
        tool_uses = [{"name": "Read"}]

    fake_query, _ = sdk_yielding([InitMessage(), ToolUseOnly(), ResultMessage()])
    out = await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert [type(m).__name__ for m in out] == ["InitMessage", "ToolUseOnly", "ResultMessage"]
    assert router_stub["outcomes"][0]["outcome"] == "ok"


async def test_init_only_stream_still_yields_buffer(router_stub):
    """A stream that never gets past startup must not swallow what it buffered."""
    fake_query, _ = sdk_yielding([InitMessage()])
    out = await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert [type(m).__name__ for m in out] == ["InitMessage"]
    assert router_stub["outcomes"] == [{"slot": "primary", "outcome": "ok"}]


# ─────────────────────────── Failover ──────────────────────────────────────


async def test_fails_over_before_first_token(router_stub):
    fake_query, calls = sdk_yielding(
        [InitMessage(), ConnectionError("connection refused")],
        [InitMessage(), AssistantMessage("from backup")],
    )
    seen: list[str] = []

    out = await drain(
        prompt="p",
        make_options=OPTS,
        sdk_query=fake_query,
        on_endpoint=lambda c: seen.append(c.slot),
    )

    assert seen == ["primary", "backup"]
    assert len(out) == 2  # only the backup's messages
    assert router_stub["outcomes"][0] == {"slot": "primary", "outcome": "hard_failure"}
    assert router_stub["outcomes"][1]["slot"] == "backup"


async def test_options_are_rebuilt_per_candidate(router_stub):
    """Capability gating is baked into options, so they cannot be reused."""
    fake_query, calls = sdk_yielding(
        [ConnectionError("nope")],
        [AssistantMessage()],
    )
    await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert calls["options"] == [{"slot": "primary"}, {"slot": "backup"}]


async def test_no_failover_after_commit(router_stub):
    """Once tools may have run, retrying would replay side effects."""
    fake_query, calls = sdk_yielding(
        [InitMessage(), AssistantMessage(), RuntimeError("upstream died mid-stream")],
        [AssistantMessage("backup should never run")],
    )

    with pytest.raises(RuntimeError, match="mid-stream"):
        await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert calls["n"] == 1


async def test_all_endpoints_failing_raises_typed_error(router_stub):
    fake_query, _ = sdk_yielding(
        [ConnectionError("primary down")],
        [ConnectionError("backup down")],
    )

    with pytest.raises(AllEndpointsUnavailable) as excinfo:
        await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    # Both causes must survive — with everything down, why is all that is left.
    assert "primary down" in str(excinfo.value)
    assert "backup down" in str(excinfo.value)
    assert [slot for slot, _ in excinfo.value.failures] == ["primary", "backup"]


async def test_falls_back_to_legacy_path_when_no_candidates(router_stub):
    """Routing off / nothing configured must behave exactly as before."""
    router_stub["candidates"] = []
    fake_query, calls = sdk_yielding([AssistantMessage()])

    out = await drain(prompt="p", make_options=OPTS, sdk_query=fake_query)

    assert len(out) == 1
    assert calls["options"] == [{"slot": None}]  # build_options called with endpoint=None
    assert router_stub["outcomes"] == []  # nothing to attribute the call to
