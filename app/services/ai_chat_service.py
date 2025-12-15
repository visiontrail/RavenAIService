"""
AI 对话服务：封装 LangGraph 智能体与简单会话记忆。
"""
import logging
import json
import uuid
from typing import AsyncIterator, Dict, List

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
        logger.info("==================== AIChatService.chat 开始 ====================")
        logger.info(f"chat: 用户消息: {payload.message[:100]}...")
        logger.info(f"chat: session_id: {payload.session_id}")
        logger.info(f"chat: remember: {payload.remember}")
        
        session_id = payload.session_id or str(uuid.uuid4())
        logger.info(f"chat: 使用的 session_id: {session_id}")
        
        # 前端传入的历史优先，其次取服务端记忆
        if payload.history:
            logger.info(f"chat: 使用前端传入的历史记录，条数: {len(payload.history)}")
            history_messages = self._to_langchain_messages(payload.history)
        else:
            logger.info("chat: 使用服务端记忆中的历史记录")
            history_messages = self.memory.get_history(session_id)
            logger.info(f"chat: 从记忆中获取到 {len(history_messages)} 条历史消息")
        
        history_messages.append(HumanMessage(content=payload.message))
        logger.info(f"chat: 添加用户消息后，总消息数: {len(history_messages)}")

        # 调用 LangGraph 智能体
        logger.info("chat: 正在调用 agent.ainvoke...")
        try:
            state = await self.agent.ainvoke(
                messages=history_messages,
                system_prompt=payload.system_prompt,
            )
            logger.info("chat: agent.ainvoke 调用成功")
        except Exception as e:
            logger.error(f"chat: agent.ainvoke 调用失败: {str(e)}", exc_info=True)
            raise
        
        messages = state.get("messages", history_messages)
        logger.info(f"chat: 从 state 中获取到 {len(messages)} 条消息")

        # 写回会话记忆
        if payload.remember:
            logger.info("chat: 保存会话记忆")
            self.memory.save_history(session_id, messages)

        ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if ai_message:
            answer_text = ai_message.content
            logger.info(f"chat: AI 回复长度: {len(answer_text)} 字符")
            logger.info(f"chat: AI 回复预览: {answer_text[:100]}...")
        else:
            answer_text = ""
            logger.warning("chat: 未找到 AI 回复消息")

        response = ChatResponse(
            session_id=session_id,
            answer=answer_text,
            model=self.agent.model_name,
            messages=self._to_chat_messages(messages),
            message="ok",
        )
        logger.info("==================== AIChatService.chat 完成 ====================")
        return response

    async def chat_stream(self, payload: ChatRequest) -> AsyncIterator[str]:
        """流式返回模型回复，SSE 格式。"""
        logger.info("==================== AIChatService.chat_stream 开始 ====================")
        logger.info(f"chat_stream: 用户消息: {payload.message[:100]}...")

        session_id = payload.session_id or str(uuid.uuid4())
        logger.info(f"chat_stream: 使用的 session_id: {session_id}")

        if payload.history:
            history_messages = self._to_langchain_messages(payload.history)
            logger.info(f"chat_stream: 前端传入历史记录 {len(history_messages)} 条")
        else:
            history_messages = self.memory.get_history(session_id)
            logger.info(f"chat_stream: 从记忆读取历史记录 {len(history_messages)} 条")

        history_messages.append(HumanMessage(content=payload.message))
        logger.info(f"chat_stream: 添加用户消息后共 {len(history_messages)} 条")

        # 先返回 session 事件，便于前端更新会话
        yield self._sse_event({"event": "session", "session_id": session_id})

        ai_chunks: List[str] = []
        try:
            async for token in self.agent.astream(
                messages=history_messages,
                system_prompt=payload.system_prompt,
            ):
                ai_chunks.append(token)
                yield self._sse_event({"event": "chunk", "content": token})
        except Exception as exc:  # noqa: BLE001
            logger.error("chat_stream: LLM 流式输出失败: %s", exc, exc_info=True)
            yield self._sse_event({"event": "error", "message": str(exc)})
            return

        answer_text = "".join(ai_chunks)
        logger.info(f"chat_stream: 拼接后的回复长度 {len(answer_text)}")

        messages = history_messages + [AIMessage(content=answer_text)]
        if payload.remember:
            logger.info("chat_stream: 写入会话记忆")
            self.memory.save_history(session_id, messages)

        yield self._sse_event(
            {
                "event": "done",
                "session_id": session_id,
                "answer": answer_text,
                "model": self.agent.model_name,
                "messages": self._to_chat_messages(messages),
            }
        )
        logger.info("==================== AIChatService.chat_stream 完成 ====================")

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

    @staticmethod
    def _sse_event(payload: Dict[str, object]) -> str:
        """格式化 SSE 数据行。"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


ai_chat_service = AIChatService()
