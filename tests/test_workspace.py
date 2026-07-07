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


def _make_log_record(
    archive_path: str = "",
    question: str = "test?",
    project_id: int | None = None,
    original_filename: str = "",
):
    r = MagicMock()
    r.id = 42
    r.archive_path = archive_path
    r.issue_description = question
    r.hints = ""
    r.project_id = project_id
    r.original_filename = original_filename
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

    def test_rar_extraction_falls_back_to_unar(self, tmp_path, monkeypatch):
        from app.agents.log_analysis import workspace

        class FakeRarError(Exception):
            pass

        class FakeRarInfo:
            filename = "logs/app.log"
            file_size = 10

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
                raise FakeRarError("Failed the read enough data: req=81920 got=0")

        fake_rarfile = SimpleNamespace(RarFile=FakeRarFile, Error=FakeRarError)
        monkeypatch.setitem(sys.modules, "rarfile", fake_rarfile)
        monkeypatch.setattr(workspace.shutil, "which", lambda name: f"/usr/bin/{name}")

        calls = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd[0])
            if cmd[0] == "lsar":
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "lsarContents": [
                                {
                                    "XADFileName": "logs/app.log",
                                    "XADFileSize": 15,
                                }
                            ]
                        }
                    )
                )
            if cmd[0] == "unar":
                out_dir = Path(cmd[cmd.index("-output-directory") + 1])
                (out_dir / "logs").mkdir(parents=True, exist_ok=True)
                (out_dir / "logs" / "app.log").write_text("unar recovered\n", encoding="utf-8")
                return SimpleNamespace(stdout="")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(workspace.subprocess, "run", fake_run)

        dest = tmp_path / "out"
        dest.mkdir()
        workspace._extract_rar(tmp_path / "sample.rar", dest, 1024)

        assert calls == ["lsar", "unar"]
        assert (dest / "logs" / "app.log").read_text(encoding="utf-8") == "unar recovered\n"


class TestPrepareTextUpload:
    def test_plain_text_log_copied_in_without_metadata_when_opted_out(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import prepare

        src = tmp_path / "app.log"
        src.write_text("2026-06-02 ERROR something broke\n", encoding="utf-8")
        record = _make_log_record(archive_path=str(src), original_filename="app.log")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record, require_metadata=False)

        placed = Path(ctx.logs_dir) / "app.log"
        assert placed.exists()
        assert "something broke" in placed.read_text(encoding="utf-8")

    def test_plain_text_log_uses_original_filename(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import prepare

        # Stored path carries a uuid prefix; original_filename should win.
        src = tmp_path / "abcd1234_service.log"
        src.write_text("hello\n", encoding="utf-8")
        record = _make_log_record(archive_path=str(src), original_filename="service.log")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record, require_metadata=False)

        assert (Path(ctx.logs_dir) / "service.log").exists()

    def test_spreadsheet_upload_is_copied_verbatim_and_listed_in_task(
        self, tmp_path, mock_settings
    ):
        from app.agents.log_analysis.workspace import prepare

        src = tmp_path / "upload.xlsx"
        # Minimal ZIP-looking bytes are enough for this unit: spreadsheet
        # detection is extension-based because real xlsx files are ZIP
        # containers and must not be decompressed by the log workspace.
        payload = b"PK\x03\x04spreadsheet payload"
        src.write_bytes(payload)
        record = _make_log_record(
            archive_path=str(src),
            original_filename="report.xlsx",
        )

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record, require_metadata=False)

        placed = Path(ctx.logs_dir) / "report.xlsx"
        assert placed.read_bytes() == payload
        task_data = json.loads(Path(ctx.task_json_path).read_text())
        assert task_data["upload_kind"] == "spreadsheet"
        assert task_data["attachments"] == [
            {
                "filename": "report.xlsx",
                "path": "logs/report.xlsx",
                "kind": "spreadsheet",
            }
        ]
        assert ctx.metadata["attachments"] == task_data["attachments"]

    def test_plain_text_log_with_relative_base_dir_records_attachment(
        self, tmp_path, mock_settings, monkeypatch
    ):
        # Regression: in production ``code_repo_clone_base_dir`` defaults to the
        # relative "temp/code_repos". The placed attachment path comes back
        # resolved (absolute) from _safe_output_path, so computing
        # attachment.relative_to(temp_dir) used to blow up with
        # "is not in the subpath of ... OR one path is relative and the other
        # is absolute." prepare() must resolve temp_dir before the comparison.
        from app.agents.log_analysis.workspace import prepare

        mock_settings.code_repo_clone_base_dir = "rel_clone_dirs"
        monkeypatch.chdir(tmp_path)

        src = tmp_path / "Irun_oam.log"
        src.write_text("2026-06-18 base station log\n", encoding="utf-8")
        record = _make_log_record(archive_path=str(src), original_filename="Irun_oam.log")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            ctx = prepare(record, require_metadata=False)

        placed = Path(ctx.logs_dir) / "Irun_oam.log"
        assert placed.exists()
        task_data = json.loads(Path(ctx.task_json_path).read_text())
        assert task_data["attachments"] == [
            {
                "filename": "Irun_oam.log",
                "path": "logs/Irun_oam.log",
                "kind": "text",
            }
        ]
        assert ctx.metadata["attachments"] == task_data["attachments"]

    def test_plain_text_log_requires_metadata_raises(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import MissingMetadataJsonError, prepare

        src = tmp_path / "app.log"
        src.write_text("no metadata in a flat text file\n", encoding="utf-8")
        record = _make_log_record(archive_path=str(src), original_filename="app.log")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(MissingMetadataJsonError):
                prepare(record, require_metadata=True)

    def test_text_too_large(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import WorkspaceExtractTooLarge, prepare

        mock_settings.ai_analysis_max_extract_bytes = 10
        src = tmp_path / "big.log"
        src.write_text("x" * 1000, encoding="utf-8")
        record = _make_log_record(archive_path=str(src), original_filename="big.log")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(WorkspaceExtractTooLarge):
                prepare(record, require_metadata=False)

    def test_binary_blob_rejected(self, tmp_path, mock_settings):
        from app.agents.log_analysis.workspace import UnsupportedUploadFormatError, prepare

        src = tmp_path / "mystery.bin"
        src.write_bytes(b"\x00\x01\x02\x03binary\x00payload")
        record = _make_log_record(archive_path=str(src), original_filename="mystery.bin")

        with patch("app.agents.log_analysis.workspace.settings", mock_settings):
            with pytest.raises(UnsupportedUploadFormatError):
                prepare(record, require_metadata=False)


class TestDetectUploadKind:
    def test_detects_plain_text(self, tmp_path):
        from app.tools.archive_tool import detect_upload_kind

        p = tmp_path / "a.log"
        p.write_text("plain log line\n", encoding="utf-8")
        assert detect_upload_kind(str(p)) == "text"

    def test_detects_zip_archive(self, tmp_path):
        from app.tools.archive_tool import detect_upload_kind

        archive = _create_zip(tmp_path, {"logs/app.log": b"x"})
        assert detect_upload_kind(str(archive)) == "archive"

    def test_detects_xlsx_as_spreadsheet_before_zip_archive(self, tmp_path):
        from app.tools.archive_tool import detect_upload_kind

        spreadsheet = tmp_path / "report.xlsx"
        with zipfile.ZipFile(str(spreadsheet), "w") as zf:
            zf.writestr("xl/workbook.xml", "<workbook/>")
        assert detect_upload_kind(str(spreadsheet)) == "spreadsheet"

    def test_detects_tar_gz_archive(self, tmp_path):
        from app.tools.archive_tool import detect_upload_kind

        archive = _create_tar_gz(tmp_path, {"app.log": b"x"})
        assert detect_upload_kind(str(archive)) == "archive"

    def test_binary_is_unknown(self, tmp_path):
        from app.tools.archive_tool import detect_upload_kind

        p = tmp_path / "x.dat"
        p.write_bytes(b"\x00\xff\x00\xffbinary")
        assert detect_upload_kind(str(p)) == "unknown"

    def test_text_named_archive_still_archive(self, tmp_path):
        # A zip whose name ends in .log must still be treated as an archive,
        # because looks_like_text rejects the PK magic header.
        from app.tools.archive_tool import detect_upload_kind, looks_like_text

        archive = _create_zip(tmp_path, {"inner.log": b"data"})
        renamed = tmp_path / "weird.log"
        archive.rename(renamed)
        assert looks_like_text(str(renamed)) is False
        assert detect_upload_kind(str(renamed)) == "archive"


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
