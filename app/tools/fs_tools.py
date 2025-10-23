"""
Filesystem helper tools for safe operations on large log files.
"""
import os
import glob
import hashlib
from typing import Dict, List, Optional

from app.config import settings
from app.agents.xml_utils import wrap_excerpt, wrap_metadata


def _is_in_allowed_root(path: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(settings.agent_root_dir)
        return os.path.commonpath([abs_path, abs_root]) == abs_root
    except Exception:
        return False


def safe_listdir(root: Optional[str] = None, include_glob: Optional[str] = None, max_depth: int = 2) -> List[Dict[str, str]]:
    base = os.path.abspath(root or settings.agent_root_dir)
    if os.path.commonpath([base, os.path.abspath(settings.agent_root_dir)]) != os.path.abspath(settings.agent_root_dir):
        raise PermissionError("Root outside allowed directory")
    results: List[Dict[str, str]] = []
    for d, _, files in os.walk(base):
        depth = d[len(base):].count(os.sep)
        if depth > max_depth:
            continue
        for f in files:
            path = os.path.join(d, f)
            if include_glob and not glob.fnmatch.fnmatch(path, include_glob):
                continue
            try:
                st = os.stat(path)
                results.append({
                    "path": path,
                    "size": str(st.st_size),
                    "modified": str(int(st.st_mtime)),
                })
            except Exception:
                continue
    return results


def _read_lines(file_path: str, n_lines: int, from_tail: bool = False, max_bytes: Optional[int] = None) -> str:
    if not _is_in_allowed_root(file_path):
        raise PermissionError("Path outside allowed root: %s" % file_path)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)

    limit = max_bytes or settings.agent_max_snippet_bytes

    if not from_tail:
        out_lines: List[str] = []
        total_bytes = 0
        with open(file_path, "r", errors="ignore") as f:
            for _ in range(n_lines):
                line = f.readline()
                if not line:
                    break
                out_lines.append(line)
                total_bytes += len(line.encode("utf-8", errors="ignore"))
                if total_bytes >= limit:
                    break
        return "".join(out_lines)
    else:
        # Simple tail: read last bytes then split lines
        with open(file_path, "rb") as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                read_size = min(limit, size)
                f.seek(-read_size, os.SEEK_END)
                buf = f.read(read_size)
            except Exception:
                f.seek(0)
                buf = f.read(limit)
        text = buf.decode("utf-8", errors="ignore")
        lines = text.splitlines()
        tail_lines = lines[-n_lines:]
        return "\n".join(tail_lines)


def read_head_xml(path: str, n_lines: int = 100, max_bytes: Optional[int] = None) -> str:
    snippet = _read_lines(path, n_lines=n_lines, from_tail=False, max_bytes=max_bytes)
    return wrap_excerpt(path, 1, n_lines, snippet, match="<head>")


def read_tail_xml(path: str, n_lines: int = 100, max_bytes: Optional[int] = None) -> str:
    snippet = _read_lines(path, n_lines=n_lines, from_tail=True, max_bytes=max_bytes)
    # We don't know exact line numbers; mark tail region
    return wrap_excerpt(path, -n_lines, -1, snippet, match="<tail>")


def read_chunk_xml(path: str, offset: int, length: int) -> str:
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        f.seek(offset)
        buf = f.read(min(length, settings.agent_max_snippet_bytes))
    text = buf.decode("utf-8", errors="ignore")
    return wrap_excerpt(path, offset, offset + len(buf), text, match="<chunk>")


def stat_xml(path: str) -> str:
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    st = os.stat(path)
    meta = {
        "path": path,
        "size": st.st_size,
        "modified": int(st.st_mtime),
    }
    return wrap_metadata(meta)


def sha256_xml(path: str) -> str:
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return wrap_metadata({"path": path, "sha256": h.hexdigest()})