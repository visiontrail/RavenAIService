"""Raven rebuild package management service.

The legacy Node package service stored package metadata in a JSON array and
package files on disk. This service keeps that storage contract so existing
volumes can be reused by the unified FastAPI backend.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable, Optional

from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.utils.storage_utils import get_free_bytes

logger = logging.getLogger(__name__)


PACKAGE_TYPES = {
    "LINGXI_10": "lingxi-10",
    "LINGXI_07A": "lingxi-07a",
    "KA_TX": "ka-tx",
    "KA_RX": "ka-rx",
    "CONFIG": "config",
    "LINGXI_06TRD": "lingxi-06-thrid",
}


def _abs_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(settings.base_dir) / path


def _json_or_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_list(value: Any) -> list[Any]:
    parsed = _json_or_value(value)
    if parsed is None or parsed == "":
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, tuple):
        return list(parsed)
    if isinstance(parsed, str):
        return [item.strip() for item in parsed.split(",") if item.strip()]
    return [parsed]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RavenPackageService:
    def __init__(self) -> None:
        self.data_dir = _abs_path(settings.raven_data_dir)
        self.uploads_dir = _abs_path(settings.upload_dir)
        self.metadata_file = _abs_path(settings.raven_metadata_file)
        self.vector_store_path = _abs_path(settings.raven_vector_store_path)
        self.vector_meta_file = Path(f"{self.vector_store_path}.meta.json")
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

    def load_packages(self) -> list[dict[str, Any]]:
        if not self.metadata_file.exists():
            return []
        try:
            data = json.loads(self.metadata_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取 Raven 包元数据失败: %s", exc)
            return []
        return data if isinstance(data, list) else []

    def save_packages(self, packages: list[dict[str, Any]]) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_file.write_text(
            json.dumps(packages, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def package_file(self, package: dict[str, Any]) -> Path:
        path = Path(str(package.get("path") or ""))
        return path if path.is_absolute() else self.uploads_dir / path

    def get_all_packages(self, prune_missing: bool = True) -> list[dict[str, Any]]:
        packages = self.load_packages()
        if not prune_missing:
            return packages

        existing: list[dict[str, Any]] = []
        removed = 0
        for package in packages:
            if self.package_file(package).exists():
                existing.append(package)
            else:
                removed += 1

        if removed:
            self.save_packages(existing)
            logger.info("Raven 包元数据清理完成，移除不存在文件记录 %s 条", removed)
        return existing

    def get_package(self, package_id: str) -> Optional[dict[str, Any]]:
        return next((pkg for pkg in self.get_all_packages() if pkg.get("id") == package_id), None)

    def add_or_update_package(self, package: dict[str, Any]) -> dict[str, Any]:
        packages = self.load_packages()
        target_path = str(package.get("path") or "")
        updated = False

        for index, existing in enumerate(packages):
            if existing.get("path") == target_path:
                package["id"] = existing.get("id") or package.get("id")
                packages[index] = {**existing, **package}
                updated = True
                break

        if not updated:
            packages.append(package)

        self.save_packages(packages)
        return package

    def delete_package(self, package_id: str) -> bool:
        packages = self.load_packages()
        target = next((pkg for pkg in packages if pkg.get("id") == package_id), None)
        if not target:
            return False

        file_path = self.package_file(target)
        if file_path.exists():
            file_path.unlink()
        self.save_packages([pkg for pkg in packages if pkg.get("id") != package_id])
        return True

    async def store_upload(self, file: UploadFile) -> tuple[Path, int, str]:
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件缺少文件名")

        lower_name = file.filename.lower()
        if not (lower_name.endswith(".tgz") or lower_name.endswith(".tar.gz")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .tgz and .tar.gz files are allowed")

        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        dest = self._unique_upload_path(file.filename)
        sha256_hash = hashlib.sha256()
        total = 0
        limit = settings.upload_max_size_mb * 1024 * 1024

        try:
            with dest.open("wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"文件过大，超过 {settings.upload_max_size_mb}MB 限制",
                        )
                    free_bytes = get_free_bytes(self.uploads_dir)
                    if free_bytes - settings.disk_reserve_bytes < len(chunk):
                        raise HTTPException(status_code=507, detail="磁盘空间不足，无法完成上传")
                    out.write(chunk)
                    sha256_hash.update(chunk)
        except Exception:
            if dest.exists():
                dest.unlink()
            raise
        finally:
            await file.close()

        return dest, total, sha256_hash.hexdigest()

    def build_package_info(
        self,
        file_path: Path,
        size: int,
        sha256: str,
        metadata_fields: Optional[dict[str, Any]] = None,
        package_info: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        metadata_fields = metadata_fields or {}
        base = package_info.copy() if package_info else self.extract_package_metadata(file_path, size, sha256)

        if package_info:
            base["path"] = str(file_path)
            base["size"] = size
            base.setdefault("id", str(uuid.uuid4()))
            base.setdefault("name", file_path.name)
            base.setdefault("createdAt", _now_iso())
            base.setdefault("version", self.parse_version(file_path.name) or "0.0.0")
            base.setdefault("packageType", self.determine_package_type(file_path.name))
            base.setdefault("metadata", {})

        metadata = dict(base.get("metadata") or {})
        if "description" in metadata_fields:
            metadata["description"] = metadata_fields.get("description") or ""
        if "isPatch" in metadata_fields:
            metadata["isPatch"] = _as_bool(metadata_fields.get("isPatch"))
        if "tags" in metadata_fields:
            metadata["tags"] = [str(item) for item in _as_list(metadata_fields.get("tags"))]
        if "components" in metadata_fields:
            metadata["components"] = self.normalize_components(_as_list(metadata_fields.get("components")), base.get("version"))
        metadata["sha256"] = sha256
        metadata.setdefault("customFields", {})

        if metadata_fields.get("version"):
            base["version"] = str(metadata_fields["version"])
        if metadata_fields.get("packageType"):
            base["packageType"] = str(metadata_fields["packageType"])

        base["metadata"] = metadata
        return base

    def extract_package_metadata(self, file_path: Path, size: Optional[int] = None, sha256: Optional[str] = None) -> dict[str, Any]:
        stat = file_path.stat()
        version = self.parse_version(file_path.name) or "0.0.0"
        return {
            "id": str(uuid.uuid4()),
            "name": file_path.name,
            "path": str(file_path),
            "size": size if size is not None else stat.st_size,
            "createdAt": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(),
            "packageType": self.determine_package_type(file_path.name),
            "version": version,
            "metadata": {
                "isPatch": "patch" in file_path.name.lower(),
                "components": self.normalize_components(self.extract_components(file_path.name), version),
                "description": "",
                "tags": [],
                "sha256": sha256 or self.calculate_hash(file_path),
                "customFields": {},
            },
        }

    def scan_uploads_directory(self) -> int:
        packages = self.load_packages()
        known_paths = {str(pkg.get("path")) for pkg in packages}
        added = 0
        for file_path in self.uploads_dir.iterdir():
            if not file_path.is_file():
                continue
            lower = file_path.name.lower()
            if not (lower.endswith(".tgz") or lower.endswith(".tar.gz")):
                continue
            if str(file_path) in known_paths:
                continue
            packages.append(self.extract_package_metadata(file_path))
            added += 1
        if added:
            self.save_packages(packages)
        return added

    def filter_packages(self, params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        packages = self.get_all_packages()
        search = str(params.get("search") or "").lower()
        package_type = str(params.get("type") or "")
        version = str(params.get("version") or "")
        tags = str(params.get("tags") or "").lower()
        is_patch = params.get("isPatch")

        if search:
            packages = [
                pkg for pkg in packages
                if search in str(pkg.get("name", "")).lower()
                or search in str(pkg.get("version", "")).lower()
                or search in str(pkg.get("metadata", {}).get("description", "")).lower()
            ]
        if package_type:
            packages = [pkg for pkg in packages if pkg.get("packageType") == package_type]
        if version:
            packages = [pkg for pkg in packages if str(pkg.get("version", "")) == version]
        if tags:
            packages = [
                pkg for pkg in packages
                if any(tags in str(tag).lower() for tag in pkg.get("metadata", {}).get("tags", []))
            ]
        if is_patch not in (None, ""):
            expected = _as_bool(is_patch)
            packages = [pkg for pkg in packages if _as_bool(pkg.get("metadata", {}).get("isPatch")) == expected]

        sort_by = str(params.get("sortBy") or "createdAt")
        reverse = str(params.get("sortOrder") or "desc").lower() == "desc"
        packages.sort(key=lambda pkg: self._sort_value(pkg, sort_by), reverse=reverse)

        page = max(int(params.get("page") or 1), 1)
        limit = max(int(params.get("limit") or 10), 1)
        total = len(packages)
        start = (page - 1) * limit
        end = start + limit
        return packages[start:end], {
            "currentPage": page,
            "totalPages": (total + limit - 1) // limit,
            "totalItems": total,
            "itemsPerPage": limit,
        }

    def build_zip(self, packages: Iterable[dict[str, Any]], prefix: str = "packages") -> Path:
        temp = NamedTemporaryFile(prefix=f"{prefix}-", suffix=".zip", delete=False)
        temp_path = Path(temp.name)
        temp.close()
        with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for package in packages:
                file_path = self.package_file(package)
                if file_path.exists():
                    archive.write(file_path, arcname=str(package.get("name") or file_path.name))
        return temp_path

    def rebuild_search_index(self) -> dict[str, Any]:
        packages = self.get_all_packages()
        self.vector_store_path.mkdir(parents=True, exist_ok=True)
        docs = [{"id": pkg.get("id"), "text": self.package_to_text(pkg)} for pkg in packages]
        (self.vector_store_path / "documents.json").write_text(
            json.dumps(docs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        meta = {
            "provider": settings.rag_embedding_provider,
            "modelName": settings.rag_embedding_model,
            "createdAt": _now_iso(),
            "totalPackages": len(packages),
        }
        self.vector_meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def search_status(self) -> dict[str, Any]:
        packages = self.get_all_packages()
        meta = {}
        if self.vector_meta_file.exists():
            try:
                meta = json.loads(self.vector_meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        return {
            "initialized": self.vector_meta_file.exists() or len(packages) == 0,
            "vectorStoreExists": self.vector_store_path.exists(),
            "rebuilding": False,
            "embeddingProvider": settings.rag_embedding_provider,
            "embeddingModel": settings.rag_embedding_model,
            "totalPackages": len(packages),
            "config": {
                "baseURL": settings.openai_base_url or settings.deepseek_base_url,
                "modelName": settings.llm_model_name,
            },
            **({"meta": meta} if meta else {}),
        }

    def similarity_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        packages = self.get_all_packages()
        scored = []
        for package in packages:
            score = self.score_package(query, package)
            if score > 0:
                scored.append(({**package, "relevanceScore": round(score, 4)}, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [item[0] for item in scored[:limit]]

    def intelligent_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        relevant = self.similarity_search(query, limit)
        if not relevant:
            return {
                "answer": f"没有找到与“{query}”明显匹配的重构包。可以尝试按型号、组件、版本号或补丁关键词重新搜索。",
                "relevantPackages": [],
                "query": query,
                "searchResultsCount": 0,
                "recommendedPackageIds": [],
            }

        lines = [f"已找到 {len(relevant)} 个相关重构包，建议优先查看匹配度最高的包："]
        for index, package in enumerate(relevant[:3], start=1):
            patch_text = "补丁包" if package.get("metadata", {}).get("isPatch") else "完整包"
            lines.append(
                f"{index}. {package.get('name')}，版本 {package.get('version')}，类型 {package.get('packageType')}，{patch_text}。"
            )
        return {
            "answer": "\n".join(lines),
            "relevantPackages": relevant,
            "query": query,
            "searchResultsCount": len(relevant),
            "recommendedPackageIds": [str(pkg.get("id")) for pkg in relevant[:1] if pkg.get("id")],
        }

    def suggestions(self, query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []
        return [
            f"{query} 最新版本",
            f"{query} 补丁包",
            f"{query} 完整包",
            f"lingxi-10 {query}",
            f"lingxi-07a {query}",
        ]

    def package_to_text(self, package: dict[str, Any]) -> str:
        metadata = package.get("metadata", {}) or {}
        components = ", ".join(str(item.get("name", item)) if isinstance(item, dict) else str(item) for item in metadata.get("components", []))
        tags = ", ".join(str(item) for item in metadata.get("tags", []))
        return " ".join(
            str(part)
            for part in [
                package.get("name"),
                package.get("version"),
                package.get("packageType"),
                metadata.get("description"),
                components,
                tags,
                "patch" if metadata.get("isPatch") else "",
            ]
            if part
        )

    def score_package(self, query: str, package: dict[str, Any]) -> float:
        text = self.package_to_text(package).lower()
        tokens = [token for token in re.split(r"[\s,;，。/\\_-]+", query.lower()) if token]
        if not tokens:
            return 0
        score = 0.0
        for token in tokens:
            if token in text:
                score += 1.0
            if token and token in str(package.get("name", "")).lower():
                score += 1.0
        return score / len(tokens)

    def calculate_hash(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def determine_package_type(self, filename: str) -> str:
        lower = filename.lower()
        if "lingxi-10" in lower or "lx10" in lower:
            return PACKAGE_TYPES["LINGXI_10"]
        if "lingxi-07a" in lower or "lx07a" in lower:
            return PACKAGE_TYPES["LINGXI_07A"]
        if "ka-tx" in lower or "katx" in lower:
            return PACKAGE_TYPES["KA_TX"]
        if "ka-rx" in lower or "karx" in lower:
            return PACKAGE_TYPES["KA_RX"]
        if "config" in lower:
            return PACKAGE_TYPES["CONFIG"]
        if "lingxi-06-thrid" in lower or "trd" in lower:
            return PACKAGE_TYPES["LINGXI_06TRD"]
        return PACKAGE_TYPES["LINGXI_10"]

    def parse_version(self, filename: str) -> Optional[str]:
        match = re.search(r"[Vv]?(\d+(?:\.\d+)*)", filename)
        return match.group(1) if match else None

    def extract_components(self, filename: str) -> list[str]:
        lower = filename.lower()
        components = []
        checks = {
            "galaxy_core": "galaxy_core_network",
            "satellite": "satellite_app_server",
            "oam": "oam",
            "cucp": "cucp",
            "cuup": "cuup",
            "du": "du",
        }
        for key, value in checks.items():
            if key in lower:
                components.append(value)
        return components

    def normalize_components(self, components: list[Any], version: Any = None) -> list[Any]:
        normalized = []
        for component in components:
            if isinstance(component, dict):
                normalized.append(component)
            else:
                normalized.append({"name": str(component), "version": version or ""})
        return normalized

    def _unique_upload_path(self, filename: str) -> Path:
        dest = self.uploads_dir / Path(filename).name
        if not dest.exists():
            return dest
        stem = dest.name[:-7] if dest.name.lower().endswith(".tar.gz") else dest.stem
        suffix = ".tar.gz" if dest.name.lower().endswith(".tar.gz") else dest.suffix
        return self.uploads_dir / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"

    def _sort_value(self, package: dict[str, Any], key: str) -> Any:
        if key == "createdAt":
            value = package.get("createdAt") or ""
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)
        return package.get(key) or ""

    def cleanup_file(self, path: Path) -> None:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


raven_package_service = RavenPackageService()
