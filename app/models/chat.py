"""
AI 对话相关的请求/响应模型
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.models.base import BaseResponse


class ChatMessage(BaseModel):
    """前后端统一的对话消息模型"""
    role: Literal["user", "ai", "assistant", "system"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """单轮对话请求"""
    message: str = Field(..., description="用户输入")
    session_id: Optional[str] = Field(None, description="会话ID，未提供时由服务端生成")
    history: List[ChatMessage] = Field(default_factory=list, description="可选的历史消息，由前端传入")
    system_prompt: Optional[str] = Field(None, description="可选系统提示词，未提供时使用默认提示")
    target_device_id: Optional[str] = Field(None, description="可选的目标设备ID，用于设备联动")
    target_device_name: Optional[str] = Field(None, description="可选的目标设备名称，用于设备联动提示")
    remember: bool = Field(True, description="是否将本轮对话写入服务端内存会话")


class ChatResponse(BaseResponse):
    """对话响应"""
    session_id: str = Field(..., description="会话ID")
    answer: str = Field(..., description="模型回复内容")
    model: Optional[str] = Field(None, description="实际使用的模型名称")
    messages: List[ChatMessage] = Field(default_factory=list, description="包含本轮在内的对话消息")
    usage: Optional[Dict[str, Any]] = Field(None, description="可选的Token用量统计")
