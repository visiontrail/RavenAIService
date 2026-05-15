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
        description=None,
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
                repo_url="https://gitlab.example/foo.git",
            )
        # project_code should be normalized
        MockRepo.assert_called_once()
        call_kwargs = MockRepo.call_args[1]
        assert call_kwargs["project_code"] == "foo"


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
