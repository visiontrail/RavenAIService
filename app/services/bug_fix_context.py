"""Persist analysis evidence before asynchronous repair dispatch.

Only evidence directories and redacted task metadata are copied, never a repo or
its credentials. References survive source workspace cleanup and retries.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.agents.log_analysis.trace import mask_input, mask_tokens
from app.config import settings


def context_root() -> Path:
    return Path(settings.bug_fix_context_dir).resolve()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in {"api_key", "git_token", "password", "access_token", "authorization"}
            else _redact(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return mask_input(value)


def capture_source(ctx: Any, *, images: list | None = None) -> dict:
    """Capture task metadata now; copy evidence at dispatch while ctx is alive."""
    task = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
    # Repository metadata can contain an authenticated clone URL.
    task = json.loads(mask_tokens(json.dumps(_redact(task), ensure_ascii=False)))
    return {
        "task": task,
        "workspace_dir": str(Path(ctx.temp_dir).resolve()),
        "images": [{"path": image.path, **image.to_meta()} for image in (images or [])],
    }


def _copy_evidence(source: Path, target: Path) -> None:
    if source.is_symlink():
        raise ValueError("source_context_symlink")
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy_evidence(child, target / child.name)
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    else:
        raise FileNotFoundError(f"source_context_missing: {source.name}")


def persist(task_id: str, source: dict, analysis_result: dict) -> dict:
    """Create an immutable per-task evidence snapshot on the shared data volume."""
    task_id = str(uuid.UUID(task_id))
    target = context_root() / task_id
    target.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Path(source["workspace_dir"])
        _copy_evidence(workspace / "logs", target / "logs")
        if (workspace / "images").exists():
            _copy_evidence(workspace / "images", target / "images")
        # Include originals even when the analysis provider only consumed OCR.
        for image in source.get("images", []):
            path = Path(image["path"])
            _copy_evidence(path, target / "images" / path.name)
        metadata = {
            "version": 1, "task": source["task"], "analysis_result": analysis_result,
            "images": [{**{k: v for k, v in item.items() if k != "path"},
                        "file": "images/" + Path(item["path"]).name}
                       for item in source.get("images", [])],
        }
        metadata = json.loads(mask_tokens(json.dumps(_redact(metadata), ensure_ascii=False)))
        manifest = []
        for path in sorted(target.rglob("*")):
            if path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                manifest.append({"path": path.relative_to(target).as_posix(),
                                 "size": path.stat().st_size,
                                 "sha256": digest})
        metadata["files"] = manifest
        (target / "context.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"version": 1, "snapshot_id": task_id}
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def restore(reference: dict, workspace: Path) -> dict:
    """Verify and restore all saved evidence; missing bytes fail explicitly."""
    source = context_root() / str(uuid.UUID(reference["snapshot_id"]))
    metadata = json.loads((source / "context.json").read_text(encoding="utf-8"))
    for item in metadata["files"]:
        path = source / item["path"]
        if not path.resolve().is_relative_to(source.resolve()) or path.is_symlink():
            raise ValueError("source_context_invalid_path")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"source_context_changed: {item['path']}")
        _copy_evidence(path, workspace / item["path"])
    # Historical tool output can exceed the SDK Read limit in a single JSON
    # line. Keep it losslessly available without forcing the reviewer to replay
    # the previous agent's entire tool transcript before reaching the evidence.
    analysis = metadata.get("analysis_result") or {}
    (workspace / "analysis_result.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    index = {
        **metadata,
        "analysis_result": {key: value for key, value in analysis.items()
                            if key not in {"tool_trace", "raw", "trace_events"}},
        "full_analysis_result_file": "analysis_result.json",
    }
    (workspace / "source_analysis.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def recover_legacy(session: Any, task: Any, log: Any) -> dict:
    """Reconstruct old tasks from their upload group and pre-dispatch chat history.

    This cannot recover deleted materials or the exact old prompt. Keep that
    limitation in the evidence; do not use a later analysis turn as the source.
    """
    from app.agents.log_analysis.workspace import prepare, prepare_many, cleanup
    from app.models.log import LogRecord
    from app.models.user import ChatMessage
    from app.services.chat_image_store import StoredImage, resolve_path
    from app.services.log_service import LogService

    metadata = json.loads(log.metadata_json or "{}")
    extra = metadata.get("extra_fields") or {}
    records = [log]
    if log.analysis_group_id:
        records = session.query(LogRecord).filter(
            LogRecord.analysis_group_id == log.analysis_group_id,
            LogRecord.is_deleted.is_(False),
        ).order_by(LogRecord.created_at, LogRecord.id).all()
    elif LogService._legacy_analysis_group_identity(log):
        candidates = session.query(LogRecord).filter(
            LogRecord.project_id == log.project_id, LogRecord.is_deleted.is_(False)
        ).all()
        records = [r for r in candidates if LogService._analysis_group_key(r) == LogService._analysis_group_key(log)]
    # The source record is always first, preserving task/log identity.
    records = [log] + [r for r in records if r.id != log.id]
    ctx = prepare_many(records, require_metadata=False) if len(records) > 1 else prepare(log, require_metadata=False)
    try:
        proposals = json.loads(task.proposed_fixes_json or "[]")
        turns = extra.get("ai_analysis_conversation") or []
        matching = [turn for turn in turns if turn.get("proposed_fixes") == proposals]
        analysis = matching[0] if matching else {
            "summary": task.summary, "proposed_fixes": proposals,
        }
        messages = []
        images = []
        missing = []
        session_id = extra.get("chat_session_id")
        if session_id:
            query = session.query(ChatMessage).filter(ChatMessage.session_id == session_id)
            if task.created_at:
                query = query.filter(ChatMessage.created_at <= task.created_at)
            messages = query.order_by(ChatMessage.created_at, ChatMessage.id).all()
            for message in messages:
                for item in json.loads(message.images_json or "[]"):
                    path = resolve_path(session_id, item.get("id", ""))
                    if path is None:
                        missing.append(item.get("id"))
                    else:
                        images.append(StoredImage(item['id'], item['media_type'], item.get('name', ''), item.get('size', 0), str(path)))
        task_data = json.loads(Path(ctx.task_json_path).read_text())
        task_data.update(
            question=analysis.get("query") or log.issue_description or "",
            hints=[{"role": message.role, "content": message.content} for message in messages],
            context_availability="legacy_reconstructed",
            limitations=["Exact dispatch-time prompt was not retained by the old version"],
            missing_image_ids=missing,
        )
        Path(ctx.task_json_path).write_text(json.dumps(task_data, ensure_ascii=False), encoding="utf-8")
        reference = persist(task.id, capture_source(ctx, images=images), analysis)
        reference["availability"] = "legacy_reconstructed"
        return reference
    finally:
        cleanup(ctx)
