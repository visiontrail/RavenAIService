"""End-to-end coverage for the four query categories from task 8.1.

Task 8.1 in the OpenSpec change called for a human to start the
backend + frontend and visually verify that the four representative
query categories (name substring / version range / component /
statistics) each return a structured recommendation. This module
turns that manual scenario into an automated test by:

1. Seeding an isolated ``RavenPackageService`` with a small but
   representative package catalog;
2. Pointing both the MCP tool dispatch (``TOOL_CALLS``) and the
   agent's ID validation path at that isolated service;
3. Driving ``PackageSearchAgent`` with a stub SDK loop that
   simulates the model picking the right tool for each query type,
   actually calling the real MCP tool against the seeded data, and
   then emitting the fenced JSON answer pointing at the IDs that
   tool returned.

If the agent / MCP wiring regresses in a way that would also break
human verification (e.g. brief-shape mismatch, broken ID validation,
forgotten warning), at least one of these scenarios will fail.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, List

import pytest

from app.agents.package_search.agent import PackageSearchAgent
from app.agents.package_search.mcp_tools import TOOL_CALLS
from app.agents.package_search.workspace import WorkspaceContext
from app.services.raven_package_service import RavenPackageService


# ──────────────── fake SDK message helpers ────────────────


class _ToolUseBlock:
    def __init__(self, *, name: str, tool_input: dict, block_id: str) -> None:
        self.name = name
        self.input = tool_input
        self.id = block_id


class _ToolResultBlock:
    def __init__(self, *, tool_use_id: str, text: str) -> None:
        self.tool_use_id = tool_use_id
        self.content = [{"type": "text", "text": text}]
        self.is_error = False


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    def __init__(self, blocks: list) -> None:
        self.content = blocks


class _ResultMessage:
    """Fake terminal ResultMessage: carries the final answer text."""

    def __init__(self, result: str) -> None:
        self.content = None
        self.result = result


# ──────────────── fixture: isolated service + bound singletons ────────────────


def _pkg(
    pid: str,
    name: str,
    version: str,
    ptype: str = "lingxi-10",
    **meta: Any,
) -> dict:
    return {
        "id": pid,
        "name": name,
        "version": version,
        "packageType": ptype,
        "path": f"/tmp/{name}",
        "size": meta.pop("size", 4096),
        "createdAt": meta.pop("createdAt", "2025-01-01T00:00:00Z"),
        "metadata": {
            "isPatch": meta.pop("is_patch", False),
            "components": [
                {"name": c, "version": version} for c in meta.pop("components", [])
            ],
            "tags": meta.pop("tags", []),
            "description": meta.pop("description", ""),
            "sha256": "deadbeef" * 8,
            "customFields": {},
        },
    }


@pytest.fixture
def seeded_service(tmp_path, monkeypatch):
    """Set up an isolated RavenPackageService with a diverse fixture set."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "raven_data_dir", str(tmp_path / "raven"))
    monkeypatch.setattr(
        app_settings,
        "raven_metadata_file",
        str(tmp_path / "raven" / "package-metadata.json"),
    )
    monkeypatch.setattr(app_settings, "upload_dir", str(tmp_path / "raven" / "uploads"))
    monkeypatch.setattr(app_settings, "package_search_default_limit", 5)
    monkeypatch.setattr(app_settings, "package_search_max_limit", 10)

    svc = RavenPackageService()
    svc.get_all_packages = lambda prune_missing=False: svc.load_packages()  # type: ignore[assignment]

    fixtures: List[dict] = [
        _pkg("ka-1", "katx-1.0.tgz", "1.0.0", "ka-tx",
             components=["tx-fpga", "tx-fw"], tags=["stable"],
             createdAt="2024-01-15T00:00:00Z"),
        _pkg("ka-2", "katx-2.0.tgz", "2.0.0", "ka-tx",
             components=["tx-fpga", "tx-fw", "tx-cal"], tags=["stable"],
             createdAt="2025-03-10T00:00:00Z"),
        _pkg("lx-1", "lx10-1.9.tgz", "1.9.0", "lingxi-10",
             components=["cucp", "cuup"], tags=["lts"],
             createdAt="2024-06-01T00:00:00Z"),
        _pkg("lx-2", "lx10-1.10.tgz", "1.10.0", "lingxi-10",
             components=["cucp", "cuup", "du"], tags=["lts"],
             createdAt="2024-12-20T00:00:00Z"),
        _pkg("lx-3", "lx10-2.0.tgz", "2.0.0", "lingxi-10",
             components=["cucp", "du"], tags=["edge"],
             createdAt="2025-04-05T00:00:00Z"),
        _pkg("lx-rc", "lx10-2.1rc1.tgz", "2.1.0rc1", "lingxi-10",
             components=["cucp", "du"], tags=["preview"],
             createdAt="2025-05-01T00:00:00Z"),
        _pkg("patch-1", "lx10-patch-2.0.1.tgz", "2.0.1", "lingxi-10",
             is_patch=True, components=["cucp"], tags=["patch"],
             createdAt="2025-04-20T00:00:00Z"),
    ]
    svc.save_packages(fixtures)

    # Point both the MCP tool dispatch and the agent's ID validation
    # path at this isolated service.
    import app.agents.package_search.mcp_tools as mcp_module
    import app.services.raven_package_service as svc_module

    monkeypatch.setattr(mcp_module, "_service", lambda: svc)
    monkeypatch.setattr(svc_module, "raven_package_service", svc)
    return svc


@pytest.fixture
def stub_options(monkeypatch):
    """Skip ClaudeAgentOptions construction so we don't touch real config."""
    def fake_build(self, *, system_prompt, project_code, cwd):
        return (object(), "fake-model", "fake-provider")
    monkeypatch.setattr(PackageSearchAgent, "_build_options", fake_build)


# ──────────────── helper: drive agent with one tool round-trip ────────────────


def _scripted_loop(
    tool_name: str,
    tool_input: dict,
    fenced_ids: List[str],
    project_code: str,
):
    """Build the messages for a single tool_use → tool_result → final answer.

    The MCP tool is invoked with the run's ``project_code`` — same
    server-side scoping the rebuilt agent applies via ``get_mcp_server``.
    """
    tool_payload = TOOL_CALLS[tool_name](tool_input, project_code=project_code)
    fenced = (
        "Here are the matches.\n"
        "```json\n"
        + json.dumps(
            {
                "recommended_package_ids": fenced_ids,
                "relevant_package_ids": fenced_ids,
                "notes": f"derived via {tool_name}",
            }
        )
        + "\n```\n"
    )
    return [
        _Message([
            _ToolUseBlock(name=f"mcp__package_search__{tool_name}",
                          tool_input=tool_input, block_id="tu1"),
        ]),
        _Message([
            _ToolResultBlock(
                tool_use_id="tu1",
                text=json.dumps(tool_payload),
            ),
        ]),
        _ResultMessage(fenced),
    ], tool_payload


def _build_agent(messages):
    agent = PackageSearchAgent()

    async def fake_loop(self, prompt, options):
        for m in messages:
            yield m

    agent._run_sdk_loop = fake_loop.__get__(agent, PackageSearchAgent)  # type: ignore[method-assign]
    return agent


def _run(agent: PackageSearchAgent, query: str, project_code: str) -> dict:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="pkgsearch-test-")
    ctx = WorkspaceContext(
        task_id="task-e2e",
        temp_dir=tmp,
        repo_dir=f"{tmp}/repo",
        task_json_path=f"{tmp}/task.json",
        project_code=project_code,
        metadata={"question": query, "hints": ""},
    )
    return asyncio.run(agent.run(ctx))


# ──────────────── the four scenarios from task 8.1 ────────────────


def test_query_category_name_substring(seeded_service, stub_options):
    """Name substring: 'katx' → both ka-tx packages (run bound to ka-tx)."""
    messages, payload = _scripted_loop(
        "search_packages_by_text",
        {"text": "katx"},
        fenced_ids=["ka-1", "ka-2"],
        project_code="ka-tx",
    )
    # Sanity: the MCP tool actually returned both ka-tx packages.
    returned_ids = {item["id"] for item in payload["items"]}
    assert returned_ids == {"ka-1", "ka-2"}

    result = _run(_build_agent(messages), "找一下名字带 katx 的包", "ka-tx")

    assert result["recommended_package_ids"] == ["ka-1", "ka-2"]
    assert result["relevant_package_ids"] == ["ka-1", "ka-2"]
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == []  # all IDs are real → no filtering


def test_query_category_version_range(seeded_service, stub_options):
    """Version range within project lingxi-10: ≥ 1.10.0 — SemVer comparison."""
    messages, payload = _scripted_loop(
        "filter_packages_by_version",
        {"version_min": "1.10.0"},
        fenced_ids=["lx-2", "lx-3"],
        project_code="lingxi-10",
    )
    returned_ids = {item["id"] for item in payload["items"]}
    # SemVer: 1.10.0 must be there, 1.9.0 must NOT (string compare would fail),
    # prerelease rc1 must NOT (default include_prerelease=false), patch IS counted
    # since 2.0.1 ≥ 1.10.0. Project scoping excludes the ka-tx packages.
    assert "lx-2" in returned_ids
    assert "lx-3" in returned_ids
    assert "lx-1" not in returned_ids
    assert "lx-rc" not in returned_ids
    assert "ka-2" not in returned_ids  # other project — scoped out server-side

    result = _run(_build_agent(messages),
                  "我要 v1.10.0 以上的非预发布版本", "lingxi-10")

    assert result["recommended_package_ids"] == ["lx-2", "lx-3"]
    assert result["relevant_package_ids"] == ["lx-2", "lx-3"]


def test_query_category_component(seeded_service, stub_options):
    """Component: find packages containing 'du' → lx-2, lx-3, lx-rc, patch-1."""
    messages, payload = _scripted_loop(
        "find_packages_by_component",
        {"component_name": "du"},
        fenced_ids=["lx-2", "lx-3"],
        project_code="lingxi-10",
    )
    returned_ids = {item["id"] for item in payload["items"]}
    assert "lx-2" in returned_ids
    assert "lx-3" in returned_ids
    # The fixture for lx-1 doesn't include "du", so it must not match.
    assert "lx-1" not in returned_ids

    result = _run(_build_agent(messages), "哪些包含 du 组件", "lingxi-10")

    assert result["recommended_package_ids"] == ["lx-2", "lx-3"]


def test_query_category_stats(seeded_service, stub_options):
    """Stats: group_by=isPatch within project lingxi-10 (type dimension removed)."""
    messages, payload = _scripted_loop(
        "package_stats",
        {"group_by": "isPatch"},
        fenced_ids=[],  # stats query yields no recommendation, just a summary
        project_code="lingxi-10",
    )
    groups = {g["key"]: g["count"] for g in payload["groups"]}
    assert groups["patch"] == 1  # patch-1
    # full (project-scoped) = lx-1, lx-2, lx-3, lx-rc
    assert groups["full"] == 4

    result = _run(_build_agent(messages), "按补丁类型分组统计包数量", "lingxi-10")

    # No recommendations expected for a pure-stats answer.
    assert result["recommended_package_ids"] == []
    assert result["relevant_package_ids"] == []
    # And no spurious warning — empty arrays are a valid answer.
    warnings = [e for e in result["tool_trace"] if e.get("type") == "warning"]
    assert warnings == []
