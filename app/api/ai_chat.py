"""
AI 对话相关 API
"""
import logging
from fastapi import APIRouter, HTTPException

from app.models.chat import ChatRequest, ChatResponse
from app.services.ai_chat_service import ai_chat_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse, summary="AI 对话")
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    logger.info("=" * 80)
    logger.info("接收到 AI 对话请求")
    logger.info(f"请求消息: {request.message[:100]}...")
    logger.info(f"session_id: {request.session_id}")
    logger.info(f"历史记录条数: {len(request.history) if request.history else 0}")
    logger.info("=" * 80)
    try:
        response = await ai_chat_service.chat(request)
        logger.info("AI 对话请求处理成功")
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI chat request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
