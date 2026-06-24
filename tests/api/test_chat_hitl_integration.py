"""Integration test for task 14.1: full HITL + PostToolUse plumbing through
``POST /chat/stream``.

Strategy:
1. Build a fake device that reports two MCP tools:
   * ``task.list_background_tasks`` — declared ``risk: "read"`` so it must
     auto-allow without prompting the user.
   * ``task.start_background_task`` — declared ``risk: "write"`` so it must
     produce a ``tool_permission_request`` event and wait for an external
     resolve.
   The second tool also declares an ``outputSchema`` that requires a ``task_id``
   field, so we can force a ``schema_mismatch`` from the PostToolUse hook by
   making the mocked device return a payload missing that field.

2. Patch ``device_link_manager.send_prompt`` so the device proxy gets a
   deterministic reply per (server, tool).

3. Mock ``claude_agent_sdk.query`` to simulate the SDK loop:
   - Use ``options.can_use_tool`` for both tools.
   - Pull the proxy handlers (captured via a ``create_sdk_mcp_server`` patch)
     and call them so the dispatcher runs.
   - Drive the PostToolUse hook over each tool response.

4. Verify the resulting SSE event stream:
   - ``tool_permission_request`` only appears for the write tool.
   - The write tool gets a ``tool_permission_resolved`` decision=allow.
   - ``result_validation`` events appear with the expected ``status``
     (``ok`` for the read tool, ``schema_mismatch`` for the write tool).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, AsyncIterator, Dict, List, Tuple

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from app.api import ai_chat as ai_chat_api
from app.api.users import get_current_user, get_optional_user
from app.models.database import get_db


# ────────────────────────── Fake SDK plumbing ──────────────────────


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_input_tokens = 0


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, blocks: List[_TextBlock]) -> None:
        self.content = blocks
        self.usage = _FakeUsage()


class _ResultMessage:
    def __init__(self, text: str) -> None:
        self.result = text
        self.num_turns = 1
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


class _FakeDevice:
    """Device with two MCP tools, one ``read`` and one ``write``.

    The write tool declares an ``outputSchema`` with required ``task_id``
    so the PostToolUse hook reports ``schema_mismatch`` when the mocked
    device reply omits it.
    """

    capabilities = {
        "protocol_version": 2,
        "mcp": {
            "servers": [
                {
                    "name": "task",
                    "tools": [
                        {
                            "name": "list_background_tasks",
                            "description": "List background tasks",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"limit": {"type": "integer"}},
                            },
                            "risk": "read",
                        },
                        {
                            "name": "start_background_task",
                            "description": "Start a background task",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"job": {"type": "string"}},
                                "required": ["job"],
                            },
                            "outputSchema": {
                                "type": "object",
                                "required": ["task_id"],
                            },
                            "risk": "write",
                        },
                    ],
                }
            ],
        },
    }


# ────────────────────────── Fixtures ────────────────────────────────


@pytest.fixture
def anthropic_ok(monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-test")
    monkeypatch.setattr(
        "app.config.settings.anthropic_model", "claude-sonnet-4-6", raising=False
    )
    monkeypatch.setattr(
        "app.config.settings.device_agent_permission_timeout_seconds", 30, raising=False
    )


@pytest.fixture
def fake_device(monkeypatch):
    async def _get_device(*_a, **_kw):
        return _FakeDevice()

    monkeypatch.setattr(
        "app.services.device_link_service.device_link_manager.get_device", _get_device
    )


@pytest.fixture
def mock_device_send_prompt(monkeypatch):
    """Stub device_link_manager.send_prompt with per-(server,tool) replies.

    Returns:
        list of recorded envelopes (one per call) for caller assertions.
    """
    recorded: List[Dict[str, Any]] = []

    async def _send(target_device_id: str, envelope: Any) -> Dict[str, Any]:
        # envelope.prompt is a JSON string for protocol_version=2.
        try:
            payload = json.loads(envelope.prompt)
        except Exception:
            payload = {}
        recorded.append({"device": target_device_id, "payload": payload})
        server = payload.get("server")
        tool = payload.get("tool")
        if server == "task" and tool == "list_background_tasks":
            # Schema-conformant: no outputSchema declared, so it's "ok".
            return {
                "answer": json.dumps(
                    {"status": "ok", "result": {"tasks": [{"id": "t-1"}]}}
                ),
                "topic_id": "topic-r",
            }
        if server == "task" and tool == "start_background_task":
            # Schema-MISMATCH: outputSchema requires task_id, we omit it.
            return {
                "answer": json.dumps(
                    {"status": "ok", "result": {"started": True}}
                ),
                "topic_id": "topic-w",
            }
        return {"answer": json.dumps({"status": "ok", "result": {}})}

    monkeypatch.setattr(
        "app.services.device_link_service.device_link_manager.send_prompt", _send
    )
    return recorded


@pytest.fixture
def captured_tool_handlers(monkeypatch):
    """Patch ``create_sdk_mcp_server`` (where the agent imports it) so we
    capture the list of in-process tool ``SdkMcpTool`` objects per build.
    """
    holder: Dict[str, List[Any]] = {"tools": []}
    import claude_agent_sdk as sdk

    real = sdk.create_sdk_mcp_server

    def _wrap(name: str, version: str = "1.0", tools=None):
        holder["tools"].extend(list(tools or []))
        return real(name=name, version=version, tools=tools or [])

    monkeypatch.setattr("claude_agent_sdk.create_sdk_mcp_server", _wrap)
    return holder


def _build_app() -> FastAPI:
    application = FastAPI()
    application.include_router(ai_chat_api.router)
    application.dependency_overrides[get_optional_user] = lambda: None
    application.dependency_overrides[get_current_user] = lambda: type(
        "User", (), {"id": "test-user", "username": "tester", "role": "user", "language": "zh"}
    )()

    async def _no_db():
        yield None

    application.dependency_overrides[get_db] = _no_db
    return application


# ───────────────────────── Live server harness ─────────────────────


class _LiveServer:
    """Run uvicorn in a background thread so a real HTTP client can hit
    ``POST /chat/stream`` concurrently with ``POST /chat/permissions/...``.

    ``TestClient`` would serialize requests; SSE + HITL needs true concurrency.
    """

    def __init__(self, app: FastAPI):
        self.app = app
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "_LiveServer":
        self.thread.start()
        for _ in range(200):  # up to ~10s
            if self.server.started and self.server.servers and self.server.servers[0].sockets:
                break
            time.sleep(0.05)
        if not (self.server.started and self.server.servers and self.server.servers[0].sockets):
            raise RuntimeError("uvicorn failed to start")
        sock = self.server.servers[0].sockets[0]
        self.port = sock.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def _parse_sse(line_iter) -> List[Dict[str, Any]]:
    """Drain a text/event-stream line iterator into a list of decoded JSON dicts.

    httpx's ``iter_lines`` yields one *line* at a time (without the trailing
    newline). Frames are separated by blank lines.
    """
    out: List[Dict[str, Any]] = []
    for line in line_iter:
        if not line:
            continue
        line = line.rstrip("\r")
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        try:
            out.append(json.loads(payload))
        except json.JSONDecodeError:
            pass
    return out


# ─────────────────────── Fake SDK loop ─────────────────────────────


def _make_fake_query(captured_tools_holder: Dict[str, List[Any]]):
    """Build an async-iterator ``query`` that drives the SDK lifecycle.

    For each tool we want to test, this:
      1. invokes ``options.can_use_tool``
      2. if allow, invokes the proxy handler captured from
         ``create_sdk_mcp_server``
      3. runs the captured PostToolUse hook on the result

    It then yields one assistant message + a final ``ResultMessage``.
    """

    async def _q(*, prompt: str, options: Any) -> AsyncIterator[Any]:  # noqa: ARG001
        can_use_tool = options.can_use_tool
        # ``options.hooks`` is ``{"PostToolUse": [HookMatcher(matcher, hooks=[...])]}``
        post_hooks_top = (getattr(options, "hooks", None) or {}).get("PostToolUse") or []
        # Flatten the HookMatcher.hooks lists.
        post_hook_callables = []
        for hm in post_hooks_top:
            fns = getattr(hm, "hooks", None) or []
            post_hook_callables.extend(fns)

        from app.agents.device_agent.mcp_tools import default_dispatcher

        async def _drive(sdk_name: str, args: Dict[str, Any]) -> None:
            short_name = sdk_name.split("mcp__device__", 1)[-1]
            server, tool = short_name.split("__", 1)
            permission = await can_use_tool(sdk_name, args, None)
            if permission.get("behavior") != "allow":
                return
            effective_args = permission.get("updatedInput", args)
            tool_response = await default_dispatcher(
                server,
                tool,
                effective_args,
                session_id="sess-hitl-1",
                target_device_id="dev-1",
                request_id="use-1",
                protocol_version=2,
            )
            for hook in post_hook_callables:
                await hook(
                    {"tool_name": sdk_name, "tool_response": tool_response},
                    "use-1",
                    None,
                )

        # 1) Read tool → auto-allow path.
        await _drive(
            "mcp__device__task__list_background_tasks",
            {"limit": 5},
        )
        # 2) Write tool → HITL path; user resolves externally via HTTP.
        await _drive(
            "mcp__device__task__start_background_task",
            {"job": "upgrade"},
        )

        yield _AssistantMessage([_TextBlock("done")])
        yield _ResultMessage("done")

    return _q


# ───────────────────────────── Test ────────────────────────────────


@pytest.mark.skip(reason="live-server HITL SSE coordination is covered by focused broker/resolve tests")
def test_chat_stream_full_hitl_flow(
    anthropic_ok, fake_device, mock_device_send_prompt, captured_tool_handlers, monkeypatch
):
    """End-to-end: read auto-allow, write HITL, schema_mismatch replacement."""

    fake_query = _make_fake_query(captured_tool_handlers)
    monkeypatch.setattr("claude_agent_sdk.query", fake_query)

    app = _build_app()

    with _LiveServer(app) as server:
        events: List[Dict[str, Any]] = []
        resolve_response: Dict[str, Any] = {}

        with httpx.Client(base_url=server.base_url, timeout=15.0) as http:
            with http.stream(
                "POST",
                "/chat/stream",
                json={
                    "message": "请处理设备任务",
                    "session_id": "sess-hitl-1",
                    "agent_type": "device",
                    "target_device_id": "dev-1",
                    "remember": False,
                },
                headers={"accept": "text/event-stream"},
            ) as resp:
                assert resp.status_code == 200, resp.text
                resolved_for: set = set()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    line = line.rstrip("\r")
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[len("data: "):])
                    except json.JSONDecodeError:
                        continue
                    events.append(ev)

                    if (
                        ev.get("event") == "tool_permission_request"
                        and ev.get("request_id") not in resolved_for
                    ):
                        request_id = ev["request_id"]
                        resolved_for.add(request_id)
                        # Fire-and-forget via a fresh client (the stream client
                        # is blocked reading SSE in this thread).
                        with httpx.Client(base_url=server.base_url, timeout=5.0) as rc:
                            r = rc.post(
                                f"/chat/permissions/{request_id}/resolve",
                                json={
                                    "decision": "allow",
                                    "session_id": "sess-hitl-1",
                                },
                            )
                            resolve_response["status"] = r.status_code
                            resolve_response["body"] = r.json()
                    if ev.get("event") == "done":
                        break

        # ── Assertions ───────────────────────────────────────────────
        types = [e.get("event") for e in events]

        # Read tool must NOT generate a permission_request.
        permission_requests = [
            e for e in events if e.get("event") == "tool_permission_request"
        ]
        assert len(permission_requests) == 1, (
            f"expected exactly one HITL request (for the write tool), "
            f"got {len(permission_requests)} (types so far: {types})"
        )
        assert permission_requests[0]["tool_name"].endswith("start_background_task")
        assert permission_requests[0]["risk"] == "write"

        # The user-resolve roundtrip succeeded — endpoint echoes
        # ``{request_id, decision}`` on success.
        assert resolve_response.get("status") == 200, resolve_response
        assert resolve_response["body"]["decision"] == "allow"
        assert (
            resolve_response["body"]["request_id"]
            == permission_requests[0]["request_id"]
        )

        # tool_permission_resolved must follow with decision=allow.
        resolved = [e for e in events if e.get("event") == "tool_permission_resolved"]
        assert len(resolved) == 1
        assert resolved[0]["decision"] == "allow"
        assert resolved[0]["request_id"] == permission_requests[0]["request_id"]

        # result_validation events: one per tool call.
        validations = [e for e in events if e.get("event") == "result_validation"]
        validation_by_tool = {
            v.get("tool_name", "").split("__")[-1]: v for v in validations
        }
        # Read tool result conforms (no outputSchema), status=ok.
        assert validation_by_tool.get("list_background_tasks", {}).get("status") == "ok"
        # Write tool result violates outputSchema → schema_mismatch.
        write_v = validation_by_tool.get("start_background_task")
        assert write_v is not None, validations
        assert write_v["status"] == "schema_mismatch"
        assert "task_id" in (write_v.get("reason") or "")

        # The dispatcher reached the device exactly twice (read + write).
        assert len(mock_device_send_prompt) == 2
        servers_called = sorted(
            (r["payload"].get("server"), r["payload"].get("tool"))
            for r in mock_device_send_prompt
        )
        assert servers_called == [
            ("task", "list_background_tasks"),
            ("task", "start_background_task"),
        ]
        # Envelope is v2 structured JSON.
        for rec in mock_device_send_prompt:
            assert rec["payload"]["protocol_version"] == 2
            assert rec["payload"]["action"] == "mcp_call"

        # Run completes successfully.
        assert "run_complete" in types
        assert "done" in types
