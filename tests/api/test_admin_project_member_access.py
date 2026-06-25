"""Integration tests for project-member admin access.

Covers the constrained admin surface introduced by the
``project-member-admin-access`` change:

* ``GET /admin/auth/me`` access-level reporting (5.1)
* project repo scoped list/read/update/test-connection + forbidden global
  actions (5.2)
* project-level system prompt read/update scope (5.3)
* project Skill API access scope (5.4)

These tests use *real* user bearer tokens (no dependency overrides) so the full
authorization chain — including project membership lookups — is exercised.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import admin as admin_api
from app.models.database import Base, get_db
from app.models.project_repo import ProjectRepo, ProjectRepoMember
from app.models.user import User
from app.security.admin_auth import auth_manager as admin_auth_manager
from app.security.user_auth import user_auth_manager


_SKILL_MD = (
    "---\n"
    "name: test-skill\n"
    "description: A skill for testing\n"
    "---\n"
    "# Body\nTest body.\n"
).encode("utf-8")


def _build_zip(members: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    from app.config import settings

    monkeypatch.setattr(settings, "skills_data_dir", str(tmp_path / "agent_skills"))
    monkeypatch.setattr(
        settings, "project_skills_data_dir", str(tmp_path / "project_skills")
    )
    monkeypatch.setattr(
        settings, "project_prompts_data_dir", str(tmp_path / "project_prompts")
    )
    # Ensure the legacy admin token manager has no configured users so user
    # tokens fall through to user-token resolution deterministically.
    monkeypatch.setattr(admin_auth_manager, "_users", [])

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pm_access.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    state: dict[str, object] = {}

    async def _seed() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            admin = User(
                id="admin-id", username="admin", password_hash="x", role="admin"
            )
            member = User(
                id="member-id", username="mallory", password_hash="x", role="user"
            )
            outsider = User(
                id="outsider-id", username="olivia", password_hash="x", role="user"
            )
            alpha = ProjectRepo(
                project_code="alpha", project_name="Alpha", repo_url="", enabled=True
            )
            beta = ProjectRepo(
                project_code="beta", project_name="Beta", repo_url="", enabled=True
            )
            session.add_all([admin, member, outsider, alpha, beta])
            await session.flush()
            session.add(
                ProjectRepoMember(project_repo_id=alpha.id, user_id=member.id)
            )
            await session.flush()
            state["alpha_id"] = alpha.id
            state["beta_id"] = beta.id
            await session.commit()

    asyncio.run(_seed())

    async def _get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = FastAPI()
    application.include_router(admin_api.router)
    application.dependency_overrides[get_db] = _get_db

    state["admin_token"] = user_auth_manager.issue_token("admin-id", "admin")[0]
    state["member_token"] = user_auth_manager.issue_token("member-id", "mallory")[0]
    state["outsider_token"] = user_auth_manager.issue_token("outsider-id", "olivia")[0]

    with TestClient(application) as test_client:
        test_client.seed_state = state
        yield test_client

    asyncio.run(engine.dispose())


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────── 5.1 auth/me ───────────────────────────


def test_me_global_admin(client: TestClient) -> None:
    resp = client.get("/admin/auth/me", headers=_h(client.seed_state["admin_token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["access_level"] == "global_admin"
    assert "users" in data["allowed_nav_keys"]
    assert "project-repos" in data["allowed_nav_keys"]


def test_me_project_member(client: TestClient) -> None:
    resp = client.get("/admin/auth/me", headers=_h(client.seed_state["member_token"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["access_level"] == "project_member"
    assert data["allowed_nav_keys"] == ["project-repos"]
    assert data["allowed_project_codes"] == ["alpha"]
    assert data["allowed_project_ids"] == [client.seed_state["alpha_id"]]


def test_me_user_without_membership_forbidden(client: TestClient) -> None:
    resp = client.get("/admin/auth/me", headers=_h(client.seed_state["outsider_token"]))
    assert resp.status_code == 403, resp.text


def test_me_unauthenticated(client: TestClient) -> None:
    resp = client.get("/admin/auth/me")
    assert resp.status_code == 401, resp.text


# ─────────────────────── 5.2 project repos ─────────────────────────


def test_member_lists_only_member_projects(client: TestClient) -> None:
    resp = client.get("/admin/project-repos", headers=_h(client.seed_state["member_token"]))
    assert resp.status_code == 200, resp.text
    codes = {item["project_code"] for item in resp.json()["data"]}
    assert codes == {"alpha"}


def test_global_admin_lists_all_projects(client: TestClient) -> None:
    resp = client.get("/admin/project-repos", headers=_h(client.seed_state["admin_token"]))
    assert resp.status_code == 200, resp.text
    codes = {item["project_code"] for item in resp.json()["data"]}
    assert {"alpha", "beta"} <= codes


def test_member_reads_member_project(client: TestClient) -> None:
    resp = client.get(
        f"/admin/project-repos/{client.seed_state['alpha_id']}",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["project_code"] == "alpha"


def test_member_cannot_read_non_member_project(client: TestClient) -> None:
    resp = client.get(
        f"/admin/project-repos/{client.seed_state['beta_id']}",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_member_updates_allowed_fields(client: TestClient) -> None:
    resp = client.put(
        f"/admin/project-repos/{client.seed_state['alpha_id']}",
        headers=_h(client.seed_state["member_token"]),
        json={
            "project_name": "Alpha Renamed",
            "description": "Updated",
            "default_branch": "develop",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["project_name"] == "Alpha Renamed"
    assert data["default_branch"] == "develop"


def test_member_cannot_update_restricted_fields(client: TestClient) -> None:
    resp = client.put(
        f"/admin/project-repos/{client.seed_state['alpha_id']}",
        headers=_h(client.seed_state["member_token"]),
        json={"enabled": False},
    )
    assert resp.status_code == 403, resp.text

    resp = client.put(
        f"/admin/project-repos/{client.seed_state['alpha_id']}",
        headers=_h(client.seed_state["member_token"]),
        json={"git_token": "secret"},
    )
    assert resp.status_code == 403, resp.text


def test_member_cannot_create_or_delete(client: TestClient) -> None:
    resp = client.post(
        "/admin/project-repos",
        headers=_h(client.seed_state["member_token"]),
        json={"project_code": "delta", "project_name": "Delta"},
    )
    assert resp.status_code == 403, resp.text

    resp = client.delete(
        f"/admin/project-repos/{client.seed_state['alpha_id']}",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 403, resp.text


def test_member_test_connection_allowed(client: TestClient) -> None:
    resp = client.post(
        f"/admin/project-repos/{client.seed_state['alpha_id']}/test-connection",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 200, resp.text
    # No raw token ever leaks in the structured result.
    assert "git_token" not in resp.json()["data"]


def test_member_test_connection_non_member_404(client: TestClient) -> None:
    resp = client.post(
        f"/admin/project-repos/{client.seed_state['beta_id']}/test-connection",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_member_cannot_access_global_endpoints(client: TestClient) -> None:
    # Member management is global-admin-only.
    resp = client.get(
        f"/admin/project-repos/{client.seed_state['alpha_id']}/members",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 403, resp.text
    # Prompts config is global-admin-only.
    resp = client.get(
        "/admin/prompts/config", headers=_h(client.seed_state["member_token"])
    )
    assert resp.status_code == 403, resp.text


# ─────────────────── 5.3 project system prompt ─────────────────────


def test_member_reads_and_updates_own_prompt(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/alpha/system-prompt",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 200, resp.text

    resp = client.put(
        "/admin/project-repos/alpha/system-prompt",
        headers=_h(client.seed_state["member_token"]),
        json={"content": "Project alpha extra prompt"},
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(
        "/admin/project-repos/alpha/system-prompt",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.json()["data"]["content"] == "Project alpha extra prompt"


def test_member_cannot_access_non_member_prompt(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/beta/system-prompt",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 404, resp.text

    resp = client.put(
        "/admin/project-repos/beta/system-prompt",
        headers=_h(client.seed_state["member_token"]),
        json={"content": "nope"},
    )
    assert resp.status_code == 404, resp.text


def test_global_admin_manages_any_prompt(client: TestClient) -> None:
    resp = client.put(
        "/admin/project-repos/beta/system-prompt",
        headers=_h(client.seed_state["admin_token"]),
        json={"content": "beta prompt"},
    )
    assert resp.status_code == 200, resp.text


# ─────────────────────── 5.4 project skills ────────────────────────


def test_member_lists_and_uploads_own_skills(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/alpha/skills",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []

    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    resp = client.post(
        "/admin/project-repos/alpha/skills",
        headers=_h(client.seed_state["member_token"]),
        files={"file": ("test-skill.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 201, resp.text


def test_member_cannot_access_non_member_skills(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/beta/skills",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 404, resp.text

    zip_bytes = _build_zip({"SKILL.md": _SKILL_MD})
    resp = client.post(
        "/admin/project-repos/beta/skills",
        headers=_h(client.seed_state["member_token"]),
        files={"file": ("test-skill.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 404, resp.text
    # The rejected write must not have created the beta project skill listing.
    resp = client.get(
        "/admin/project-repos/beta/skills",
        headers=_h(client.seed_state["admin_token"]),
    )
    assert resp.json()["data"] == []


def test_member_unknown_project_skills_404(client: TestClient) -> None:
    resp = client.get(
        "/admin/project-repos/ghost/skills",
        headers=_h(client.seed_state["member_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_global_admin_unknown_project_skills_ok(client: TestClient) -> None:
    # Global admins keep pre-provisioning behavior for unknown project codes.
    resp = client.get(
        "/admin/project-repos/ghost/skills",
        headers=_h(client.seed_state["admin_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []


def test_skills_unauthenticated(client: TestClient) -> None:
    resp = client.get("/admin/project-repos/alpha/skills")
    assert resp.status_code == 401, resp.text
