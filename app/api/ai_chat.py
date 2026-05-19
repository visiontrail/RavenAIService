"""
AI 对话相关 API
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.users import get_optional_user
from app.models.chat import ChatRequest, ChatResponse
from app.models.database import get_db
from app.services.ai_chat_service import ai_chat_service
from app.services.log_analysis_chat_service import log_analysis_chat_service

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
        return StreamingResponse(generator, media_type="text/event-stream")
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat stream request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/log-analysis/stream", summary="主对话日志分析（流式）")
async def log_analysis_stream_endpoint(
    message: str = Form("", description="用户问题"),
    session_id: Optional[str] = Form(None, description="对话会话ID"),
    history: Optional[str] = Form(None, description="前端传入的历史消息 JSON"),
    remember: bool = Form(True, description="是否保存到会话历史"),
    file: Optional[UploadFile] = File(None, description="可选日志包附件"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    logger.info("=" * 80)
    logger.info("接收到主对话日志分析请求")
    logger.info("message: %s...", message[:100])
    logger.info("session_id: %s, has_file=%s", session_id, bool(file and file.filename))
    logger.info("=" * 80)
    try:
        generator = log_analysis_chat_service.stream(
            message=message,
            session_id=session_id,
            history_json=history,
            file=file,
            remember=remember,
            db=db,
            user=current_user,
        )
        return StreamingResponse(generator, media_type="text/event-stream")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Log analysis chat stream request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
