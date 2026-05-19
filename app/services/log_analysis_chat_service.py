"""Main-chat Log Analysis Agent workflow.

This service keeps a persistent filesystem workspace per chat session so a
user can upload a log archive once and continue asking follow-up questions
against the same extracted logs and cloned repository.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.log_analysis.agent import LogAnalysisAgent
from app.agents.log_analysis.workspace import WorkspaceContext, cleanup, prepare
from app.config import settings
from app.models.chat import ChatMessage
from app.models.log import LogLevel, LogMetadata, LogStatus, LogType, LogUploadRequest
from app.models.user import User
from app.services.chat_history_service import chat_history_service
from app.services.log_service import log_service

logger = logging.getLogger(__name__)


_SESSION_KEY_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_AGENT_PROGRESS_INTERVAL_SECONDS = 15


class LogAnalysisChatService:
    """Run LogAnalysisAgent from the main chat composer."""

    def __init__(self) -> None:
        self.registry_dir = Path(settings.code_repo_clone_base_dir) / "chat_log_analysis_sessions"
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    async def stream(
        self,
        *,
        message: str,
        session_id: Optional[str],
        history_json: Optional[str],
        file: Optional[UploadFile],
        remember: bool,
        db: Optional[AsyncSession],
        user: Optional[User],
    ) -> AsyncIterator[str]:
        """SSE stream for one log-analysis turn."""
        effective_session_id = session_id or str(uuid.uuid4())
        question = (message or "").strip()
        uploaded_filename = self._uploaded_filename(file)

        if not question:
            question = "请分析这个日志包，给出概览、可疑异常和下一步建议。"

        yield self._sse_event({"event": "session", "session_id": effective_session_id})

        agent_task: Optional[asyncio.Task[Dict[str, Any]]] = None
        try:
            logger.info(
                "log-analysis chat: stream started session_id=%s has_file=%s filename=%s",
                effective_session_id,
                bool(uploaded_filename),
                uploaded_filename or "-",
            )
            if uploaded_filename:
                yield self._sse_event(
                    {
                        "event": "log_analysis_status",
                        "message": f"已接收日志包 `{uploaded_filename}`，正在建立分析工作区...",
                    }
                )
                ctx, context_meta = await self._create_context_from_upload(
                    db=db,
                    session_id=effective_session_id,
                    question=question,
                    file=file,
                    user=user,
                )
                yield self._sse_event(
                    {
                        "event": "log_analysis_context",
                        "session_id": effective_session_id,
                        "log_id": context_meta.get("log_id"),
                        "filename": context_meta.get("filename"),
                    }
                )
            else:
                loaded = self._load_context(effective_session_id, user=user)
                if loaded is None:
                    yield self._sse_event(
                        {
                            "event": "error",
                            "message": "请先在“日志分析”模式下上传一个包含 metadata.json 的日志包，再继续追问。",
                        }
                    )
                    return
                ctx, context_meta = loaded
                yield self._sse_event(
                    {
                        "event": "log_analysis_status",
                        "message": "已复用当前对话的日志分析工作区，正在基于已解压日志和已克隆代码继续分析...",
                    }
                )

            history_hint = await self._build_history_hint(
                db=db,
                user=user,
                session_id=effective_session_id,
                history_json=history_json,
            )
            self._bind_question_and_hints(ctx, question=question, hints=history_hint)

            yield self._sse_event(
                {
                    "event": "log_analysis_status",
                    "message": "Log Analysis Agent 正在读取日志与代码上下文...",
                }
            )

            logger.info(
                "log-analysis chat: agent run starting session_id=%s task_id=%s temp_dir=%s",
                effective_session_id,
                ctx.task_id,
                ctx.temp_dir,
            )
            started_at = time.monotonic()
            heartbeat_count = 0
            agent_task = asyncio.create_task(asyncio.to_thread(LogAnalysisAgent().run_sync, ctx))
            while not agent_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(agent_task),
                        timeout=_AGENT_PROGRESS_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    heartbeat_count += 1
                    elapsed = int(time.monotonic() - started_at)
                    logger.info(
                        "log-analysis chat: agent still running session_id=%s task_id=%s elapsed=%ss heartbeat=%d",
                        effective_session_id,
                        ctx.task_id,
                        elapsed,
                        heartbeat_count,
                    )
                    yield self._sse_event(
                        {
                            "event": "log_analysis_status",
                            "message": f"Log Analysis Agent 已运行 {elapsed}s，仍在分析日志与代码上下文...",
                            "elapsed_seconds": elapsed,
                            "heartbeat": heartbeat_count,
                        }
                    )

            result = agent_task.result()
            logger.info(
                "log-analysis chat: agent run completed session_id=%s task_id=%s status=%s error_kind=%s duration=%ss heartbeats=%d",
                effective_session_id,
                ctx.task_id,
                result.get("status"),
                result.get("error_kind"),
                int(time.monotonic() - started_at),
                heartbeat_count,
            )
            answer_text = self._format_agent_result(result, question=question, context_meta=context_meta)

            await self._save_analysis_result(db=db, context_meta=context_meta, result=result)
            self._touch_context(effective_session_id, result=result, answer=answer_text)

            if remember and user and db:
                await self._persist_exchange(
                    db=db,
                    user=user,
                    session_id=effective_session_id,
                    question=question,
                    answer=answer_text,
                    filename=context_meta.get("filename"),
                )

            yield self._sse_event(
                {
                    "event": "done",
                    "session_id": effective_session_id,
                    "answer": answer_text,
                    "model": result.get("model"),
                    "result": result,
                }
            )
            logger.info(
                "log-analysis chat: stream done session_id=%s answer_len=%d",
                effective_session_id,
                len(answer_text),
            )
        except asyncio.CancelledError:
            if agent_task and not agent_task.done():
                agent_task.cancel()
            logger.warning(
                "log-analysis chat stream cancelled: session_id=%s filename=%s",
                effective_session_id,
                uploaded_filename or "-",
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("log-analysis chat stream failed: %s", exc, exc_info=True)
            yield self._sse_event({"event": "error", "message": str(exc)})

    async def _create_context_from_upload(
        self,
        *,
        db: Optional[AsyncSession],
        session_id: str,
        question: str,
        file: UploadFile,
        user: Optional[User],
    ) -> Tuple[WorkspaceContext, Dict[str, Any]]:
        if db is None:
            raise RuntimeError("数据库会话不可用，无法保存日志包")

        old_context = self._load_context(session_id, user=user)
        old_ctx = old_context[0] if old_context else None

        inferred_type = self._infer_log_type_from_filename(file.filename or "")
        upload_request = LogUploadRequest(
            # Force OAM during upload so LogService does not start the protocol
            # stack processing Celery task; this endpoint owns analysis itself.
            log_type=LogType.OAM_ANTENNA,
            log_level=LogLevel.INFO,
            metadata=LogMetadata(
                source="ai_chat",
                extra_fields={"chat_session_id": session_id},
            ),
            issue_description=question,
        )
        log_info = await log_service.upload_log(db, file, upload_request)
        log_record = await log_service.get_by_id(db, log_info.id)
        if log_record is None:
            raise RuntimeError("日志包已上传但未找到数据库记录")

        log_record.log_type = inferred_type
        log_record.status = LogStatus.COMPLETED
        log_record.progress = 100.0
        log_record.issue_description = question
        await db.flush()

        ctx = prepare(log_record)
        ctx.metadata.update(
            {
                "question": question,
                "log_type": inferred_type.value,
                "hints": "",
            }
        )
        self._inject_repo_info(ctx)

        context_meta = {
            "session_id": session_id,
            "owner_user_id": getattr(user, "id", None),
            "task_id": ctx.task_id,
            "temp_dir": ctx.temp_dir,
            "logs_dir": ctx.logs_dir,
            "repo_dir": ctx.repo_dir,
            "task_json_path": ctx.task_json_path,
            "log_id": log_record.id,
            "filename": log_record.original_filename or log_record.filename,
            "log_type": inferred_type.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save_context(session_id, context_meta)
        if old_ctx and old_ctx.temp_dir != ctx.temp_dir:
            cleanup(old_ctx)
        return ctx, context_meta

    def _inject_repo_info(self, ctx: WorkspaceContext) -> None:
        try:
            from app.tasks.ai_analysis import SessionLocal, _inject_repo_info

            sync_session = SessionLocal()
            try:
                _inject_repo_info(sync_session, ctx)
            finally:
                sync_session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("log-analysis chat: repo_info injection skipped: %s", exc)

    def _bind_question_and_hints(self, ctx: WorkspaceContext, *, question: str, hints: str) -> None:
        try:
            from app.tasks.ai_analysis import _bind_query_to_workspace

            _bind_query_to_workspace(ctx, query=question, log_type=ctx.metadata.get("log_type"))
        except Exception:
            ctx.metadata["question"] = question

        task_path = Path(ctx.task_json_path)
        try:
            task_data = json.loads(task_path.read_text(encoding="utf-8"))
            if not isinstance(task_data, dict):
                task_data = {}
        except Exception:
            task_data = {}

        task_data["question"] = question
        task_data["hints"] = hints
        task_data["conversation_context"] = hints
        task_path.write_text(json.dumps(task_data, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.metadata["question"] = question
        ctx.metadata["hints"] = hints

    async def _build_history_hint(
        self,
        *,
        db: Optional[AsyncSession],
        user: Optional[User],
        session_id: str,
        history_json: Optional[str],
    ) -> str:
        messages: List[ChatMessage] = []
        if user and db:
            try:
                records = await chat_history_service.fetch_messages(
                    db,
                    user_id=user.id,
                    session_id=session_id,
                )
                messages = chat_history_service.to_chat_messages(records)
            except Exception:
                messages = []

        if not messages:
            messages = self._parse_client_history(history_json)

        if not messages:
            return ""

        recent = messages[-12:]
        lines = ["以下是同一对话中此前的上下文。用户可能会用“刚才/这个/继续”等指代，请结合这些内容理解当前问题："]
        for msg in recent:
            role = "用户" if msg.role == "user" else "助手"
            content = " ".join(str(msg.content or "").split())
            if len(content) > 1600:
                content = content[:1600] + "..."
            if content:
                lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def _parse_client_history(self, history_json: Optional[str]) -> List[ChatMessage]:
        if not history_json:
            return []
        try:
            raw = json.loads(history_json)
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        messages: List[ChatMessage] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            if role not in {"user", "ai", "assistant", "system"}:
                role = "user"
            content = str(item.get("content") or "")
            if content:
                messages.append(ChatMessage(role=role, content=content))
        return messages

    async def _persist_exchange(
        self,
        *,
        db: AsyncSession,
        user: User,
        session_id: str,
        question: str,
        answer: str,
        filename: Optional[str],
    ) -> None:
        user_content = question
        if filename:
            user_content = f"{question}\n\n[日志附件] {filename}"
        session = await chat_history_service.save_exchange(
            db,
            user_id=user.id,
            session_id=session_id,
            user_content=user_content,
            ai_content=answer,
            title_hint=question,
        )
        if (session.message_count or 0) <= 2:
            try:
                from app.services.ai_chat_service import ai_chat_service

                title = await asyncio.wait_for(
                    ai_chat_service.generate_session_title(user_content, answer),
                    timeout=8,
                )
                if title:
                    await chat_history_service.update_session_title(
                        db,
                        user_id=user.id,
                        session_id=session_id,
                        title=title,
                    )
            except Exception:
                pass
        await db.commit()

    async def _save_analysis_result(
        self,
        *,
        db: Optional[AsyncSession],
        context_meta: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        if not db or not context_meta.get("log_id"):
            return
        try:
            await log_service.save_ai_analysis_result(db, context_meta["log_id"], result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("log-analysis chat: failed to save result to log record: %s", exc)

    def _load_context(
        self,
        session_id: str,
        *,
        user: Optional[User],
        ignore_owner: bool = False,
    ) -> Optional[Tuple[WorkspaceContext, Dict[str, Any]]]:
        path = self._context_file(session_id)
        if not path.exists():
            return None
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        owner_user_id = meta.get("owner_user_id")
        if not ignore_owner and owner_user_id and getattr(user, "id", None) != owner_user_id:
            raise PermissionError("当前用户无权访问这个日志分析上下文")

        required_paths = ["temp_dir", "logs_dir", "repo_dir", "task_json_path"]
        if any(not meta.get(key) for key in required_paths):
            return None
        if not Path(meta["temp_dir"]).exists() or not Path(meta["task_json_path"]).exists():
            return None

        ctx = WorkspaceContext(
            task_id=meta.get("task_id") or Path(meta["temp_dir"]).name,
            temp_dir=meta["temp_dir"],
            logs_dir=meta["logs_dir"],
            repo_dir=meta["repo_dir"],
            task_json_path=meta["task_json_path"],
            metadata={
                "question": "",
                "log_type": meta.get("log_type"),
                "hints": "",
            },
        )
        return ctx, meta

    def _save_context(self, session_id: str, meta: Dict[str, Any]) -> None:
        path = self._context_file(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _touch_context(self, session_id: str, *, result: Dict[str, Any], answer: str) -> None:
        path = self._context_file(session_id)
        if not path.exists():
            return
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            meta["updated_at"] = datetime.utcnow().isoformat()
            meta["last_result_status"] = result.get("status")
            meta["last_error_kind"] = result.get("error_kind")
            meta["last_answer_excerpt"] = answer[:1000]
            self._save_context(session_id, meta)
        except Exception:
            logger.debug("log-analysis chat: failed to touch context", exc_info=True)

    def _context_file(self, session_id: str) -> Path:
        safe = _SESSION_KEY_RE.sub("_", session_id or "")
        if not safe:
            safe = str(uuid.uuid4())
        return self.registry_dir / f"{safe}.json"

    @staticmethod
    def _uploaded_filename(file: Optional[UploadFile]) -> Optional[str]:
        filename = getattr(file, "filename", None)
        if isinstance(filename, str) and filename.strip():
            return filename.strip()
        return None

    @staticmethod
    def _infer_log_type_from_filename(filename: str) -> LogType:
        name = (filename or "").lower()
        has_stack = "stack" in name
        has_oam = ("oam" in name) or ("om" in name)
        if has_stack and has_oam:
            return LogType.FULL
        if has_stack:
            return LogType.STACK
        return LogType.OAM_ANTENNA

    @staticmethod
    def _format_agent_result(
        result: Dict[str, Any],
        *,
        question: str,
        context_meta: Dict[str, Any],
    ) -> str:
        status = result.get("status") or "unknown"
        filename = context_meta.get("filename") or "当前日志包"
        model = result.get("model") or "unknown"
        duration = result.get("duration_seconds")
        answer = str(result.get("answer") or result.get("summary") or "").strip()
        summary = str(result.get("summary") or "").strip()

        lines: List[str] = [
            "**日志分析 Agent** 已完成本轮分析。",
            "",
            f"- 日志包：`{filename}`",
            f"- 问题：{question}",
            f"- 状态：`{status}`",
            f"- 模型：`{model}`" + (f"，耗时：{duration}s" if duration is not None else ""),
            "- 上下文：已保留本次解压日志与代码工作区，可在当前对话继续追问。",
        ]

        if result.get("error_kind"):
            lines.append(f"- 错误类型：`{result.get('error_kind')}`")

        if answer:
            lines.extend(["", "## 回答", answer])
        elif status == "schema_mismatch":
            lines.extend(["", "## 回答", "模型返回未命中结构化 JSON，我保留了原始输出供排查。"])

        if summary and summary != answer:
            lines.extend(["", "## 摘要", summary])

        hypotheses = result.get("root_cause_hypotheses")
        if isinstance(hypotheses, list) and hypotheses:
            lines.extend(["", "## 根因假设"])
            for item in hypotheses:
                if isinstance(item, dict):
                    text = item.get("hypothesis") or item.get("description") or json.dumps(item, ensure_ascii=False)
                    evidence = item.get("evidence")
                    lines.append(f"- {text}")
                    if isinstance(evidence, list) and evidence:
                        lines.append(f"  证据：{'; '.join(str(e) for e in evidence)}")
                else:
                    lines.append(f"- {item}")

        actions = result.get("recommended_actions")
        if isinstance(actions, list) and actions:
            lines.extend(["", "## 建议"])
            for item in actions:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('action') or item.get('description') or json.dumps(item, ensure_ascii=False)}")
                else:
                    lines.append(f"- {item}")

        keywords = result.get("related_keywords")
        if isinstance(keywords, list) and keywords:
            rendered = " ".join(f"`{str(keyword)}`" for keyword in keywords if str(keyword).strip())
            if rendered:
                lines.extend(["", "## 关键词", rendered])

        raw = result.get("raw")
        if status == "schema_mismatch" and isinstance(raw, str) and raw.strip():
            lines.extend(["", "## 原始输出", "```text", raw.strip()[:4000], "```"])

        return "\n".join(lines).strip()

    @staticmethod
    def _sse_event(payload: Dict[str, object]) -> str:
        safe_payload = jsonable_encoder(payload)
        return f"data: {json.dumps(safe_payload, ensure_ascii=False)}\n\n"


log_analysis_chat_service = LogAnalysisChatService()
