"""
Metadata extraction tool for large log packages (tar.gz / zip).
Reads archive headers without full decompression and emits structured XML.
"""
import os
import io
import json
import tarfile
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.agents.xml_utils import wrap_file_list, wrap_metadata


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
    # Fallback using signature checks
    try:
        if tarfile.is_tarfile(path):
            return "tar"
        if zipfile.is_zipfile(path):
            return "zip"
    except Exception:
        pass
    return None


def _list_tar_members(path: str) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    with tarfile.open(path, "r:*") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            files.append({
                "path": m.name,
                "size": m.size,
                "modified": datetime.utcfromtimestamp(m.mtime).isoformat() + "Z"
            })
    return files


def _list_zip_members(path: str) -> List[Dict[str, str]]:
    files: List[Dict[str, str]] = []
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Zip doesn't store UTC explicitly
            dt = datetime(*info.date_time).isoformat() + "Z"
            files.append({
                "path": info.filename,
                "size": info.file_size,
                "modified": dt
            })
    return files


def _extract_metadata_json(path: str) -> Optional[Dict[str, Any]]:
    """Try to locate and parse metadata.json inside the archive without full extraction."""
    # Try ZIP first
    try:
        if path.endswith(".zip") or zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                meta_name = next((n for n in zf.namelist() if n.endswith("metadata.json") and not n.endswith("/")), None)
                if meta_name:
                    with zf.open(meta_name) as f:
                        content = f.read().decode("utf-8", errors="ignore")
                        return json.loads(content)
    except Exception:
        pass
    # Fallback to tar family
    try:
        with tarfile.open(path, mode="r:*") as tf:
            member = next((m for m in tf.getmembers() if m.isfile() and m.name.endswith("metadata.json")), None)
            if member is not None:
                extracted = tf.extractfile(member)
                if extracted is not None:
                    content = extracted.read().decode("utf-8", errors="ignore")
                    return json.loads(content)
    except Exception:
        pass
    return None


def _derive_package_metadata(files: List[Dict[str, str]], source: str) -> Dict[str, str]:
    total_size = sum(int(f.get("size", 0)) for f in files)
    types = set()
    for f in files:
        name = f.get("path", "").lower()
        if name.endswith((".log", ".txt")):
            types.add("text")
        elif name.endswith((".json")):
            types.add("json")
        elif name.endswith((".pcap", ".pcapng")):
            types.add("pcap")
        elif name.endswith((".csv")):
            types.add("csv")
    modified_list = [f.get("modified") for f in files if f.get("modified")]
    first_modified = min(modified_list) if modified_list else None
    last_modified = max(modified_list) if modified_list else None
    return {
        "source": source,
        "file_count": str(len(files)),
        "total_size": str(total_size),
        "content_types": ",".join(sorted(types)) if types else "unknown",
        "first_modified": first_modified or "",
        "last_modified": last_modified or "",
    }


def get_log_package_metadata(path: str) -> Dict[str, str]:
    """Return metadata dict for a log package.
    Only reads archive headers and extracts metadata.json when present.
    Safe-root enforced.
    """
    if not settings.agent_enabled:
        raise RuntimeError("Agent disabled by configuration")
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    a_type = _guess_archive_type(path)
    if a_type is None:
        raise ValueError("Unsupported archive format")

    file_list: List[Dict[str, str]]
    if a_type == "tar":
        file_list = _list_tar_members(path)
    else:
        file_list = _list_zip_members(path)

    meta = _derive_package_metadata(file_list, source=os.path.basename(path))

    # Enrich with fields from metadata.json if present
    metadata_json = _extract_metadata_json(path)
    if metadata_json:
        try:
            issue_info = metadata_json.get("issue_info", {}) if isinstance(metadata_json, dict) else {}
            issue_desc = issue_info.get("issue_description")
            environment_info = issue_info.get("environment_info")
            service_name = issue_info.get("service_name")
            version_info = metadata_json.get("version_info")

            if issue_desc:
                meta["issue_description"] = str(issue_desc)
            if environment_info:
                meta["environment"] = str(environment_info)
            if service_name:
                meta["service_name"] = str(service_name)
            if version_info is not None:
                meta["version_info"] = json.dumps(version_info, ensure_ascii=False) if isinstance(version_info, (dict, list)) else str(version_info)

            meta["has_metadata_json"] = "true"
        except Exception:
            meta["has_metadata_json"] = "false"
    else:
        meta["has_metadata_json"] = "false"

    return meta


def get_log_package_metadata_xml(path: str) -> str:
    """Return XML with both metadata and file list."""
    if not settings.agent_enabled:
        raise RuntimeError("Agent disabled by configuration")
    if not _is_in_allowed_root(path):
        raise PermissionError("Path outside allowed root: %s" % path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    a_type = _guess_archive_type(path)
    if a_type is None:
        raise ValueError("Unsupported archive format")

    if a_type == "tar":
        file_list = _list_tar_members(path)
    else:
        file_list = _list_zip_members(path)

    meta = _derive_package_metadata(file_list, source=os.path.basename(path))

    # Enrich with fields from metadata.json if present
    metadata_json = _extract_metadata_json(path)
    if metadata_json:
        try:
            issue_info = metadata_json.get("issue_info", {}) if isinstance(metadata_json, dict) else {}
            issue_desc = issue_info.get("issue_description")
            environment_info = issue_info.get("environment_info")
            service_name = issue_info.get("service_name")
            version_info = metadata_json.get("version_info")

            if issue_desc:
                meta["issue_description"] = str(issue_desc)
            if environment_info:
                meta["environment"] = str(environment_info)
            if service_name:
                meta["service_name"] = str(service_name)
            if version_info is not None:
                meta["version_info"] = json.dumps(version_info, ensure_ascii=False) if isinstance(version_info, (dict, list)) else str(version_info)

            meta["has_metadata_json"] = "true"
        except Exception:
            meta["has_metadata_json"] = "false"
    else:
        meta["has_metadata_json"] = "false"

    file_xml = wrap_file_list(file_list, source=meta.get("source"))
    meta_xml = wrap_metadata(meta)
    # Wrap both for easier ingestion
    return f"<log_package_info>{meta_xml}{file_xml}</log_package_info>"