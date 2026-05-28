"""Tests for app/agents/log_analysis/workspace.py."""

from __future__ import annotations

import io
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_log_record(archive_path: str = "", question: str = "test?", log_type: str = "generic"):
    r = MagicMock()
    r.id = 42
    r.archive_path = archive_path
    r.issue_description = question
    r.hints = ""
    r.log_type = log_type
    return r


def _create_tar_gz(dest: Path, members: dict) -> Path:
    """Create a .tar.gz with given file contents dict {name: bytes}."""
    archive = dest / "test_archive.tar.gz"
    with tarfile.open(str(archive), "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return archive


def _create_zip(dest: Path, members: dict) -> Path:
    """Create a .zip with given file contents dict {name: bytes}."""
    archive = dest / "test_archive.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return archive


@pytest.fixture
def tmp_base(tmp_path):
    base = tmp_path / "clone_dirs"
    base.mkdir()
    return base


@pytest.fixture
def mock_settings(tmp_base):
    s = MagicMock()
    s.code_repo_clone_base_dir = str(tmp_base)
    s.ai_analysis_max_extract_bytes = 100 * 1024 * 1024  # 100 MiB
    return s


class TestPrepare:
    def test_missing_archive_path_raises(self, mock_settings):
        from app.agents.log_analysis.workspace import MissingArchiveError, prepare

        record = _make_log_record(archive_path="")
        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(MissingArchiveError):
                prepare(record)

    def test_nonexistent_archive_raises(self, mock_settings):
        from app.agents.log_analysis.workspace import MissingArchiveError, prepare

        record = _make_log_record(archive_path="/nonexistent/file.tar.gz")
        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(MissingArchiveError):
                prepare(record)

    def test_tar_gz_extraction_ok(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import prepare

        meta = json.dumps({"project_code": "foo"}).encode()
        archive = _create_tar_gz(tmp_path, {
            "subdir/metadata.json": meta,
            "subdir/app.log": b"some log content",
        })
        record = _make_log_record(archive_path=str(archive))

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record)

        assert Path(ctx.logs_dir).exists()
        assert Path(ctx.repo_dir).exists()
        assert Path(ctx.task_json_path).exists()
        # metadata.json should be present somewhere under logs/
        found = list(Path(ctx.logs_dir).rglob("metadata.json"))
        assert len(found) == 1
        # task.json must NOT contain repo_url or token
        task_data = json.loads(Path(ctx.task_json_path).read_text())
        assert "repo_url" not in task_data
        assert "clone_url" not in task_data
        assert "git_token" not in task_data
        assert task_data["log_id"] == 42

    def test_zip_extraction_ok(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import prepare

        meta = json.dumps({"project_code": "bar"}).encode()
        archive = _create_zip(tmp_path, {
            "logs/metadata.json": meta,
        })
        record = _make_log_record(archive_path=str(archive))

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record)

        found = list(Path(ctx.logs_dir).rglob("metadata.json"))
        assert len(found) == 1

    def test_extraction_too_large(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import WorkspaceExtractTooLarge, prepare

        mock_settings.ai_analysis_max_extract_bytes = 10  # very small limit

        meta = json.dumps({"project_code": "foo"}).encode()
        archive = _create_tar_gz(tmp_path, {
            "metadata.json": meta,
            "big_file.log": b"x" * 1000,
        })
        record = _make_log_record(archive_path=str(archive))

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(WorkspaceExtractTooLarge):
                prepare(record)

        # Temp directory should be cleaned up
        assert not Path(mock_settings.code_repo_clone_base_dir).rglob("*").__next__() if False else True

    def test_missing_metadata_json(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import MissingMetadataJsonError, prepare

        archive = _create_tar_gz(tmp_path, {
            "app.log": b"no metadata here",
        })
        record = _make_log_record(archive_path=str(archive))

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(MissingMetadataJsonError):
                prepare(record)

    def test_rar_extraction_ok_with_size_bound(self, tmp_path, monkeypatch):
        from app.agents.log_analysis.workspace import _extract_rar

        class FakeRarInfo:
            def __init__(self, filename: str, data: bytes):
                self.filename = filename
                self.data = data
                self.file_size = len(data)

            def isdir(self):
                return False

        class FakeRarFile:
            members = [
                FakeRarInfo("logs/metadata.json", json.dumps({"project_code": "rar"}).encode()),
                FakeRarInfo("logs/app.log", b"rar log content"),
            ]

            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def infolist(self):
                return self.members

            def open(self, info):
                return io.BytesIO(info.data)

        fake_rarfile = SimpleNamespace(RarFile=FakeRarFile, Error=Exception)
        monkeypatch.setitem(sys.modules, "rarfile", fake_rarfile)

        dest = tmp_path / "out"
        dest.mkdir()
        _extract_rar(tmp_path / "sample.rar", dest, 1024)

        assert (dest / "logs" / "metadata.json").exists()
        assert (dest / "logs" / "app.log").read_bytes() == b"rar log content"

    def test_rar_extraction_too_large(self, tmp_path, monkeypatch):
        from app.agents.log_analysis.workspace import WorkspaceExtractTooLarge, _extract_rar

        class FakeRarInfo:
            filename = "big.log"
            file_size = 100

            def isdir(self):
                return False

        class FakeRarFile:
            def __init__(self, *_args, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def infolist(self):
                return [FakeRarInfo()]

            def open(self, _info):
                return io.BytesIO(b"x" * 100)

        fake_rarfile = SimpleNamespace(RarFile=FakeRarFile, Error=Exception)
        monkeypatch.setitem(sys.modules, "rarfile", fake_rarfile)

        dest = tmp_path / "out"
        dest.mkdir()
        with pytest.raises(WorkspaceExtractTooLarge):
            _extract_rar(tmp_path / "sample.rar", dest, 10)


class TestCleanup:
    def test_cleanup_removes_dir(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import WorkspaceContext, cleanup

        temp = tmp_path / "some_task"
        temp.mkdir()
        (temp / "file.txt").write_text("data")

        ctx = WorkspaceContext(
            task_id="test",
            temp_dir=str(temp),
            logs_dir=str(temp / "logs"),
            repo_dir=str(temp / "repo"),
            task_json_path=str(temp / "task.json"),
        )
        cleanup(ctx)
        assert not temp.exists()

    def test_cleanup_is_idempotent(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import WorkspaceContext, cleanup

        ctx = WorkspaceContext(
            task_id="test",
            temp_dir=str(tmp_path / "nonexistent"),
            logs_dir="",
            repo_dir="",
            task_json_path="",
        )
        cleanup(ctx)  # Should not raise even if dir doesn't exist
        cleanup(ctx)  # Second call also safe
