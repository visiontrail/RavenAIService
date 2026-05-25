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
import threading
import time
import uuid
from dataclasses import dataclass, field
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
_JOB_POLL_INTERVAL_SECONDS = 0.2
# Keep finished Jobs around for late /result polling and post-disconnect reconnect.
_JOB_RETENTION_SECONDS = 30 * 60


@dataclass
class AgentJob:
    """In-process record of a running or recently-finished log-analysis Agent task.

    The Agent runs as a long-lived asyncio task; SSE streams are just views
    that subscribe to ``events``. Cancellation is best-effort and signaled via
    ``cancel_event`` (checked between SDK messages inside the Agent loop).
    """

    session_id: str
    task_id: str
    context_meta: Dict[str, Any]
    question: str
    user_id: Optional[Any]
    remember: bool
    filename: Optional[str]
    started_at: float
    # run_id projects this job into the unified chat_agent_runs lifecycle so
    # the sidebar overlay and /active-run snapshot can see log-analysis runs
    # alongside DeviceAgent runs.
    run_id: str = ""
    owner_scope: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    # Raw AgentTraceEvent payloads (no SSE wrapper) for late-subscriber
    # full-history replay and for the final `done` frame to carry the
    # complete trace.
    trace_events: List[Dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cancel_requested: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event)
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None


class LogAnalysisChatService:
    """Run LogAnalysisAgent from the main chat composer."""

    def __init__(self) -> None:
        self.registry_dir = Path(settings.code_repo_clone_base_dir) / "chat_log_analysis_sessions"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        # In-process Job registry. Single-process uvicorn deployment is assumed.
        # If we move to multi-worker, swap this for a Redis-backed registry.
        self._jobs: Dict[str, AgentJob] = {}

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
        owner_scope: Optional[str] = None,
        project_repo_id: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """SSE stream for one log-analysis turn.

        Behavior:
        - If an in-flight Job exists for ``session_id``: subscribe and replay
          buffered events. A new file upload while a Job is running is rejected.
        - Else: start a new Job (with file upload, or follow-up against the
          previously-saved workspace context).

        SSE client disconnects do NOT cancel the underlying Agent Job — the
        Job runs to completion or until explicit cancel/timeout, and its
        result is persisted to DB so it can be retrieved later via the
        ``/result`` endpoint or by reconnecting.
        """
        effective_session_id = session_id or str(uuid.uuid4())
        question = (message or "").strip()
        uploaded_filename = self._uploaded_filename(file)

        self._evict_old_jobs()

        yield self._sse_event({"event": "session", "session_id": effective_session_id})

        logger.info(
            "log-analysis chat: stream started session_id=%s has_file=%s filename=%s",
            effective_session_id,
            bool(uploaded_filename),
            uploaded_filename or "-",
        )

        existing_job = self._jobs.get(effective_session_id)

        # Subscribe path: in-flight Job already exists for this session.
        if existing_job is not None and not existing_job.done:
            if uploaded_filename:
                yield self._sse_event(
                    {
                        "event": "error",
                        "message": "本会话已有正在进行的分析任务，请先取消或等待完成后再上传新日志包。",
                    }
                )
                return
            yield self._sse_event(
                {
                    "event": "log_analysis_status",
                    "message": "已重新连接到正在运行的分析任务，继续推送已积累的进度...",
                    "reattached": True,
                }
            )
            async for chunk in self._subscribe(existing_job):
                yield chunk
            return

        # Re-subscribe path: Job already done and still cached; replay terminal events.
        if existing_job is not None and existing_job.done and not uploaded_filename and not question:
            async for chunk in self._subscribe(existing_job):
                yield chunk
            return

        # Validate explicit project_repo_id up-front so we fail fast before
        # writing any file or running heavy work.
        if project_repo_id is not None and db is not None:
            try:
                from app.services import project_repo_service

                repo = await project_repo_service.get_by_id(db, project_repo_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("log-analysis chat: 校验 project_repo_id 失败: %s", exc)
                repo = None
            if not repo or not repo.enabled:
                yield self._sse_event(
                    {
                        "event": "error",
                        "message": "所选项目仓库不存在或已禁用，请重新选择。",
                    }
                )
                return

        # Start a new Job.
        try:
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
                    question=question or "请分析这个日志包，给出概览、可疑异常和下一步建议。",
                    file=file,
                    user=user,
                    project_repo_id=project_repo_id,
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

            if not question:
                question = "请分析这个日志包，给出概览、可疑异常和下一步建议。"

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

            run_id = str(uuid.uuid4())
            effective_owner_scope = owner_scope or (
                f"user:{user.id}" if getattr(user, "id", None) else "anon:legacy"
            )
            job = AgentJob(
                session_id=effective_session_id,
                task_id=ctx.task_id,
                context_meta=context_meta,
                question=question,
                user_id=getattr(user, "id", None),
                remember=bool(remember),
                filename=context_meta.get("filename"),
                started_at=time.monotonic(),
                run_id=run_id,
                owner_scope=effective_owner_scope,
            )
            self._jobs[effective_session_id] = job
            # Project the job into the unified chat_agent_runs lifecycle so
            # the active-run endpoint and sidebar overlay can show it.
            await self._register_chat_run(job, ctx)
            job.task = asyncio.create_task(self._run_job_async(job, ctx))

            logger.info(
                "log-analysis chat: agent job scheduled session_id=%s task_id=%s temp_dir=%s",
                effective_session_id,
                ctx.task_id,
                ctx.temp_dir,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("log-analysis chat stream failed to start job: %s", exc, exc_info=True)
            yield self._sse_event({"event": "error", "message": str(exc)})
            return

        try:
            async for chunk in self._subscribe(job):
                yield chunk
        except asyncio.CancelledError:
            # SSE was cancelled by client disconnect. The Job keeps running
            # in the background; the client (or another) can reattach.
            logger.warning(
                "log-analysis chat stream cancelled (client disconnect): session_id=%s job still running",
                effective_session_id,
            )
            raise

    async def _run_job_async(self, job: AgentJob, ctx: WorkspaceContext) -> None:
        """Background Agent task. Survives SSE disconnects; persists to DB on completion."""
        try:
            # Sync emitter: append the raw AgentTraceEvent to job.trace_events
            # (for late-subscriber replay + final `done` payload) AND push an
            # SSE-shaped frame onto job.events so live subscribers see the
            # event right away. The lambda is invoked from the Agent's thread
            # (via asyncio.to_thread → run_sync → asyncio.run); list.append
            # is thread-safe under the GIL.
            def _emit_trace(event: Dict[str, Any]) -> None:
                job.trace_events.append(event)
                job.events.append({"event": "agent_trace", **event})

            result = await asyncio.to_thread(
                LogAnalysisAgent().run_sync, ctx, job.cancel_event, _emit_trace
            )
            job.result = result
            answer_text = self._format_agent_result(
                result, question=job.question, context_meta=job.context_meta
            )
            job.answer = answer_text

            await self._persist_job_result(job, result, answer_text)
            self._touch_context(job.session_id, result=result, answer=answer_text)

            job.events.append(
                {
                    "event": "done",
                    "session_id": job.session_id,
                    "answer": answer_text,
                    "model": result.get("model"),
                    "result": result,
                    "trace_summary": result.get("trace_summary"),
                    "trace_events": result.get("trace_events"),
                }
            )
            logger.info(
                "log-analysis chat: agent job completed session_id=%s task_id=%s status=%s error_kind=%s duration=%ss",
                job.session_id,
                job.task_id,
                result.get("status"),
                result.get("error_kind"),
                int(time.monotonic() - job.started_at),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "log-analysis chat: agent job failed session_id=%s: %s",
                job.session_id,
                exc,
                exc_info=True,
            )
            job.error = str(exc)
            job.events.append({"event": "error", "message": str(exc)})
        finally:
            job.done = True
            job.finished_at = time.monotonic()
            # Project terminal state into chat_agent_runs + chat_run_service so
            # snapshot endpoints and sidebar overlay reflect completion.
            await self._finalize_chat_run(job)

    async def _register_chat_run(self, job: AgentJob, ctx: WorkspaceContext) -> None:
        """Create a ``chat_agent_runs`` row and register a ChatRunJob shadow.

        Best-effort: persistence and registry failures are logged but do not
        block the actual agent execution (the LogAnalysisChatService remains
        the source of truth for execution; chat_run_service mirrors state).
        """
        from app.models.database import db_manager
        from app.models.user import ChatAgentRun
        from app.services.chat_run_service import (
            RUN_STATUS_RUNNING,
            chat_run_service,
        )

        request_payload: Dict[str, Any] = {
            "filename": job.filename,
            "log_id": job.context_meta.get("log_id"),
            "log_type": job.context_meta.get("log_type"),
            "project_repo_id": job.context_meta.get("project_repo_id"),
        }

        # Register the in-memory ChatRunJob first so even if DB write fails
        # the sidebar/active-run endpoint still surfaces the running task.
        try:
            chat_run_service.register_external_job(
                run_id=job.run_id,
                session_id=job.session_id,
                user_id=str(job.user_id) if job.user_id is not None else None,
                owner_scope=job.owner_scope,
                agent_kind="log_analysis",
                user_message=job.question,
                request_payload=request_payload,
                events_ref=job.events,
                trace_events_ref=job.trace_events,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: chat_run_service register failed run_id=%s: %s",
                job.run_id,
                exc,
            )

        if db_manager.session_factory is None:
            return
        try:
            async with db_manager.session_factory() as db:
                try:
                    row = ChatAgentRun(
                        id=job.run_id,
                        session_id=job.session_id,
                        user_id=(
                            str(job.user_id) if job.user_id is not None else None
                        ),
                        owner_scope=job.owner_scope or "anon:legacy",
                        agent_kind="log_analysis",
                        status=RUN_STATUS_RUNNING,
                        user_message=job.question or "",
                        request_json=json.dumps(request_payload, ensure_ascii=False),
                        workspace_path=ctx.temp_dir,
                        started_at=datetime.utcnow(),
                    )
                    db.add(row)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: chat_agent_runs row insert failed run_id=%s: %s",
                job.run_id,
                exc,
            )

    async def _finalize_chat_run(self, job: AgentJob) -> None:
        """Update ``chat_agent_runs`` terminal state and clear active pointer.

        Status mapping:
        - ``cancel_requested`` → ``cancelled``
        - ``job.error`` → ``failed``
        - otherwise → ``succeeded``
        """
        if not job.run_id:
            return

        from app.models.database import db_manager
        from app.models.user import ChatAgentRun
        from app.services.chat_run_service import (
            RUN_STATUS_CANCELLED,
            RUN_STATUS_FAILED,
            RUN_STATUS_SUCCEEDED,
            chat_run_service,
        )

        # Prefer the agent's own status when available — cancel_requested may
        # have been set after the agent already produced an answer.
        agent_status = ""
        if isinstance(job.result, dict):
            agent_status = str(job.result.get("status") or "")
        if job.error:
            terminal_status = RUN_STATUS_FAILED
        elif agent_status == "cancelled" or (
            job.cancel_requested and not job.answer
        ):
            terminal_status = RUN_STATUS_CANCELLED
        else:
            terminal_status = RUN_STATUS_SUCCEEDED

        result_model = ""
        if isinstance(job.result, dict):
            model_value = job.result.get("model")
            if isinstance(model_value, str):
                result_model = model_value

        try:
            chat_run_service.mark_external_terminal(
                job.run_id,
                terminal_status,
                answer=job.answer or "",
                model=result_model,
                error=job.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: chat_run_service finalize failed run_id=%s: %s",
                job.run_id,
                exc,
            )

        if db_manager.session_factory is None:
            return
        try:
            async with db_manager.session_factory() as db:
                try:
                    from sqlalchemy import select

                    result = await db.execute(
                        select(ChatAgentRun).where(ChatAgentRun.id == job.run_id)
                    )
                    row = result.scalar_one_or_none()
                    if row is None:
                        return
                    row.status = terminal_status
                    row.answer = job.answer or None
                    row.model = result_model or None
                    row.error = job.error
                    row.finished_at = datetime.utcnow()
                    try:
                        row.trace_events_json = json.dumps(
                            list(job.trace_events), ensure_ascii=False, default=str
                        )
                    except Exception:  # noqa: BLE001
                        row.trace_events_json = None
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: chat_agent_runs finalize failed run_id=%s: %s",
                job.run_id,
                exc,
            )

    async def _persist_job_result(
        self,
        job: AgentJob,
        result: Dict[str, Any],
        answer_text: str,
    ) -> None:
        """Open a fresh DB session and persist analysis result + chat exchange.

        Uses its own session because the original request DB session is already
        closed by the time this method runs (Job outlives the HTTP request).
        """
        from app.models.database import db_manager

        if db_manager.session_factory is None:
            logger.warning("log-analysis chat: db not initialized; skipping persistence")
            return

        try:
            async with db_manager.session_factory() as db:
                try:
                    await self._save_analysis_result(
                        db=db, context_meta=job.context_meta, result=result
                    )
                    if job.remember and job.user_id is not None:
                        await self._persist_exchange(
                            db=db,
                            user_id=job.user_id,
                            session_id=job.session_id,
                            question=job.question,
                            answer=answer_text,
                            filename=job.filename,
                        )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: failed to persist job result session_id=%s: %s",
                job.session_id,
                exc,
                exc_info=True,
            )

    async def _subscribe(self, job: AgentJob) -> AsyncIterator[str]:
        """Yield SSE chunks for this Job. Replays the full event buffer to
        late subscribers, then polls for new events until the Job is done.

        Late subscribers automatically get the full historical ``agent_trace``
        stream because those frames live in ``job.events`` next to the
        coarse ``log_analysis_status`` frames — the ``sent`` cursor walks
        every appended event in order.

        Heartbeats: if no event has been buffered for
        ``_AGENT_PROGRESS_INTERVAL_SECONDS`` (15s) while the Job is still
        running, yield a ``system_notice{kind: heartbeat}`` frame to keep
        proxies / browsers from closing the SSE stream as idle.
        """
        sent = 0
        last_activity = time.monotonic()
        while True:
            saw_new = False
            while sent < len(job.events):
                yield self._sse_event(job.events[sent])
                sent += 1
                saw_new = True
            if saw_new:
                last_activity = time.monotonic()
            if job.done:
                return
            await asyncio.sleep(_JOB_POLL_INTERVAL_SECONDS)
            now = time.monotonic()
            if now - last_activity >= _AGENT_PROGRESS_INTERVAL_SECONDS:
                elapsed = int(now - job.started_at)
                yield self._sse_event(
                    {
                        "event": "agent_trace",
                        "type": "system_notice",
                        "task_id": job.task_id,
                        "kind": "heartbeat",
                        "elapsed_seconds": elapsed,
                        "timestamp": time.time(),
                    }
                )
                last_activity = now

    def cancel(self, session_id: str, user: Optional[User] = None) -> bool:
        """Request cancellation of the in-flight Agent Job for ``session_id``.

        Returns True if a cancel signal was sent, False if no in-flight job.
        Raises PermissionError if the caller is not the Job owner.
        """
        job = self._jobs.get(session_id or "")
        if job is None or job.done:
            return False
        if user is not None and job.user_id is not None and getattr(user, "id", None) != job.user_id:
            raise PermissionError("当前用户无权取消这个分析任务")
        if job.cancel_requested:
            return True
        job.cancel_requested = True
        job.cancel_event.set()
        job.events.append(
            {
                "event": "log_analysis_status",
                "message": "已收到取消请求，正在等待 Agent 退出（最多一条 SDK 消息的延迟）...",
                "cancel_requested": True,
            }
        )
        logger.info("log-analysis chat: cancel requested session_id=%s", session_id)
        return True

    def get_status(self, session_id: str, user: Optional[User] = None) -> Dict[str, Any]:
        """Return the current state snapshot of the Job for polling clients."""
        job = self._jobs.get(session_id or "")
        if job is None:
            return {"session_id": session_id, "status": "not_found"}
        if user is not None and job.user_id is not None and getattr(user, "id", None) != job.user_id:
            raise PermissionError("当前用户无权查看这个分析任务")
        now = time.monotonic()
        elapsed = int((job.finished_at or now) - job.started_at)
        return {
            "session_id": session_id,
            "status": "done" if job.done else "running",
            "cancel_requested": job.cancel_requested,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "elapsed_seconds": elapsed,
            "filename": job.filename,
            "events": list(job.events),
            "result": job.result,
            "answer": job.answer or "",
            "error": job.error,
        }

    def _evict_old_jobs(self) -> None:
        """Lazy cleanup of Jobs that finished more than _JOB_RETENTION_SECONDS ago."""
        if not self._jobs:
            return
        cutoff = time.monotonic() - _JOB_RETENTION_SECONDS
        stale = [
            sid
            for sid, job in self._jobs.items()
            if job.done and (job.finished_at or 0) < cutoff
        ]
        for sid in stale:
            self._jobs.pop(sid, None)
            logger.debug("log-analysis chat: evicted finished job session_id=%s", sid)

    async def _create_context_from_upload(
        self,
        *,
        db: Optional[AsyncSession],
        session_id: str,
        question: str,
        file: UploadFile,
        user: Optional[User],
        project_repo_id: Optional[int] = None,
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
        # 立即提交：SSE 流会持有 request 的 AsyncSession 很久（一次 Agent 运行常
        # 达数分钟）；只 flush 不 commit 会让 SQLite 的写锁一直被持有，导致并发
        # 上传/重构包检索触发 "database is locked"。
        await db.commit()

        # When the user explicitly chose a project, skip metadata.json
        # extraction validation in the workspace and resolve repo_info
        # directly from the registry.
        ctx = prepare(log_record, require_metadata=project_repo_id is None)
        ctx.metadata.update(
            {
                "question": question,
                "log_type": inferred_type.value,
                "hints": "",
            }
        )
        if project_repo_id is not None:
            self._inject_repo_info_from_project_id(ctx, project_repo_id)
        else:
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

    def _inject_repo_info_from_project_id(
        self, ctx: WorkspaceContext, project_repo_id: int
    ) -> None:
        try:
            from app.tasks.ai_analysis import (
                SessionLocal,
                _inject_repo_info_from_project_id,
            )

            sync_session = SessionLocal()
            try:
                ok = _inject_repo_info_from_project_id(
                    sync_session, ctx, project_repo_id
                )
                if not ok:
                    logger.warning(
                        "log-analysis chat: project_repo_id=%s not resolvable; "
                        "agent will run without explicit repo_info",
                        project_repo_id,
                    )
            finally:
                sync_session.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "log-analysis chat: repo_info injection from project_id failed: %s", exc
            )

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
        user_id: Any,
        session_id: str,
        question: str,
        answer: str,
        filename: Optional[str],
    ) -> None:
        """Persist the user / assistant exchange. Caller owns commit/rollback."""
        user_content = question
        if filename:
            user_content = f"{question}\n\n[日志附件] {filename}"
        session = await chat_history_service.save_exchange(
            db,
            user_id=user_id,
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
                        user_id=user_id,
                        session_id=session_id,
                        title=title,
                    )
            except Exception:
                pass

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
