"""
Agent Skills 管理服务。

提供 Claude Agent SDK 的 Skill 包管理能力：
- 上传 / 解压 zip 格式的 Skill（兼容 Claude 应用程序的官方约定）
- 维护 per-agent 注册表（启用/禁用、来源、SKILL.md frontmatter）
- 在 Agent 运行前将启用的 Skill 物化到 cwd 下的 .claude/skills/<name>/，
  使 SDK 通过 `setting_sources=["project"]` 自动加载

存储布局：
    data/agent_skills/
    └── <agent_key>/
        ├── _registry.json          # [{id, name, description, enabled, ...}, ...]
        └── store/
            └── <skill_name>/       # zip 解压结果，必须包含 SKILL.md
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────── Constants ─────────────────────────────────

# 当前支持加载 Skill 的 Agent 注册表，前端下拉据此渲染。
SUPPORTED_AGENTS: Dict[str, Dict[str, str]] = {
    "log_analysis": {
        "key": "log_analysis",
        "name": "LogAnalysisAgent",
        "framework": "Claude Agent SDK",
        "description": "基于 Claude Agent SDK 的日志根因分析智能体（Celery 任务）",
    },
}

# Skill 包硬性限制
MAX_SKILL_ZIP_BYTES = 50 * 1024 * 1024            # 单个 zip ≤ 50 MiB
MAX_SKILL_EXTRACTED_BYTES = 200 * 1024 * 1024     # 解压总量 ≤ 200 MiB
MAX_SKILL_FILE_COUNT = 1000                       # 解压条目数上限

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_REGISTRY_FILENAME = "_registry.json"
_STORE_DIRNAME = "store"


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


# ─────────────────────── Path helpers ──────────────────────────────

def _skills_root() -> Path:
    """Skills 数据根目录（由 settings.skills_data_dir 控制）。"""
    from app.config import settings
    return Path(settings.skills_data_dir)


def _agent_root(agent_key: str) -> Path:
    if agent_key not in SUPPORTED_AGENTS:
        raise UnknownAgentError(f"Unknown agent_key: {agent_key}")
    return _skills_root() / agent_key


def _store_root(agent_key: str) -> Path:
    return _agent_root(agent_key) / _STORE_DIRNAME


def _registry_path(agent_key: str) -> Path:
    return _agent_root(agent_key) / _REGISTRY_FILENAME


def _ensure_layout(agent_key: str) -> None:
    _store_root(agent_key).mkdir(parents=True, exist_ok=True)
    reg = _registry_path(agent_key)
    if not reg.exists():
        reg.write_text("[]", encoding="utf-8")


# ─────────────────────── Registry IO ───────────────────────────────

def _load_registry(agent_key: str) -> List[Dict[str, Any]]:
    _ensure_layout(agent_key)
    raw = _registry_path(agent_key).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("skills registry corrupt for agent=%s, resetting", agent_key)
        data = []
    if not isinstance(data, list):
        data = []
    return data


def _save_registry(agent_key: str, entries: List[Dict[str, Any]]) -> None:
    _ensure_layout(agent_key)
    tmp = _registry_path(agent_key).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_registry_path(agent_key))


# ─────────────────────── SKILL.md parsing ──────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill_frontmatter(skill_md_path: Path) -> Dict[str, str]:
    """解析 SKILL.md 顶部 YAML frontmatter。仅取 name/description；
    其余字段保留为字符串供未来扩展。"""
    text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillValidationError("SKILL.md 缺少 frontmatter（--- 包裹的 YAML 头）")
    block = m.group(1)
    result: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    if not result.get("name"):
        raise SkillValidationError("SKILL.md frontmatter 必须包含 name")
    if not _SKILL_NAME_RE.match(result["name"]):
        raise SkillValidationError(
            f"SKILL.md name='{result['name']}' 非法，只允许字母/数字/下划线/连字符，最长 64"
        )
    return result


# ─────────────────────── Zip 解包与校验 ────────────────────────────

def _safe_extract_zip(zip_bytes: bytes, dest: Path) -> List[Path]:
    """安全解压 zip 到 dest，返回所有写入的文件路径。

    防御：zip-slip / 条目数 / 解压总量。
    """
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
            # 跳过目录条目自身
            if info.is_dir():
                continue
            # 规范化路径并校验 zip-slip
            member = Path(info.filename)
            if member.is_absolute() or any(part == ".." for part in member.parts):
                raise SkillValidationError(f"zip 包含非法路径：{info.filename}")
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
    """寻找 SKILL.md 所在目录。

    兼容两种官方 zip 结构：
      (a) zip 顶层就是单个 skill 目录：<name>/SKILL.md
      (b) zip 顶层直接放 SKILL.md
    """
    direct = extracted_dir / "SKILL.md"
    if direct.is_file():
        return extracted_dir
    # 寻找唯一的 <something>/SKILL.md
    children = [p for p in extracted_dir.iterdir() if p.is_dir()]
    candidates = [d for d in children if (d / "SKILL.md").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SkillValidationError("zip 中未找到 SKILL.md，无法识别为 Skill 包")
    raise SkillValidationError(
        "zip 中存在多个 SKILL.md，请确保 zip 仅包含一个 Skill"
    )


# ─────────────────────── Public API ────────────────────────────────

def list_agents() -> List[Dict[str, str]]:
    """返回支持加载 Skill 的 Agent 列表（前端下拉用）。"""
    return list(SUPPORTED_AGENTS.values())


def list_skills(agent_key: str) -> List[Dict[str, Any]]:
    """列出 agent 已安装的 Skill。返回的 dict 已剔除内部路径字段。"""
    _ = _agent_root(agent_key)  # 校验 agent_key
    entries = _load_registry(agent_key)
    # 兜底：对照磁盘，过滤掉目录已丢失的条目
    store = _store_root(agent_key)
    alive: List[Dict[str, Any]] = []
    for e in entries:
        skill_dir = store / e.get("dir_name", "")
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
            alive.append(_public_entry(e))
        else:
            logger.warning("skill missing on disk, dropping: agent=%s id=%s", agent_key, e.get("id"))
    if len(alive) != len(entries):
        # 同步注册表
        _save_registry(agent_key, [_internal_entry(e) for e in alive])
    return alive


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
    """保留 dir_name 等内部字段，用于落盘。"""
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


def install_skill(
    agent_key: str,
    *,
    zip_bytes: bytes,
    source_filename: str,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """从 zip 字节流安装一个 Skill。

    - 上传体积上限：MAX_SKILL_ZIP_BYTES
    - zip 解包后必须含 SKILL.md（顶层或唯一子目录），frontmatter 必须含合法 name
    - 同名 Skill 默认拒绝，传 overwrite=True 时替换

    返回新增/更新后的 public entry。
    """
    if not zip_bytes:
        raise SkillValidationError("上传内容为空")
    if len(zip_bytes) > MAX_SKILL_ZIP_BYTES:
        raise SkillValidationError(
            f"zip 大小 {len(zip_bytes)} 字节超过上限 {MAX_SKILL_ZIP_BYTES}"
        )

    _ensure_layout(agent_key)
    store = _store_root(agent_key)

    # 解压到临时目录再原子化移动
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

        # 落盘：替换目标目录
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(skill_root), str(target_dir))

    # 计算大小
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
            "id": name,  # name 唯一约束 → 直接作为 id
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


# ─────────────────────── 物化到 Agent cwd ──────────────────────────

def materialize_enabled_skills(agent_key: str, target_dir: str | Path) -> List[str]:
    """在 target_dir 下创建 .claude/skills/<name>，指向已安装且启用的 Skill。

    优先使用 symlink；symlink 失败（不支持/权限）时降级为复制。返回已物化的 Skill 名称列表。

    SDK 配合 `setting_sources=["project"]` 时，会扫描 cwd 下的 .claude/skills/<name>/SKILL.md。
    """
    target = Path(target_dir)
    skills_dir = target / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    materialized: List[str] = []
    store = _store_root(agent_key)
    for entry in _load_registry(agent_key):
        if not entry.get("enabled", True):
            continue
        src = store / entry.get("dir_name", entry.get("name", ""))
        if not (src / "SKILL.md").is_file():
            logger.warning(
                "skill dir missing or invalid, skip: agent=%s name=%s src=%s",
                agent_key, entry.get("name"), src,
            )
            continue
        dst = skills_dir / entry["name"]
        if dst.exists() or dst.is_symlink():
            try:
                if dst.is_symlink() or dst.is_file():
                    dst.unlink()
                else:
                    shutil.rmtree(dst)
            except OSError as exc:
                logger.warning("clean dst failed: %s (%s)", dst, exc)
                continue
        try:
            os.symlink(src.resolve(), dst, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            logger.info(
                "symlink unavailable (%s), falling back to copy for skill=%s",
                exc, entry["name"],
            )
            shutil.copytree(src, dst)
        materialized.append(entry["name"])

    return materialized
