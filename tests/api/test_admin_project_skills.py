"""Integration tests for project-level skill admin API endpoints.

Covers CRUD operations, auth, and error cases for:
- GET    /admin/project-repos/{project_code}/skills
- POST   /admin/project-repos/{project_code}/skills
- PATCH  /admin/project-repos/{project_code}/skills/{skill_id}
- DELETE /admin/project-repos/{project_code}/skills/{skill_id}
- GET    /admin/project-repos/{project_code}/skills/{skill_id}/files
- GET    /admin/project-repos/{project_code}/skills/{skill_id}/file
"""

from __future__ import annotations

import io
import zipfile
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import admin as admin_api
from app.api.admin import require_project_admin_by_code
from app.security.admin_dependency import AdminPrincipal


def _global_admin() -> AdminPrincipal:
    return AdminPrincipal(kind="legacy_admin", username="admin", is_global_admin=True)


def _build_zip(members: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


_SKILL_MD = (
    "---\n"
    "name: test-skill\n"
    "description: A skill for testing\n"
    "---\n"
    "# Body\n"
    "Test body.\n"
).encode("utf-8")


@pytest.fixture()
def isolated_skills_dir(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "skills_data_dir", str(tmp_path / "agent_skills"))
    monkeypatch.setattr(settings, "project_skills_data_dir", str(tmp_path / "project_skills"))
    return tmp_path


@pytest.fixture()
def app(isolated_skills_dir) -> FastAPI:
    application = FastAPI()
    application.include_router(admin_api.router)
    application.dependency_overrides[require_project_admin_by_code] = _global_admin
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def no_auth_client(isolated_skills_dir) -> TestClient:
    """Client WITHOUT admin auth override — the auth dependency will reject."""
    application = FastAPI()
    application.include_router(admin_api.router)
    return TestClient(application)


# ─────────────────────── List ──────────────────────────


def test_list_empty(client: TestClient) -> None:
    resp = client.get("/admin/project-repos/myproj/skills")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ─────────────────────── Upload ────────────────────────


def test_upload_and_list(client: TestClient) -> None:
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    resp = client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("test-skill.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "test-skill"
    assert data["enabled"] is True

    resp = client.get("/admin/project-repos/myproj/skills")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_upload_non_zip_rejected(client: TestClient) -> None:
    resp = client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("bad.txt", b"not a zip", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_missing_skill_md(client: TestClient) -> None:
    zip_bytes = _build_zip({"README.md": b"# Nothing useful"})
    resp = client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("no-skill.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 422


def test_upload_conflict(client: TestClient) -> None:
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    resp = client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("first.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201

    resp = client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("second.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 409


def test_upload_overwrite(client: TestClient) -> None:
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("first.zip", zip_bytes, "application/zip")},
    )
    resp = client.post(
        "/admin/project-repos/myproj/skills?overwrite=true",
        files={"file": ("second.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201


# ─────────────────────── Patch (enable/disable) ───────


def _install_skill(client: TestClient, project_code: str = "myproj") -> str:
    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    resp = client.post(
        f"/admin/project-repos/{project_code}/skills",
        files={"file": ("test.zip", zip_bytes, "application/zip")},
    )
    return resp.json()["data"]["id"]


def test_patch_enable_disable(client: TestClient) -> None:
    skill_id = _install_skill(client)

    resp = client.patch(
        f"/admin/project-repos/myproj/skills/{skill_id}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False

    resp = client.patch(
        f"/admin/project-repos/myproj/skills/{skill_id}",
        json={"enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is True


def test_patch_not_found(client: TestClient) -> None:
    resp = client.patch(
        "/admin/project-repos/myproj/skills/nonexistent",
        json={"enabled": False},
    )
    assert resp.status_code == 404


# ─────────────────────── Delete ───────────────────────


def test_delete(client: TestClient) -> None:
    skill_id = _install_skill(client)
    resp = client.delete(f"/admin/project-repos/myproj/skills/{skill_id}")
    assert resp.status_code == 204

    resp = client.get("/admin/project-repos/myproj/skills")
    assert resp.json()["data"] == []


def test_delete_not_found(client: TestClient) -> None:
    resp = client.delete("/admin/project-repos/myproj/skills/nonexistent")
    assert resp.status_code == 404


# ─────────────────────── File browsing ────────────────


def test_list_files(client: TestClient) -> None:
    zip_bytes = _build_zip({
        "SKILL.md": _SKILL_MD,
        "scripts/run.sh": b"#!/bin/sh\n",
    })
    client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("test.zip", zip_bytes, "application/zip")},
    )
    resp = client.get("/admin/project-repos/myproj/skills/test-skill/files")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "test-skill"
    assert data["tree"]["type"] == "dir"


def test_list_files_not_found(client: TestClient) -> None:
    resp = client.get("/admin/project-repos/myproj/skills/nonexistent/files")
    assert resp.status_code == 404


def test_read_file(client: TestClient) -> None:
    zip_bytes = _build_zip({
        "SKILL.md": _SKILL_MD,
        "scripts/run.sh": b"#!/bin/sh\necho hello\n",
    })
    client.post(
        "/admin/project-repos/myproj/skills",
        files={"file": ("test.zip", zip_bytes, "application/zip")},
    )
    resp = client.get(
        "/admin/project-repos/myproj/skills/test-skill/file",
        params={"path": "scripts/run.sh"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "echo hello" in data["content"]


def test_read_file_not_found(client: TestClient) -> None:
    _install_skill(client)
    resp = client.get(
        "/admin/project-repos/myproj/skills/test-skill/file",
        params={"path": "nonexistent.txt"},
    )
    assert resp.status_code == 404


# ─────────────────────── Auth ────────────────────────


def test_auth_required(no_auth_client: TestClient) -> None:
    resp = no_auth_client.get("/admin/project-repos/myproj/skills")
    assert resp.status_code in (401, 403, 422)
