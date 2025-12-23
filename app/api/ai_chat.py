"""
AI 对话相关 API
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.users import get_optional_user
from app.models.chat import ChatRequest, ChatResponse
from app.models.database import get_db
from app.services.ai_chat_service import ai_chat_service

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
    logger.info(f"历史记录条数: {len(request.history) if request.history else 0}")
    logger.info("=" * 80)
    try:
        generator = ai_chat_service.chat_stream(request, db=db, user=current_user)
        return StreamingResponse(generator, media_type="text/event-stream")
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat stream request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
