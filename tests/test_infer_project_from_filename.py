"""Tests for filename-based project inference in app/api/logs.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInferProjectCodeFromFilename:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("stack_log_20240101.tar.gz", "stack"),
            ("STACK_dump.zip", "stack"),
            ("oam_antenna_capture.tar.gz", "oam_antenna"),
            ("om_only.zip", "oam_antenna"),
            ("stack_and_oam_full.tar.gz", "full"),
            ("unknown_data.zip", None),
            ("", None),
        ],
    )
    def test_known_and_unknown_patterns(self, filename, expected):
        from app.api.logs import _infer_project_code_from_filename

        assert _infer_project_code_from_filename(filename) == expected


class TestInferProjectFromFilename:
    @pytest.mark.asyncio
    async def test_matched_pattern_resolves_to_repo(self):
        from app.api import logs as logs_api

        repo = MagicMock()
        repo.project_code = "stack"
        db = MagicMock()

        with patch.object(
            logs_api.project_repo_service,
            "get_by_project_code",
            new=AsyncMock(return_value=repo),
        ) as mock_lookup:
            result = await logs_api.infer_project_from_filename(
                "stack_20240101.tar.gz", db
            )

        assert result is repo
        mock_lookup.assert_awaited_once_with(db, "stack")

    @pytest.mark.asyncio
    async def test_unknown_filename_returns_none_without_db_lookup(self):
        from app.api import logs as logs_api

        db = MagicMock()

        with patch.object(
            logs_api.project_repo_service,
            "get_by_project_code",
            new=AsyncMock(),
        ) as mock_lookup:
            result = await logs_api.infer_project_from_filename(
                "unknown_data.zip", db
            )

        assert result is None
        mock_lookup.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matched_code_without_enabled_entry_returns_none(self):
        from app.api import logs as logs_api

        db = MagicMock()

        with patch.object(
            logs_api.project_repo_service,
            "get_by_project_code",
            new=AsyncMock(return_value=None),
        ) as mock_lookup:
            result = await logs_api.infer_project_from_filename(
                "stack_20240101.tar.gz", db
            )

        assert result is None
        mock_lookup.assert_awaited_once_with(db, "stack")
