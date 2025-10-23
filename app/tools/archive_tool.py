"""
Archive extraction tool with safe decompression and nested archive handling.
Outputs tree/XML to support AI log analysis decisions.
"""
import os
import tarfile
import zipfile
import uuid
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.agents.xml_utils import wrap_file_list, wrap_metadata, wrap_document
from app.tools.fs_tools import safe_listdir

SUPPORTED_ARCHIVE_EXTS = {".tar.gz", ".tgz", ".zip"}


def _is_in_allowed_root(path: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(settings.agent_root_dir)
        return os.path.commonpath([abs_path, abs_root]) == abs_root
    except Exception:
        return False


def _guess_archive_type(path: str) -> Optional[str]:
    if path.endswith((".tar.gz", ".tgz")):
        return "tar"
    if path.endswith(".zip"):
        return "zip"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
        if zipfile.is_zipfile(path):
            return "zip"
    except Exception:
        pass
    return None


def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def _safe_join(base: str, *paths: str) -> str:
    candidate = os.path.abspath(os.path.join(base, *paths))
    base_abs = os.path.abspath(base)
    if os.path.commonpath([candidate, base_abs]) != base_abs:
        raise PermissionError(f"Unsafe path detected: {candidate}")
    return candidate


def _safe_extract_tar(src: str, dest: str) -> None:
    with tarfile.open(src, mode="r:*") as tf:
        for m in tf.getmembers():
            # skip dirs, symlinks, device files
            if m.isdev() or m.issym() or m.ischr() or m.isfifo():
                continue
            target = _safe_join(dest, m.name)
            if m.isdir():
                _ensure_dir(target)
                continue
            parent = os.path.dirname(target)
            _ensure_dir(parent)
            f = tf.extractfile(m)
            if f is None:
                continue
            with open(target, "wb") as out:
                out.write(f.read())


def _safe_extract_zip(src: str, dest: str) -> None:
    with zipfile.ZipFile(src, mode="r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                # directory
                _ensure_dir(_safe_join(dest, name))
                continue
            target = _safe_join(dest, name)
            parent = os.path.dirname(target)
            _ensure_dir(parent)
            with zf.open(name) as f, open(target, "wb") as out:
                out.write(f.read())


def compute_extract_root(archive_path: str) -> str:
    base = os.path.basename(archive_path)
    name = base.replace(".tar.gz", "").replace(".tgz", "").replace(".zip", "")
    unique = uuid.uuid4().hex[:8]
    extract_base = os.path.join(settings.agent_root_dir, "_extracted")
    _ensure_dir(extract_base)
    return os.path.join(extract_base, f"{name}-{unique}")


def safe_extract_archive(archive_path: str, dest_root: Optional[str] = None) -> str:
    if not settings.agent_enabled:
        raise RuntimeError("Agent disabled by configuration")
    if not _is_in_allowed_root(archive_path):
        raise PermissionError(f"Archive outside allowed root: {archive_path}")
    if not os.path.exists(archive_path):
        raise FileNotFoundError(archive_path)

    a_type = _guess_archive_type(archive_path)
    if a_type is None:
        raise ValueError("Unsupported archive format")

    dest = dest_root or compute_extract_root(archive_path)
    _ensure_dir(dest)

    if a_type == "tar":
        _safe_extract_tar(archive_path, dest)
    else:
        _safe_extract_zip(archive_path, dest)

    return dest


def list_tree_xml(root_dir: str, max_depth: int = 2) -> str:
    files = safe_listdir(root=root_dir, include_glob=None, max_depth=max_depth)
    return wrap_file_list(files, source=root_dir)


def find_nested_archives(root_dir: str) -> List[Dict[str, str]]:
    nested: List[Dict[str, str]] = []
    for d, _, files in os.walk(root_dir):
        for f in files:
            path = os.path.join(d, f)
            if any(f.endswith(ext) for ext in SUPPORTED_ARCHIVE_EXTS):
                try:
                    st = os.stat(path)
                    nested.append({
                        "path": path,
                        "size": str(st.st_size),
                        "modified": str(int(st.st_mtime))
                    })
                except Exception:
                    continue
    return nested


def nested_archives_xml(root_dir: str) -> str:
    files = find_nested_archives(root_dir)
    return wrap_document(wrap_file_list(files, source="nested_archives"), {"type": "nested_archives"})


def extract_nested_archive_xml(nested_path: str, parent_root: Optional[str] = None) -> Tuple[str, str]:
    if not _is_in_allowed_root(nested_path):
        raise PermissionError(f"Nested archive outside allowed root: {nested_path}")
    dest = safe_extract_archive(nested_path, dest_root=None)
    xml = wrap_document(list_tree_xml(dest, max_depth=2), {"extracted": dest, "source": os.path.basename(nested_path)})
    return dest, xml


def auto_extract_archive_xml(archive_path: str) -> Tuple[str, str]:
    """Extract top-level archive and return (extracted_dir, xml)."""
    dest = safe_extract_archive(archive_path)
    tree_xml = list_tree_xml(dest, max_depth=2)
    meta_xml = wrap_metadata({"archive_path": archive_path, "extracted_dir": dest})
    return dest, wrap_document(meta_xml + tree_xml, {"type": "extraction"})