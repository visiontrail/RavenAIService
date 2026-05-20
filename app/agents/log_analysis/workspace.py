"""
日志分析工作区准备与清理。

职责：
- 为每个 Celery 任务在隔离临时目录下解压日志归档
- 创建 task.json（仅含非敏感字段）
- 解压大小保护（ai_analysis_max_extract_bytes）
- 任务结束后幂等清理临时目录
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────── Exceptions ────────────────────────────────

class WorkspaceError(Exception):
    """工作区相关错误基类。"""


class WorkspaceExtractTooLarge(WorkspaceError):
    """解压总大小超出限制。"""


class MissingArchiveError(WorkspaceError):
    """LogRecord 缺少 archive_path 字段或文件不存在。"""


class MissingMetadataJsonError(WorkspaceError):
    """解压后的 logs/ 树中找不到 metadata.json。"""


# ─────────────────────── Data Structures ───────────────────────────

@dataclass
class WorkspaceContext:
    task_id: str
    temp_dir: str           # 绝对路径，如 /base/clone_dirs/<task_id>/
    logs_dir: str           # temp_dir/logs/
    repo_dir: str           # temp_dir/repo/
    task_json_path: str     # temp_dir/task.json
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────── Helpers ───────────────────────────────────

def _find_metadata_json(logs_dir: Path) -> Optional[Path]:
    """在 logs/ 树中查找第一个 metadata.json（任意子目录）。"""
    for p in logs_dir.rglob("metadata.json"):
        return p
    return None


def _extract_tar(archive_path: Path, dest: Path, max_bytes: int) -> None:
    extracted = 0
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            extracted += member.size
            if extracted > max_bytes:
                raise WorkspaceExtractTooLarge(
                    f"Extraction aborted: cumulative size {extracted} bytes "
                    f"exceeds limit {max_bytes} bytes"
                )
            tf.extract(member, path=dest, set_attrs=False)


def _extract_zip(archive_path: Path, dest: Path, max_bytes: int) -> None:
    extracted = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            extracted += info.file_size
            if extracted > max_bytes:
                raise WorkspaceExtractTooLarge(
                    f"Extraction aborted: cumulative size {extracted} bytes "
                    f"exceeds limit {max_bytes} bytes"
                )
            zf.extract(info, path=dest)


def _extract_7z(archive_path: Path, dest: Path, max_bytes: int) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise WorkspaceError("py7zr is required to extract .7z archives") from exc

    extracted = 0
    with py7zr.SevenZipFile(archive_path, mode="r") as sz:
        for name, bio in sz.read().items():
            if bio is None:
                continue
            data = bio.read()
            extracted += len(data)
            if extracted > max_bytes:
                raise WorkspaceExtractTooLarge(
                    f"Extraction aborted: cumulative size {extracted} bytes "
                    f"exceeds limit {max_bytes} bytes"
                )
            out = dest / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)


def _extract_archive(archive_path: Path, dest: Path, max_bytes: int) -> None:
    suffix = "".join(archive_path.suffixes).lower()
    if suffix in (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar"):
        _extract_tar(archive_path, dest, max_bytes)
    elif suffix == ".zip":
        _extract_zip(archive_path, dest, max_bytes)
    elif suffix == ".7z":
        _extract_7z(archive_path, dest, max_bytes)
    elif archive_path.suffix.lower() in (".gz", ".tgz"):
        _extract_tar(archive_path, dest, max_bytes)
    else:
        # Fallback: try tarfile then zipfile
        try:
            _extract_tar(archive_path, dest, max_bytes)
        except tarfile.TarError:
            _extract_zip(archive_path, dest, max_bytes)


# ─────────────────────── Public API ────────────────────────────────

def prepare(log_record: Any, *, require_metadata: bool = True) -> WorkspaceContext:
    """准备任务工作区：解压日志归档，创建 task.json，不包含仓库 URL / token。

    Args:
        log_record: LogRecord ORM 对象（含 id, archive_path, question 等字段）
        require_metadata: 是否强制要求归档内包含 metadata.json。当调用方
            已经通过其它方式（如显式选择项目仓库）提供项目身份时，可置为
            False 以跳过该校验。

    Returns:
        WorkspaceContext

    Raises:
        MissingArchiveError: archive_path 为空或文件不存在
        WorkspaceExtractTooLarge: 解压超限
        MissingMetadataJsonError: require_metadata=True 且解压后找不到 metadata.json
    """
    from app.config import settings

    archive_path_str = getattr(log_record, "archive_path", None) or getattr(log_record, "file_path", None)
    if not archive_path_str:
        raise MissingArchiveError(
            f"LogRecord id={getattr(log_record, 'id', '?')} has no archive_path"
        )

    archive_path = Path(archive_path_str)
    if not archive_path.exists():
        raise MissingArchiveError(
            f"Archive file not found: {archive_path}"
        )

    task_id = str(uuid.uuid4())
    base_dir = Path(settings.code_repo_clone_base_dir)
    temp_dir = base_dir / task_id
    logs_dir = temp_dir / "logs"
    repo_dir = temp_dir / "repo"

    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        repo_dir.mkdir(parents=True, exist_ok=True)

        # Extract archive into logs/
        max_bytes = settings.ai_analysis_max_extract_bytes
        try:
            _extract_archive(archive_path, logs_dir, max_bytes)
        except WorkspaceExtractTooLarge:
            shutil.rmtree(str(logs_dir), ignore_errors=True)
            raise

        # Verify metadata.json exists (unless caller opted out)
        if require_metadata:
            meta_path = _find_metadata_json(logs_dir)
            if meta_path is None:
                raise MissingMetadataJsonError(
                    f"No metadata.json found under {logs_dir}"
                )

        # Write task.json with non-sensitive fields only
        task_data = {
            "log_id": getattr(log_record, "id", None),
            "question": getattr(log_record, "issue_description", None) or getattr(log_record, "question", None) or "",
            "hints": getattr(log_record, "hints", None) or "",
            "log_type": getattr(log_record, "log_type", None),
        }
        task_json_path = temp_dir / "task.json"
        task_json_path.write_text(json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info(
            "Workspace prepared: task_id=%s temp_dir=%s archive=%s",
            task_id, temp_dir, archive_path,
        )
        return WorkspaceContext(
            task_id=task_id,
            temp_dir=str(temp_dir),
            logs_dir=str(logs_dir),
            repo_dir=str(repo_dir),
            task_json_path=str(task_json_path),
        )

    except (MissingArchiveError, WorkspaceExtractTooLarge, MissingMetadataJsonError):
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        raise


def cleanup(ctx: WorkspaceContext) -> None:
    """幂等删除临时工作区目录。"""
    temp = Path(ctx.temp_dir)
    if temp.exists():
        shutil.rmtree(str(temp), ignore_errors=True)
        logger.info("Workspace cleaned up: %s", ctx.temp_dir)
