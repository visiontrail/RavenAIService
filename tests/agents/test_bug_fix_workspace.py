"""Tests for the bug-fix workspace source-log sync.

Verifies that when a bug-fix task carries a source log archive, ``prepare``
rebuilds the same ``logs/`` tree the log-analysis agent saw, and that a
missing/broken archive degrades gracefully (logs are auxiliary context and
must never fail the fix task).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.agents.bug_fix import workspace as bf_ws


def _make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("device/app.log", "ERROR boom\n")
        zf.writestr("metadata.json", json.dumps({"project_code": "foo"}))
    return path


def test_sync_source_logs_extracts_archive(tmp_path):
    archive = _make_zip(tmp_path / "upload.zip")
    temp_dir = tmp_path / "ws"
    temp_dir.mkdir()

    logs_dir = bf_ws._sync_source_logs(
        temp_dir,
        bug_fix_task_id="t-1",
        source_log_archive_path=str(archive),
        source_log_filename="upload.zip",
    )

    assert logs_dir == temp_dir / "logs"
    assert (logs_dir / "device" / "app.log").read_text() == "ERROR boom\n"
    assert (logs_dir / "metadata.json").exists()


def test_sync_source_logs_missing_archive_is_non_fatal(tmp_path):
    logs_dir = bf_ws._sync_source_logs(
        tmp_path,
        bug_fix_task_id="t-2",
        source_log_archive_path=str(tmp_path / "nope.zip"),
        source_log_filename=None,
    )
    assert logs_dir is None
    assert not (tmp_path / "logs").exists()


def test_sync_source_logs_none_path_skips(tmp_path):
    assert (
        bf_ws._sync_source_logs(
            tmp_path,
            bug_fix_task_id="t-3",
            source_log_archive_path=None,
            source_log_filename=None,
        )
        is None
    )


def test_sync_source_logs_extract_failure_is_non_fatal(tmp_path):
    bad = tmp_path / "corrupt.zip"
    bad.write_bytes(b"not a zip at all")
    logs_dir = bf_ws._sync_source_logs(
        tmp_path,
        bug_fix_task_id="t-4",
        source_log_archive_path=str(bad),
        source_log_filename=None,
    )
    assert logs_dir is None
    assert not (tmp_path / "logs").exists()


@pytest.fixture
def _fake_clone(monkeypatch):
    """Make git clone / git config no-ops that report success."""

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(cmd, **kwargs):
        # Mimic clone creating the target directory.
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return _Proc()

    monkeypatch.setattr(bf_ws.subprocess, "run", _run)


def test_prepare_records_logs_dir(tmp_path, monkeypatch, _fake_clone):
    monkeypatch.setattr(
        bf_ws.settings, "code_repo_clone_base_dir", str(tmp_path / "base")
    )
    archive = _make_zip(tmp_path / "upload.zip")

    ctx = bf_ws.prepare(
        bug_fix_task_id="t-5",
        repo_url="https://gitlab.example.com/foo/bar.git",
        default_branch="main",
        git_token=None,
        title="fix",
        summary="s",
        proposed_fixes=[{"title": "fix"}],
        source_log_id="log-1",
        source_log_archive_path=str(archive),
        source_log_filename="upload.zip",
    )
    try:
        assert ctx.logs_dir is not None
        assert (Path(ctx.logs_dir) / "device" / "app.log").exists()
        task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
        assert task_data["logs_dir"] == "logs"
    finally:
        bf_ws.cleanup(ctx)


def test_prepare_without_source_log(tmp_path, monkeypatch, _fake_clone):
    monkeypatch.setattr(
        bf_ws.settings, "code_repo_clone_base_dir", str(tmp_path / "base")
    )

    ctx = bf_ws.prepare(
        bug_fix_task_id="t-6",
        repo_url="https://gitlab.example.com/foo/bar.git",
        default_branch="main",
        git_token=None,
        title="fix",
        summary="s",
        proposed_fixes=[{"title": "fix"}],
    )
    try:
        assert ctx.logs_dir is None
        task_data = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
        assert task_data["logs_dir"] is None
    finally:
        bf_ws.cleanup(ctx)
