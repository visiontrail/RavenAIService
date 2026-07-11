"""
Agent & Project Skills 管理服务。

提供 Claude Agent SDK 的 Skill 包管理能力：
- 上传 / 解压 zip 格式的 Skill（兼容 Claude 应用程序的官方约定）
- 维护 per-agent 注册表（启用/禁用、来源、SKILL.md frontmatter）
- 维护 per-project 注册表（按 project_code 隔离，与 Agent Skill 并行）
- 在 Agent 运行前将启用的 Skill 物化到 cwd 下的 .claude/skills/<name>/，
  使 SDK 通过 `setting_sources=["project"]` 自动加载

Agent Skills 存储布局：
    data/agent_skills/
    └── <agent_key>/
        ├── _registry.json
        └── store/
            └── <skill_name>/
                ├── SKILL.md
                └── ...

Project Skills 存储布局：
    data/project_skills/
    └── <project_code>/
        ├── _registry.json
        └── store/
            └── <skill_name>/
                ├── SKILL.md
                └── ...
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────── Constants ─────────────────────────────────

SUPPORTED_AGENTS: Dict[str, Dict[str, str]] = {
    "log_analysis": {
        "key": "log_analysis",
        "name": "LogAnalysisAgent",
        "framework": "Claude Agent SDK",
        "description": "基于 Claude Agent SDK 的日志根因分析智能体（Celery 任务）",
    },
    "device_agent": {
        "key": "device_agent",
        "name": "DeviceAgent",
        "framework": "Claude Agent SDK",
        "description": "面向设备联动对话的 Claude Agent SDK 智能体（POST /chat 主入口）",
    },
    "project_expert": {
        "key": "project_expert",
        "name": "ProjectExpertAgent",
        "framework": "Claude Agent SDK",
        "description": "基于 Claude Agent SDK 的项目源码答疑智能体（POST /project-expert/stream）",
    },
    "general_agent": {
        "key": "general_agent",
        "name": "GeneralAgent",
        "framework": "Claude Agent SDK",
        "description": "基于轻量模型的系统使用说明与 Agent/项目路由智能体（默认对话入口）",
    },
}

MAX_SKILL_ZIP_BYTES = 50 * 1024 * 1024
MAX_SKILL_EXTRACTED_BYTES = 200 * 1024 * 1024
MAX_SKILL_FILE_COUNT = 1000

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REGISTRY_FILENAME = "_registry.json"
_STORE_DIRNAME = "store"

_IGNORED_DIR_NAMES = {"__MACOSX", ".git", ".svn", ".hg", ".idea", ".vscode"}
_IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def _is_ignored_path_parts(parts: Iterable[str]) -> bool:
    for part in parts:
        if not part:
            continue
        if part in _IGNORED_DIR_NAMES:
            return True
        if part in _IGNORED_FILE_NAMES:
            return True
        if part.startswith("._"):
            return True
    return False


# ─────────────────────── Exceptions ────────────────────────────────

class SkillError(Exception):
    """Skill 管理基础异常。"""


class UnknownAgentError(SkillError):
    pass


class SkillValidationError(SkillError):
    """zip 内容不合法（缺 SKILL.md、frontmatter 缺失、命名非法等）。"""


class SkillConflictError(SkillError):
    """同名 Skill 已存在。"""


class SkillNotFoundError(SkillError):
    pass


# ─────────────────────── Base path / registry helpers ────────────
# Parameterized by base_dir so both agent and project skill paths
# can reuse the same IO logic.

def _base_store_root(base_dir: Path) -> Path:
    return base_dir / _STORE_DIRNAME


def _base_registry_path(base_dir: Path) -> Path:
    return base_dir / _REGISTRY_FILENAME


def _base_ensure_layout(base_dir: Path) -> None:
    _base_store_root(base_dir).mkdir(parents=True, exist_ok=True)
    reg = _base_registry_path(base_dir)
    if not reg.exists():
        reg.write_text("[]", encoding="utf-8")


def _base_load_registry(base_dir: Path) -> List[Dict[str, Any]]:
    _base_ensure_layout(base_dir)
    raw = _base_registry_path(base_dir).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("skills registry corrupt for base_dir=%s, resetting", base_dir)
        data = []
    if not isinstance(data, list):
        data = []
    return data


def _base_save_registry(base_dir: Path, entries: List[Dict[str, Any]]) -> None:
    _base_ensure_layout(base_dir)
    tmp = _base_registry_path(base_dir).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_base_registry_path(base_dir))


def _base_enabled_entries(base_dir: Path) -> List[Dict[str, Any]]:
    store = _base_store_root(base_dir)
    entries: List[Dict[str, Any]] = []
    for entry in _base_load_registry(base_dir):
        if not entry.get("enabled", True):
            continue
        src = store / entry.get("dir_name", entry.get("name", ""))
        if not (src / "SKILL.md").is_file():
            logger.warning(
                "skill dir missing or invalid, skip: base_dir=%s name=%s src=%s",
                base_dir, entry.get("name"), src,
            )
            continue
        entries.append(entry)
    return entries


def _base_skill_dir_for_entry(base_dir: Path, entry: Dict[str, Any]) -> Path:
    return _base_store_root(base_dir) / entry.get("dir_name", entry.get("name", ""))


def _base_resolve_skill_dir(base_dir: Path, skill_id: str) -> Tuple[Dict[str, Any], Path]:
    registry = _base_load_registry(base_dir)
    entry = next((e for e in registry if e.get("id") == skill_id), None)
    if entry is None:
        raise SkillNotFoundError(f"Skill 不存在: {skill_id}")
    skill_dir = (_base_store_root(base_dir) / entry.get("dir_name", entry.get("name", ""))).resolve()
    if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
        raise SkillNotFoundError(f"Skill 目录已丢失: {skill_id}")
    return entry, skill_dir


# ─────────────────────── Agent path helpers ──────────────────────

def _skills_root() -> Path:
    from app.config import settings
    return Path(settings.skills_data_dir)


def _agent_root(agent_key: str) -> Path:
    if agent_key not in SUPPORTED_AGENTS:
        raise UnknownAgentError(f"Unknown agent_key: {agent_key}")
    return _skills_root() / agent_key


def _store_root(agent_key: str) -> Path:
    return _base_store_root(_agent_root(agent_key))


def _registry_path(agent_key: str) -> Path:
    return _base_registry_path(_agent_root(agent_key))


def _ensure_layout(agent_key: str) -> None:
    _base_ensure_layout(_agent_root(agent_key))


def _load_registry(agent_key: str) -> List[Dict[str, Any]]:
    return _base_load_registry(_agent_root(agent_key))


def _save_registry(agent_key: str, entries: List[Dict[str, Any]]) -> None:
    _base_save_registry(_agent_root(agent_key), entries)


def _enabled_entries(agent_key: str) -> List[Dict[str, Any]]:
    return _base_enabled_entries(_agent_root(agent_key))


def _skill_dir_for_entry(agent_key: str, entry: Dict[str, Any]) -> Path:
    return _base_skill_dir_for_entry(_agent_root(agent_key), entry)


# ─────────────────────── Project path helpers ────────────────────

def _project_skills_root() -> Path:
    from app.config import settings
    return Path(settings.project_skills_data_dir)


def _validate_project_code(project_code: str) -> str:
    if not project_code or not project_code.strip():
        raise SkillValidationError("project_code 不能为空")
    return project_code.strip().lower()


def _project_root(project_code: str) -> Path:
    code = _validate_project_code(project_code)
    return _project_skills_root() / code


def _project_store_root(project_code: str) -> Path:
    return _base_store_root(_project_root(project_code))


def _project_registry_path(project_code: str) -> Path:
    return _base_registry_path(_project_root(project_code))


# ─────────────────────── SKILL.md parsing ──────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill_frontmatter(skill_md_path: Path) -> Dict[str, str]:
    text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillValidationError("SKILL.md 缺少 frontmatter（--- 包裹的 YAML 头）")
    block = m.group(1)
    try:
        import yaml

        parsed = yaml.safe_load(block) or {}
    except Exception as exc:  # noqa: BLE001
        raise SkillValidationError(f"SKILL.md frontmatter YAML 解析失败: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SkillValidationError("SKILL.md frontmatter 必须是键值对象")

    result: Dict[str, str] = {}
    for key, value in parsed.items():
        if not key:
            continue
        if value is None:
            result[str(key).strip()] = ""
        elif isinstance(value, str):
            result[str(key).strip()] = value.strip()
        else:
            result[str(key).strip()] = str(value).strip()
    if not result.get("name"):
        raise SkillValidationError("SKILL.md frontmatter 必须包含 name")
    if not _SKILL_NAME_RE.match(result["name"]):
        raise SkillValidationError(
            f"SKILL.md name='{result['name']}' 非法，只允许字母/数字/下划线/连字符，最长 64"
        )
    return result


# ─────────────────────── Zip 解包与校验 ────────────────────────────

def _safe_extract_zip(zip_bytes: bytes, dest: Path) -> List[Path]:
    written: List[Path] = []
    extracted = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        infos = zf.infolist()
        if len(infos) > MAX_SKILL_FILE_COUNT:
            raise SkillValidationError(
                f"zip 内条目数 {len(infos)} 超过上限 {MAX_SKILL_FILE_COUNT}"
            )
        dest_resolved = dest.resolve()
        for info in infos:
            if info.is_dir():
                continue
            member = Path(info.filename)
            if member.is_absolute() or any(part == ".." for part in member.parts):
                raise SkillValidationError(f"zip 包含非法路径：{info.filename}")
            if _is_ignored_path_parts(member.parts):
                continue
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest_resolved) + os.sep) and target != dest_resolved:
                raise SkillValidationError(f"zip 越权写入：{info.filename}")
            extracted += info.file_size
            if extracted > MAX_SKILL_EXTRACTED_BYTES:
                raise SkillValidationError(
                    f"解压总量 {extracted} 超过上限 {MAX_SKILL_EXTRACTED_BYTES}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            written.append(target)
    return written


def _find_skill_root(extracted_dir: Path) -> Path:
    direct = extracted_dir / "SKILL.md"
    if direct.is_file():
        return extracted_dir
    children = [p for p in extracted_dir.iterdir() if p.is_dir()]
    candidates = [d for d in children if (d / "SKILL.md").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SkillValidationError("zip 中未找到 SKILL.md，无法识别为 Skill 包")
    raise SkillValidationError(
        "zip 中存在多个 SKILL.md，请确保 zip 仅包含一个 Skill"
    )


# ─────────────────────── Shared entry helpers ─────────────────────

def _public_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "description": entry.get("description", ""),
        "enabled": bool(entry.get("enabled", True)),
        "source_filename": entry.get("source_filename", ""),
        "size_bytes": int(entry.get("size_bytes", 0) or 0),
        "installed_at": entry.get("installed_at"),
        "updated_at": entry.get("updated_at"),
    }


def _internal_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "description": entry.get("description", ""),
        "enabled": bool(entry.get("enabled", True)),
        "source_filename": entry.get("source_filename", ""),
        "size_bytes": int(entry.get("size_bytes", 0) or 0),
        "installed_at": entry.get("installed_at"),
        "updated_at": entry.get("updated_at"),
        "dir_name": entry.get("dir_name") or entry["name"],
    }


# ─────────────────────── Agent Public API ─────────────────────────

def list_agents() -> List[Dict[str, str]]:
    return list(SUPPORTED_AGENTS.values())


def list_skills(agent_key: str) -> List[Dict[str, Any]]:
    _ = _agent_root(agent_key)
    entries = _load_registry(agent_key)
    store = _store_root(agent_key)
    alive: List[Dict[str, Any]] = []
    for e in entries:
        skill_dir = store / e.get("dir_name", "")
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            alive.append(_public_entry(e))
        else:
            logger.warning("skill missing on disk, dropping: agent=%s id=%s", agent_key, e.get("id"))
    if len(alive) != len(entries):
        _save_registry(agent_key, [_internal_entry(e) for e in alive])
    return alive


def install_skill(
    agent_key: str,
    *,
    zip_bytes: bytes,
    source_filename: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    if not zip_bytes:
        raise SkillValidationError("上传内容为空")
    if len(zip_bytes) > MAX_SKILL_ZIP_BYTES:
        raise SkillValidationError(
            f"zip 大小 {len(zip_bytes)} 字节超过上限 {MAX_SKILL_ZIP_BYTES}"
        )

    _ensure_layout(agent_key)
    store = _store_root(agent_key)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="skill_", dir=str(store)) as tmpdir:
        tmp_path = Path(tmpdir)
        _safe_extract_zip(zip_bytes, tmp_path)
        skill_root = _find_skill_root(tmp_path)
        fm = _parse_skill_frontmatter(skill_root / "SKILL.md")
        name = fm["name"]
        description = fm.get("description", "")

        target_dir = store / name
        registry = _load_registry(agent_key)
        existing = next((e for e in registry if e.get("name") == name), None)
        if existing and not overwrite:
            raise SkillConflictError(f"已存在同名 Skill: {name}")

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(skill_root), str(target_dir))

    size_bytes = sum(
        f.stat().st_size for f in target_dir.rglob("*") if f.is_file()
    )
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        existing.update(
            {
                "description": description,
                "source_filename": source_filename,
                "size_bytes": size_bytes,
                "updated_at": now,
                "dir_name": name,
            }
        )
        new_entry = existing
    else:
        new_entry = {
            "id": name,
            "name": name,
            "description": description,
            "enabled": True,
            "source_filename": source_filename,
            "size_bytes": size_bytes,
            "installed_at": now,
            "updated_at": now,
            "dir_name": name,
        }
        registry.append(new_entry)

    _save_registry(agent_key, [_internal_entry(e) for e in registry])
    logger.info(
        "skill installed: agent=%s name=%s size=%d overwrite=%s",
        agent_key, name, size_bytes, bool(existing),
    )
    return _public_entry(new_entry)


def delete_skill(agent_key: str, skill_id: str) -> None:
    registry = _load_registry(agent_key)
    idx = next((i for i, e in enumerate(registry) if e.get("id") == skill_id), -1)
    if idx < 0:
        raise SkillNotFoundError(f"Skill 不存在: {skill_id}")
    entry = registry.pop(idx)
    target = _store_root(agent_key) / entry.get("dir_name", entry.get("name", ""))
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    _save_registry(agent_key, [_internal_entry(e) for e in registry])
    logger.info("skill deleted: agent=%s id=%s", agent_key, skill_id)


def set_skill_enabled(agent_key: str, skill_id: str, enabled: bool) -> Dict[str, Any]:
    registry = _load_registry(agent_key)
    entry = next((e for e in registry if e.get("id") == skill_id), None)
    if entry is None:
        raise SkillNotFoundError(f"Skill 不存在: {skill_id}")
    entry["enabled"] = bool(enabled)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_registry(agent_key, [_internal_entry(e) for e in registry])
    return _public_entry(entry)


# ─────────────────────── Agent file browsing ──────────────────────

MAX_PREVIEW_FILE_BYTES = 1 * 1024 * 1024
MAX_TREE_ENTRIES = 2000

_TEXT_LIKE_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".htm", ".css",
    ".scss", ".sass", ".less", ".sh", ".bash", ".zsh", ".fish", ".rb",
    ".go", ".rs", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp",
    ".hpp", ".cs", ".swift", ".php", ".sql", ".xml", ".csv", ".tsv",
    ".env", ".gitignore", ".dockerignore", ".log", ".lua", ".r",
    ".proto", ".graphql", ".gql",
}


def _safe_join(base: Path, rel_path: str) -> Path:
    if not rel_path or rel_path in (".", "./"):
        return base
    candidate = (base / rel_path).resolve()
    base_resolved = base.resolve()
    if candidate != base_resolved and not str(candidate).startswith(str(base_resolved) + os.sep):
        raise SkillValidationError(f"非法路径: {rel_path}")
    return candidate


def _build_file_tree(skill_dir: Path, entry_name: str) -> Dict[str, Any]:
    count = 0

    def build(node_dir: Path) -> Dict[str, Any]:
        nonlocal count
        children: List[Dict[str, Any]] = []
        items = sorted(
            (p for p in node_dir.iterdir() if not _is_ignored_path_parts([p.name])),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        for child in items:
            count += 1
            if count > MAX_TREE_ENTRIES:
                raise SkillValidationError(
                    f"Skill 文件数超过预览上限 {MAX_TREE_ENTRIES}"
                )
            rel = child.relative_to(skill_dir).as_posix()
            if child.is_dir():
                children.append(
                    {
                        "name": child.name,
                        "path": rel,
                        "type": "dir",
                        "children": build(child)["children"],
                    }
                )
            else:
                children.append(
                    {
                        "name": child.name,
                        "path": rel,
                        "type": "file",
                        "size": child.stat().st_size,
                    }
                )
        return {
            "name": node_dir.name if node_dir != skill_dir else entry_name,
            "path": "",
            "type": "dir",
            "children": children,
        }

    return build(skill_dir)


def _read_file_content(skill_dir: Path, rel_path: str) -> Dict[str, Any]:
    if not rel_path:
        raise SkillValidationError("path 不能为空")
    target = _safe_join(skill_dir, rel_path)
    if not target.is_file():
        raise SkillNotFoundError(f"文件不存在: {rel_path}")

    size = target.stat().st_size
    suffix = target.suffix.lower()
    is_textlike = suffix in _TEXT_LIKE_SUFFIXES or target.name.lower() in {"skill.md", "readme", "license"}

    if not is_textlike:
        with open(target, "rb") as fh:
            sniff = fh.read(4096)
        is_textlike = b"\x00" not in sniff

    if not is_textlike:
        return {
            "path": rel_path,
            "size": size,
            "encoding": "binary",
            "truncated": False,
        }

    truncated = size > MAX_PREVIEW_FILE_BYTES
    read_size = MAX_PREVIEW_FILE_BYTES if truncated else size
    with open(target, "rb") as fh:
        raw = fh.read(read_size)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")

    return {
        "path": rel_path,
        "size": size,
        "encoding": "utf-8",
        "content": text,
        "truncated": truncated,
    }


def list_skill_files(agent_key: str, skill_id: str) -> Dict[str, Any]:
    _ = _agent_root(agent_key)
    entry, skill_dir = _base_resolve_skill_dir(_agent_root(agent_key), skill_id)
    tree = _build_file_tree(skill_dir, entry["name"])
    return {"name": entry["name"], "tree": tree}


def read_skill_file(agent_key: str, skill_id: str, rel_path: str) -> Dict[str, Any]:
    _ = _agent_root(agent_key)
    _, skill_dir = _base_resolve_skill_dir(_agent_root(agent_key), skill_id)
    return _read_file_content(skill_dir, rel_path)


# ─────────────────────── Project Skill Public API ─────────────────

def list_project_skills(project_code: str) -> List[Dict[str, Any]]:
    base_dir = _project_root(project_code)
    entries = _base_load_registry(base_dir)
    store = _base_store_root(base_dir)
    alive: List[Dict[str, Any]] = []
    for e in entries:
        skill_dir = store / e.get("dir_name", "")
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            alive.append(_public_entry(e))
        else:
            logger.warning("project skill missing on disk, dropping: project=%s id=%s", project_code, e.get("id"))
    if len(alive) != len(entries):
        _base_save_registry(base_dir, [_internal_entry(e) for e in alive])
    return alive


def install_project_skill(
    project_code: str,
    *,
    zip_bytes: bytes,
    source_filename: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    if not zip_bytes:
        raise SkillValidationError("上传内容为空")
    if len(zip_bytes) > MAX_SKILL_ZIP_BYTES:
        raise SkillValidationError(
            f"zip 大小 {len(zip_bytes)} 字节超过上限 {MAX_SKILL_ZIP_BYTES}"
        )

    base_dir = _project_root(project_code)
    _base_ensure_layout(base_dir)
    store = _base_store_root(base_dir)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="skill_", dir=str(store)) as tmpdir:
        tmp_path = Path(tmpdir)
        _safe_extract_zip(zip_bytes, tmp_path)
        skill_root = _find_skill_root(tmp_path)
        fm = _parse_skill_frontmatter(skill_root / "SKILL.md")
        name = fm["name"]
        description = fm.get("description", "")

        target_dir = store / name
        registry = _base_load_registry(base_dir)
        existing = next((e for e in registry if e.get("name") == name), None)
        if existing and not overwrite:
            raise SkillConflictError(f"已存在同名 Skill: {name}")

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(skill_root), str(target_dir))

    size_bytes = sum(
        f.stat().st_size for f in target_dir.rglob("*") if f.is_file()
    )
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        existing.update(
            {
                "description": description,
                "source_filename": source_filename,
                "size_bytes": size_bytes,
                "updated_at": now,
                "dir_name": name,
            }
        )
        new_entry = existing
    else:
        new_entry = {
            "id": name,
            "name": name,
            "description": description,
            "enabled": True,
            "source_filename": source_filename,
            "size_bytes": size_bytes,
            "installed_at": now,
            "updated_at": now,
            "dir_name": name,
        }
        registry.append(new_entry)

    _base_save_registry(base_dir, [_internal_entry(e) for e in registry])
    logger.info(
        "project skill installed: project=%s name=%s size=%d overwrite=%s",
        project_code, name, size_bytes, bool(existing),
    )
    return _public_entry(new_entry)


def set_project_skill_enabled(project_code: str, skill_id: str, enabled: bool) -> Dict[str, Any]:
    base_dir = _project_root(project_code)
    registry = _base_load_registry(base_dir)
    entry = next((e for e in registry if e.get("id") == skill_id), None)
    if entry is None:
        raise SkillNotFoundError(f"Skill 不存在: {skill_id}")
    entry["enabled"] = bool(enabled)
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    _base_save_registry(base_dir, [_internal_entry(e) for e in registry])
    return _public_entry(entry)


def delete_project_skill(project_code: str, skill_id: str) -> None:
    base_dir = _project_root(project_code)
    registry = _base_load_registry(base_dir)
    idx = next((i for i, e in enumerate(registry) if e.get("id") == skill_id), -1)
    if idx < 0:
        raise SkillNotFoundError(f"Skill 不存在: {skill_id}")
    entry = registry.pop(idx)
    target = _base_store_root(base_dir) / entry.get("dir_name", entry.get("name", ""))
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    _base_save_registry(base_dir, [_internal_entry(e) for e in registry])
    logger.info("project skill deleted: project=%s id=%s", project_code, skill_id)


def list_project_skill_files(project_code: str, skill_id: str) -> Dict[str, Any]:
    base_dir = _project_root(project_code)
    entry, skill_dir = _base_resolve_skill_dir(base_dir, skill_id)
    tree = _build_file_tree(skill_dir, entry["name"])
    return {"name": entry["name"], "tree": tree}


def read_project_skill_file(project_code: str, skill_id: str, rel_path: str) -> Dict[str, Any]:
    base_dir = _project_root(project_code)
    _, skill_dir = _base_resolve_skill_dir(base_dir, skill_id)
    return _read_file_content(skill_dir, rel_path)


# ─────────────────────── Project enabled entries ─────────────────

def _project_enabled_entries(project_code: str) -> List[Dict[str, Any]]:
    return _base_enabled_entries(_project_root(project_code))


# ─────────────────────── Overviews & Materialization ──────────────

def enabled_skill_overviews(
    agent_key: str,
    *,
    project_code: Optional[str] = None,
    names: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    """Return name/description pairs for the combined enabled skill pool.

    Mirrors the materialization order (agent skills first, project skills
    override on name conflict) so agents can advertise exactly what was
    materialized. ``names`` optionally restricts the result to a subset.
    """
    wanted = {str(n) for n in names} if names is not None else None
    order: List[str] = []
    merged: Dict[str, str] = {}

    def _add(entry: Dict[str, Any]) -> None:
        name = str(entry["name"])
        if wanted is not None and name not in wanted:
            return
        if name not in merged:
            order.append(name)
        merged[name] = str(entry.get("description") or "")

    for entry in _enabled_entries(agent_key):
        _add(entry)
    if project_code:
        for entry in _project_enabled_entries(project_code):
            _add(entry)
    return [{"name": name, "description": merged[name]} for name in order]


def materialize_enabled_skills(
    agent_key: str,
    target_dir: str | Path,
    *,
    skill_names: Optional[Iterable[str]] = None,
    project_code: Optional[str] = None,
) -> List[str]:
    target = Path(target_dir)
    skills_dir = target / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    selected_names = set(skill_names) if skill_names is not None else None

    materialized: List[str] = []

    def _link_skill(name: str, src: Path) -> None:
        dst = skills_dir / name
        if dst.exists() or dst.is_symlink():
            try:
                if dst.is_symlink() or dst.is_file():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)
            except OSError as exc:
                logger.warning("clean dst failed: %s (%s)", dst, exc)
                return
        try:
            os.symlink(src.resolve(), dst, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            logger.info(
                "symlink unavailable (%s), falling back to copy for skill=%s",
                exc, name,
            )
            shutil.copytree(src, dst)
        if name not in materialized:
            materialized.append(name)

    # Agent skills first
    for entry in _enabled_entries(agent_key):
        name = entry["name"]
        if selected_names is not None and name not in selected_names:
            continue
        _link_skill(name, _skill_dir_for_entry(agent_key, entry))

    # Project skills second — overwrite on name conflict
    if project_code:
        for entry in _project_enabled_entries(project_code):
            name = entry["name"]
            if selected_names is not None and name not in selected_names:
                continue
            _link_skill(name, _base_skill_dir_for_entry(_project_root(project_code), entry))

    return materialized
