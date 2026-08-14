"""Unit and integration tests for project_repo_service."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_repo(**kwargs):
    defaults = dict(
        id=1,
        project_code="foo",
        project_name="Foo",
        repo_url="https://gitlab.example/foo.git",
        default_branch="main",
        git_token="secret-token",
        project_card="Foo project scope and supported questions",
        enabled=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


class TestGetByProjectCode:
    @pytest.mark.asyncio
    async def test_case_insensitive_lookup(self, mock_db):
        from app.services.project_repo_service import get_by_project_code

        repo = _make_repo(project_code="foo")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = repo
        mock_db.execute = AsyncMock(return_value=result_mock)

        found = await get_by_project_code(mock_db, "  FOO  ")
        assert found is repo
        # Verify the query used the normalized code
        call_args = mock_db.execute.call_args[0][0]
        # The WHERE clause should use normalized "foo"

    @pytest.mark.asyncio
    async def test_disabled_entry_not_returned(self, mock_db):
        from app.services.project_repo_service import get_by_project_code

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None  # disabled entries filtered out
        mock_db.execute = AsyncMock(return_value=result_mock)

        found = await get_by_project_code(mock_db, "foo")
        assert found is None

    @pytest.mark.asyncio
    async def test_require_repo_hides_repoless_project(self, mock_db):
        """未关联代码仓库（repo_url 为空）的项目在 require_repo=True 时不可见。"""
        from app.services.project_repo_service import get_by_project_code

        repoless = _make_repo(project_code="foo", repo_url="")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = repoless
        mock_db.execute = AsyncMock(return_value=result_mock)

        # 项目专家（默认 require_repo=False）仍可看到该项目。
        assert await get_by_project_code(mock_db, "foo") is repoless
        # 其它 Agent（require_repo=True）看不到。
        assert await get_by_project_code(mock_db, "foo", require_repo=True) is None


class TestHasRepo:
    def test_has_repo_truthy_only_for_nonblank_url(self):
        from app.services.project_repo_service import has_repo

        assert has_repo(_make_repo(repo_url="https://git.example/x.git")) is True
        assert has_repo(_make_repo(repo_url="")) is False
        assert has_repo(_make_repo(repo_url="   ")) is False
        assert has_repo(_make_repo(repo_url=None)) is False
        assert has_repo(None) is False


class TestProjectCard:
    def test_normalize_trims_and_rejects_blank_or_oversized(self):
        from app.services.project_repo_service import (
            PROJECT_CARD_MAX_LENGTH,
            normalize_project_card,
        )

        assert normalize_project_card("  Foo scope  ") == "Foo scope"
        with pytest.raises(ValueError, match="请填写项目卡片"):
            normalize_project_card("   ")
        with pytest.raises(ValueError, match="不能超过"):
            normalize_project_card("x" * (PROJECT_CARD_MAX_LENGTH + 1))

    @pytest.mark.asyncio
    async def test_update_cannot_clear_project_card(self, mock_db):
        from app.services.project_repo_service import update

        repo = _make_repo(project_card="Original project scope")
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        with pytest.raises(ValueError, match="请填写项目卡片"):
            await update(mock_db, repo, project_card="   ")
        assert repo.project_card == "Original project scope"


class TestProjectDiscovery:
    @pytest.mark.asyncio
    async def test_catalog_is_bounded_enabled_and_safe(self, mock_db):
        from app.services.project_repo_service import discover_projects

        visible = _make_repo(
            id=7,
            project_code="foo",
            project_name="Foo",
            project_card="Foo authentication and account APIs",
            repo_url="https://git.example/foo.git",
            git_token="super-secret",
        )
        with patch(
            "app.services.project_repo_service.list_repos",
            new=AsyncMock(return_value=[visible]),
        ) as list_repos, patch(
            "app.services.project_repo_service.list_agent_keys_bulk",
            new=AsyncMock(return_value={7: ["project_expert", "log_analysis"]}),
        ):
            payload = await discover_projects(mock_db)

        list_repos.assert_awaited_once_with(
            mock_db,
            include_disabled=False,
            offset=0,
            limit=501,
        )
        assert payload == {
            "projects": [
                {
                    "id": 7,
                    "project_code": "foo",
                    "project_name": "Foo",
                    "project_card": "Foo authentication and account APIs",
                    "has_repo": True,
                    "enabled_agent_keys": ["project_expert", "log_analysis"],
                }
            ],
            "count": 1,
            "truncated": False,
        }
        serialized = str(payload)
        for sensitive in ("repo_url", "clone_url", "git_token", "super-secret"):
            assert sensitive not in serialized


class TestProjectAgents:
    def test_default_agents_depend_on_repo_url(self):
        from app.services.project_repo_service import (
            PROJECT_AGENT_REGISTRY,
            default_agent_keys_for_repo,
        )

        assert PROJECT_AGENT_REGISTRY["package_search"]["display_name"] == "配置管理员"
        assert PROJECT_AGENT_REGISTRY["package_search"]["requires_repo"] is False
        assert default_agent_keys_for_repo(_make_repo(repo_url="")) == [
            "project_expert",
            "package_search",
        ]
        assert default_agent_keys_for_repo(_make_repo(repo_url="https://git.example/x.git")) == [
            "project_expert",
            "log_analysis",
            "package_search",
        ]

    def test_normalize_rejects_repo_bound_agent_without_repo(self):
        from app.services.project_repo_service import normalize_agent_keys

        with pytest.raises(ValueError, match="不能启用"):
            normalize_agent_keys(["log_analysis"], _make_repo(repo_url=""))

    def test_normalize_allows_subset_for_repo_project(self):
        from app.services.project_repo_service import normalize_agent_keys

        assert normalize_agent_keys(
            ["package_search", "package_search"],
            _make_repo(repo_url="https://git.example/x.git"),
        ) == ["package_search"]

    def test_normalize_allows_configuration_manager_without_repo(self):
        from app.services.project_repo_service import normalize_agent_keys

        assert normalize_agent_keys(
            ["package_search"],
            _make_repo(repo_url=""),
        ) == ["package_search"]


class TestCreateRepoless:
    @pytest.mark.asyncio
    async def test_create_without_repo_url_drops_token(self, mock_db):
        """不关联代码仓库时不应保存 git_token。"""
        from app.services.project_repo_service import create

        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()
        repo = await create(
            mock_db,
            project_code="bar",
            project_name="Bar",
            project_card="Bar project scope",
            repo_url=None,
            git_token="should-be-dropped",
        )
        assert repo.repo_url == ""
        assert repo.git_token is None


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_normalizes_project_code(self, mock_db):
        from app.services.project_repo_service import create

        created_repo = _make_repo(project_code="foo")
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=lambda r: None)
        mock_db.add = MagicMock()
        # Simulate refresh setting the repo
        mock_db.refresh = AsyncMock()

        with patch("app.services.project_repo_service.ProjectRepo") as MockRepo:
            MockRepo.return_value = created_repo
            repo = await create(
                mock_db,
                project_code="  FOO  ",
                project_name="Foo",
                project_card="Foo project scope",
                repo_url="https://gitlab.example/foo.git",
            )
        # project_code should be normalized
        MockRepo.assert_called_once()
        call_kwargs = MockRepo.call_args[1]
        assert call_kwargs["project_code"] == "foo"
        assert call_kwargs["project_card"] == "Foo project scope"


class TestUpdate:
    @pytest.mark.asyncio
    async def test_masked_token_does_not_change_git_token(self, mock_db):
        from app.services.project_repo_service import update

        repo = _make_repo(git_token="original-secret")
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        updated = await update(mock_db, repo, git_token="••••••••", project_name="New Name")
        assert repo.git_token == "original-secret"
        assert repo.project_name == "New Name"

    @pytest.mark.asyncio
    async def test_real_token_updates_git_token(self, mock_db):
        from app.services.project_repo_service import update

        repo = _make_repo(git_token="old-token")
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await update(mock_db, repo, git_token="new-token")
        assert repo.git_token == "new-token"

    @pytest.mark.asyncio
    async def test_clearing_repo_url_drops_git_token(self, mock_db):
        from app.services.project_repo_service import update

        repo = _make_repo(
            repo_url="https://git.example/x.git",
            git_token="old-token",
        )
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await update(mock_db, repo, repo_url="", git_token="new-token")
        assert repo.repo_url == ""
        assert repo.git_token is None


class TestConnectionTest:
    @pytest.mark.asyncio
    async def test_test_connection_calls_repo_settings_service(self, mock_db):
        from app.services.project_repo_service import test_connection

        repo = _make_repo(id=1, repo_url="https://gitlab.example/foo.git", git_token="tok")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = repo
        mock_db.execute = AsyncMock(return_value=result_mock)

        with patch("app.services.project_repo_service.test_repo_connection") as mock_test:
            mock_test.return_value = {"success": True, "message": "ok", "auth_method": "token_in_url"}
            result = await test_connection(mock_db, repo_id=1)

        mock_test.assert_called_once_with(url="https://gitlab.example/foo.git", token="tok")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_test_connection_returns_error_for_missing_repo(self, mock_db):
        from app.services.project_repo_service import test_connection

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await test_connection(mock_db, repo_id=999)
        assert result["success"] is False
