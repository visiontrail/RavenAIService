"""把共享日志分析快照复制到当前用户的独立会话和工作空间。"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.log_analysis.workspace import cleanup, prepare, prepare_many, WorkspaceError
from app.exceptions import FileNotFoundError
from app.models.user import ChatSessionSummary, User
from app.services.chat_history_service import chat_history_service
from app.services.log_analysis_chat_service import log_analysis_chat_service
from app.services.log_service import log_service

logger = logging.getLogger(__name__)


async def fork_log_analysis(db: AsyncSession, log_id: str, user: User, locale: str) -> ChatSessionSummary:
    """只复制详情页已经保存的轮次，不继承原用户运行状态或可变工作目录。"""
    try:
        records = await log_service.get_analysis_group_records(db, log_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "日志不存在 / Log not found") from exc

    primary = log_service._group_primary_record(records)
    _, metadata = log_service._record_metadata(primary)
    extra = metadata.extra_fields if metadata else {}
    turns = extra.get("ai_analysis_conversation")
    turns = [turn for turn in turns if isinstance(turn, dict)] if isinstance(turns, list) else []
    if not turns and isinstance(extra.get("ai_analysis_result"), dict) and extra["ai_analysis_result"]:
        turns = [extra["ai_analysis_result"]]
    if not turns:
        raise HTTPException(422, "暂无可 Fork 的日志分析对话 / No analysis conversation to fork")

    session_id = str(uuid.uuid4())
    filenames = [record.original_filename or record.filename for record in records]
    context_meta = {"filename": filenames[0]}
    exchanges = []
    saved_task = extra.get("ai_analysis_task")
    saved_query = saved_task.get("query") if isinstance(saved_task, dict) else None
    for turn in turns:
        question = str(turn.get("query") or saved_query or primary.issue_description or (
            "请分析这些日志附件。" if locale == "zh" else "Analyze these log attachments."
        ))
        # 历史格式没有 answer；先归一化正文和建议再使用既有结果展示格式。
        result = dict(turn)
        legacy = turn.get("final_result")
        if isinstance(legacy, dict):
            result.setdefault("answer", legacy.get("content"))
            result.setdefault("summary", legacy.get("summary"))
            result.setdefault("recommended_actions", legacy.get("recommendations"))
        if not result.get("answer"):
            result["answer"] = turn.get("final_report") or turn.get("content")
        answer = log_analysis_chat_service._format_agent_result(
            result, question=question, context_meta=context_meta
        )
        exchanges.append((question, answer))

    ctx = None
    registry_path = log_analysis_chat_service._context_file(session_id)
    try:
        prepare_workspace = prepare if len(records) == 1 else prepare_many
        ctx = await asyncio.to_thread(
            prepare_workspace, records[0] if len(records) == 1 else records,
            require_metadata=False,
        )
        ctx.metadata["project_id"] = primary.project_id
        if primary.project_id is not None:
            await asyncio.to_thread(log_analysis_chat_service._inject_repo_info_from_project_id, ctx, primary.project_id)
        else:
            await asyncio.to_thread(log_analysis_chat_service._inject_repo_info, ctx)
        task = json.loads(Path(ctx.task_json_path).read_text(encoding="utf-8"))
        task.update({"session_id": session_id, "owner_user_id": user.id, "forked_from_log_id": primary.id})
        Path(ctx.task_json_path).write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        now = datetime.utcnow().isoformat()
        meta = {
            "session_id": session_id,
            "owner_user_id": user.id,
            "owner_user": log_analysis_chat_service._user_snapshot(user),
            "task_id": ctx.task_id,
            "temp_dir": ctx.temp_dir,
            "logs_dir": ctx.logs_dir,
            "repo_dir": ctx.repo_dir,
            "task_json_path": ctx.task_json_path,
            "log_id": primary.id,
            "log_ids": [record.id for record in records],
            "forked_from_log_id": primary.id,
            "filename": filenames[0],
            "filenames": filenames,
            "attachments": task.get("attachments", []),
            "project_id": primary.project_id,
            "project_repo_id": primary.project_id,
            "created_at": now,
            "updated_at": now,
        }
        for index, (question, answer) in enumerate(exchanges):
            session = await chat_history_service.save_exchange(
                db, user_id=user.id, session_id=session_id,
                user_content=question + ("\n\n[日志附件] " + "、".join(filenames) if index == 0 else ""),
                ai_content=answer,
            )
        session.title = (("Fork · " if locale == "en" else "日志 Fork · ") + filenames[0])[:60]
        log_analysis_chat_service._save_context(session_id, meta)
        await db.commit()
        return ChatSessionSummary.model_validate(session, from_attributes=True)
    except BaseException as exc:
        await db.rollback()
        registry_path.unlink(missing_ok=True)
        if ctx is not None:
            await asyncio.to_thread(cleanup, ctx)
        if isinstance(exc, (WorkspaceError, OSError)):
            logger.warning("Log Fork preparation failed log_id=%s: %s", log_id, type(exc).__name__)
            raise HTTPException(422, "无法建立独立日志工作空间，请检查原日志附件后重试 / Cannot prepare the workspace; check the original attachments and retry") from exc
        raise
