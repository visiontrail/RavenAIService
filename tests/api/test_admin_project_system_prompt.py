"""Integration tests for the project-level system prompt admin API.

Covers:
- GET /admin/project-repos/{project_code}/system-prompt
- PUT /admin/project-repos/{project_code}/system-prompt
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.api.admin import require_project_admin_by_code
from app.security.admin_dependency import AdminPrincipal


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(kind="legacy_admin", username="admin", is_global_admin=True)


@pytest.fixture()
def isolated_prompts_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(
        settings, "project_prompts_data_dir", str(tmp_path / "project_prompts")
    )
    return tmp_path


@pytest.fixture()
def app(isolated_prompts_dir) -> FastAPI:
    application = FastAPI()
    application.include_router(admin_api.router)
    application.dependency_overrides[require_project_admin_by_code] = _global_admin
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def no_auth_client(isolated_prompts_dir) -> TestClient:
    application = FastAPI()
    application.include_router(admin_api.router)
    return TestClient(application)


def test_get_unset(client: TestClient) -> None:
    resp = client.get("/admin/project-repos/myproj/system-prompt")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exists"] is False
    assert data["content"] == ""
    assert data["project_code"] == "myproj"


def test_put_then_get(client: TestClient) -> None:
    resp = client.put(
        "/admin/project-repos/myproj/system-prompt",
        json={"content": "项目规则：忽略 DEBUG 级别日志。"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["exists"] is True
    assert data["content"] == "项目规则：忽略 DEBUG 级别日志。"

    resp = client.get("/admin/project-repos/myproj/system-prompt")
    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == "项目规则：忽略 DEBUG 级别日志。"


def test_put_empty_clears(client: TestClient) -> None:
    client.put("/admin/project-repos/myproj/system-prompt", json={"content": "x"})
    resp = client.put("/admin/project-repos/myproj/system-prompt", json={"content": ""})
    assert resp.status_code == 200
    assert resp.json()["data"]["exists"] is False


def test_put_oversized_rejected(client: TestClient) -> None:
    from app.services import project_prompt_service as svc

    big = "x" * (svc.MAX_PROJECT_PROMPT_CHARS + 1)
    resp = client.put(
        "/admin/project-repos/myproj/system-prompt", json={"content": big}
    )
    assert resp.status_code == 422


def test_code_normalized(client: TestClient) -> None:
    client.put(
        "/admin/project-repos/MyProj/system-prompt", json={"content": "abc"}
    )
    # Lower-cased code resolves to the same stored prompt.
    resp = client.get("/admin/project-repos/myproj/system-prompt")
    assert resp.json()["data"]["content"] == "abc"


def test_auth_required(no_auth_client: TestClient) -> None:
    resp = no_auth_client.get("/admin/project-repos/myproj/system-prompt")
    assert resp.status_code in (401, 403, 422)


def test_agent_scoped_layer_roundtrip(client: TestClient) -> None:
    # Writing the project_expert layer must not leak into the shared layer.
    resp = client.put(
        "/admin/project-repos/myproj/system-prompt",
        params={"agent": "project_expert"},
        json={"content": "EXPERT-LAYER"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["agent_key"] == "project_expert"
    assert body["content"] == "EXPERT-LAYER"

    # Shared layer stays empty.
    shared = client.get("/admin/project-repos/myproj/system-prompt").json()["data"]
    assert shared["agent_key"] is None
    assert shared["exists"] is False

    # The agent layer reads back via the query param.
    again = client.get(
        "/admin/project-repos/myproj/system-prompt", params={"agent": "project_expert"}
    ).json()["data"]
    assert again["content"] == "EXPERT-LAYER"


def test_invalid_agent_rejected(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/myproj/system-prompt", params={"agent": "bogus"}
    )
    assert resp.status_code == 422
