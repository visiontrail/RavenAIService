"""
AI 对话相关 API
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.users import get_optional_user
from app.models.chat import ChatRequest, ChatResponse
from app.models.database import get_db
from app.services.ai_chat_service import ai_chat_service
from app.services.chat_history_service import chat_history_service
from app.services.title_generator_service import summarize_user_message
from app.services.log_analysis_chat_service import log_analysis_chat_service


class LogAnalysisCancelRequest(BaseModel):
    session_id: str


class SummarizeRequest(BaseModel):
    """Immediate session-title summary for a single user message."""

    user_content: str
    session_id: Optional[str] = None
    max_length: int = 16
    persist: bool = True


class SummarizeResponse(BaseModel):
    success: bool = True
    message: str = "ok"
    summary: str
    session_id: Optional[str] = None
    persisted: bool = False


class ChatPermissionResolveRequest(BaseModel):
    """HITL 决策提交体（前端弹窗 -> 后端 broker）。

    ``session_id`` 可选；提供时用于 O(1) 定位 broker，否则后端会扫描注册表。
    ``updated_args`` 仅在 ``decision="allow"`` 且用户编辑参数时透传给 SDK。
    """

    decision: str
    updated_args: Optional[dict] = None
    message: Optional[str] = None
    session_id: Optional[str] = None


class ChatPermissionResolveResponse(BaseModel):
    success: bool = True
    message: str = "ok"
    request_id: str
    decision: str

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse, summary="AI 对话")
async def chat_endpoint(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
) -> ChatResponse:
    logger.info("=" * 80)
    logger.info("接收到 AI 对话请求")
    logger.info(f"请求消息: {request.message[:100]}...")
    logger.info(f"session_id: {request.session_id}")
    logger.info(f"历史记录条数: {len(request.history) if request.history else 0}")
    logger.info("=" * 80)
    try:
        response = await ai_chat_service.chat(request, db=db, user=current_user)
        logger.info("AI 对话请求处理成功")
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/stream", summary="AI 对话（流式）")
async def chat_stream_endpoint(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    logger.info("=" * 80)
    logger.info("接收到 AI 对话流式请求")
    logger.info(f"请求消息: {request.message[:100]}...")
    logger.info(f"session_id: {request.session_id}")
    logger.info(f"历史记录条数（前端传入）: {len(request.history) if request.history else 0}")
    if request.history:
        logger.info("历史记录概览（前端传入）:")
        for i, msg in enumerate(request.history[:5]):  # 只显示前5条
            role = msg.role if hasattr(msg, 'role') else 'unknown'
            content_preview = (msg.content[:50] if hasattr(msg, 'content') else '')
            logger.info(f"  [{i+1}] {role}: {content_preview}...")
        if len(request.history) > 5:
            logger.info(f"  ... (还有 {len(request.history) - 5} 条)")
    logger.info("=" * 80)
    try:
        generator = ai_chat_service.chat_stream(request, db=db, user=current_user)
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat stream request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/summarize", response_model=SummarizeResponse, summary="对用户输入立即生成简短会话摘要")
async def chat_summarize_endpoint(
    payload: SummarizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
) -> SummarizeResponse:
    content = (payload.user_content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="user_content 不能为空")

    max_length = max(4, min(40, int(payload.max_length or 16)))
    summary = await summarize_user_message(content, max_length=max_length)

    persisted = False
    resolved_session_id = payload.session_id
    if payload.persist and current_user is not None:
        try:
            if not resolved_session_id:
                resolved_session_id = str(uuid.uuid4())
            session = await chat_history_service.ensure_session(
                db, current_user.id, session_id=resolved_session_id
            )
            await chat_history_service.update_session_title(
                db,
                user_id=current_user.id,
                session_id=session.id,
                title=summary,
            )
            await db.commit()
            resolved_session_id = session.id
            persisted = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("chat/summarize: 持久化标题失败: %s", exc)

    return SummarizeResponse(
        summary=summary,
        session_id=resolved_session_id,
        persisted=persisted,
    )


@router.post(
    "/chat/permissions/{request_id}/resolve",
    response_model=ChatPermissionResolveResponse,
    summary="DeviceAgent HITL 工具调用裁决",
)
async def chat_permission_resolve_endpoint(
    request_id: str,
    payload: ChatPermissionResolveRequest,
    current_user=Depends(get_optional_user),  # noqa: ARG001  保留鉴权钩子位
) -> ChatPermissionResolveResponse:
    """Resolve a pending ``can_use_tool`` request raised by a DeviceAgent run.

    Behaviour:
    - 400 if ``decision`` is not ``"allow"``/``"deny"``, or ``updated_args`` is not dict.
    - 404 if no broker holds ``request_id`` (already resolved, timed out, or unknown).
    - 200 with ``{request_id, decision}`` echoed back on success.
    """
    decision = (payload.decision or "").strip().lower()
    if decision not in {"allow", "deny"}:
        raise HTTPException(status_code=400, detail="decision must be 'allow' or 'deny'")

    if payload.updated_args is not None and not isinstance(payload.updated_args, dict):
        raise HTTPException(status_code=400, detail="updated_args must be a JSON object")

    decision_payload: dict = {"decision": decision}
    if payload.updated_args is not None:
        decision_payload["updated_args"] = payload.updated_args
    if payload.message is not None:
        msg = str(payload.message).strip()
        if msg:
            decision_payload["message"] = msg

    registry = ai_chat_service.permission_broker_registry

    # 1. Direct lookup by session_id when the client supplies one.
    if payload.session_id:
        broker = registry.get(payload.session_id)
        if broker is not None and broker.resolve(request_id, decision_payload):
            return ChatPermissionResolveResponse(request_id=request_id, decision=decision)

    # 2. Fallback: scan all live brokers. The registry is per-session and typically
    #    holds < 10 entries per user, so the linear walk is fine.
    for broker in list(registry.values()):
        if broker.resolve(request_id, decision_payload):
            return ChatPermissionResolveResponse(request_id=request_id, decision=decision)

    raise HTTPException(
        status_code=404,
        detail=f"Permission request not found or already resolved: {request_id}",
    )


@router.post("/log-analysis/stream", summary="主对话日志分析（流式）")
async def log_analysis_stream_endpoint(
    message: str = Form("", description="用户问题"),
    session_id: Optional[str] = Form(None, description="对话会话ID"),
    history: Optional[str] = Form(None, description="前端传入的历史消息 JSON"),
    remember: bool = Form(True, description="是否保存到会话历史"),
    project_repo_id: Optional[int] = Form(
        None,
        description="可选：项目仓库注册表 ID。提供时跳过 metadata.json 校验，直接使用该项目的仓库信息。",
    ),
    file: Optional[UploadFile] = File(None, description="可选日志包附件"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    logger.info("=" * 80)
    logger.info("接收到主对话日志分析请求")
    logger.info("message: %s...", message[:100])
    logger.info(
        "session_id: %s, has_file=%s, project_repo_id=%s",
        session_id, bool(file and file.filename), project_repo_id,
    )
    logger.info("=" * 80)
    try:
        generator = log_analysis_chat_service.stream(
            message=message,
            session_id=session_id,
            history_json=history,
            file=file,
            remember=remember,
            project_repo_id=project_repo_id,
            db=db,
            user=current_user,
        )
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Log analysis chat stream request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/log-analysis/cancel", summary="取消进行中的日志分析任务")
async def log_analysis_cancel_endpoint(
    payload: LogAnalysisCancelRequest,
    current_user=Depends(get_optional_user),
):
    try:
        ok = log_analysis_chat_service.cancel(payload.session_id, user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        return {"session_id": payload.session_id, "cancelled": False, "message": "未找到进行中的任务"}
    return {"session_id": payload.session_id, "cancelled": True}


@router.get("/log-analysis/result", summary="查询日志分析任务状态/结果（轮询兜底）")
async def log_analysis_result_endpoint(
    session_id: str = Query(..., description="对话会话 ID"),
    current_user=Depends(get_optional_user),
):
    try:
        return log_analysis_chat_service.get_status(session_id, user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
