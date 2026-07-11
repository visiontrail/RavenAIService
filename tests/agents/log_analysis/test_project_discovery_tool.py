from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_discover_projects_mcp_tool_returns_only_safe_catalog(monkeypatch):
    from app.agents.log_analysis import mcp_tools

    registered = {}

    def fake_tool(name, _description, _schema):
        def decorate(func):
            registered[name] = func
            return func

        return decorate

    def fake_server(**kwargs):
        return kwargs

    fake_sdk = SimpleNamespace(
        tool=fake_tool,
        create_sdk_mcp_server=fake_server,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    monkeypatch.setattr(mcp_tools, "_server", None)
    monkeypatch.setattr(mcp_tools, "_discovery_server", None)

    safe_payload = {
        "projects": [
            {
                "id": 1,
                "project_code": "alpha",
                "project_name": "Alpha",
                "project_card": "Alpha telemetry processing",
                "has_repo": True,
                "enabled_agent_keys": ["project_expert"],
            }
        ],
        "count": 1,
        "truncated": False,
    }
    with patch.object(
        mcp_tools,
        "discover_projects_payload",
        new=AsyncMock(return_value=safe_payload),
    ):
        server = mcp_tools.get_mcp_server()
        discovery_server = mcp_tools.get_project_discovery_mcp_server()
        response = await registered["discover_projects"]({})

    assert server["name"] == "project_repo"
    assert [tool.__name__ for tool in discovery_server["tools"]] == ["_discover_projects"]
    assert [tool.__name__ for tool in server["tools"]] == [
        "_discover_projects",
        "_lookup_project_repo",
    ]
    assert set(registered) == {"discover_projects", "lookup_project_repo"}
    payload = json.loads(response["content"][0]["text"])
    assert payload == safe_payload
    serialized = json.dumps(payload)
    for sensitive in ("repo_url", "clone_url", "git_token", "auth_required"):
        assert sensitive not in serialized

    # Avoid leaking the fake server into later tests in the same process.
    mcp_tools._server = None
    mcp_tools._discovery_server = None
