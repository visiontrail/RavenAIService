"""
AI 对话服务：封装 LangGraph 智能体与简单会话记忆。
"""
import logging
import uuid
from typing import Dict, List

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agents.chat_agent import ChatAgent
from app.config import settings
from app.models.chat import ChatMessage, ChatRequest, ChatResponse
from app.services.base import BaseService

logger = logging.getLogger(__name__)


class _SessionMemory:
    """轻量级内存会话管理，仅存储近期轮次。"""

    def __init__(self, max_turns: int = 10):
        self._store: Dict[str, List[BaseMessage]] = {}
        self.max_turns = max_turns

    def get_history(self, session_id: str) -> List[BaseMessage]:
        return list(self._store.get(session_id, []))

    def save_history(self, session_id: str, messages: List[BaseMessage]) -> None:
        # 仅保留最近 N 轮，避免内存无限增长
        trim_size = max(self.max_turns * 2, 10)
        self._store[session_id] = messages[-trim_size:]


class AIChatService(BaseService):
    """Raven AI 对话服务"""

    def __init__(self):
        super().__init__()
        self.agent = ChatAgent()
        self.memory = _SessionMemory(max_turns=getattr(settings, "agent_short_term_window", 5))

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        session_id = payload.session_id or str(uuid.uuid4())
        # 前端传入的历史优先，其次取服务端记忆
        history_messages = (
            self._to_langchain_messages(payload.history)
            if payload.history
            else self.memory.get_history(session_id)
        )
        history_messages.append(HumanMessage(content=payload.message))

        # 调用 LangGraph 智能体
        state = await self.agent.ainvoke(
            messages=history_messages,
            system_prompt=payload.system_prompt,
        )
        messages = state.get("messages", history_messages)

        # 写回会话记忆
        if payload.remember:
            self.memory.save_history(session_id, messages)

        ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        answer_text = ai_message.content if ai_message else ""

        return ChatResponse(
            session_id=session_id,
            answer=answer_text,
            model=self.agent.model_name,
            messages=self._to_chat_messages(messages),
            message="ok",
        )

    @staticmethod
    def _to_langchain_messages(history: List[ChatMessage]) -> List[BaseMessage]:
        """将前端消息转换为 LangChain 消息"""
        converted: List[BaseMessage] = []
        for item in history:
            role = item.role.lower()
            if role in ("ai", "assistant"):
                converted.append(AIMessage(content=item.content))
            elif role == "system":
                converted.append(SystemMessage(content=item.content))
            else:
                converted.append(HumanMessage(content=item.content))
        return converted

    @staticmethod
    def _to_chat_messages(messages: List[BaseMessage]) -> List[ChatMessage]:
        """将 LangChain 消息转换为前端可用的结构"""
        result: List[ChatMessage] = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "ai"
            elif isinstance(msg, SystemMessage):
                role = "system"
            else:
                continue
            result.append(ChatMessage(role=role, content=str(msg.content)))
        return result


ai_chat_service = AIChatService()
