"""
AI 对话服务：封装 LangGraph 智能体与简单会话记忆。
"""
import logging
import json
import uuid
from typing import AsyncIterator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.chat_agent import ChatAgent
from app.config import settings
from app.models.chat import ChatMessage, ChatRequest, ChatResponse
from app.models.device_link import DeviceInfo
from app.services.base import BaseService
from app.services.device_link_service import device_link_manager

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

    async def _build_device_capabilities_prompt(self, device_id: Optional[str]) -> Optional[str]:
        """Fetch device info and format its capabilities for system prompt injection."""
        if not device_id:
            return None
        try:
            device = await device_link_manager.get_device(device_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load device info for capabilities", exc_info=True, extra={"device_id": device_id})
            return None
        return self._format_device_capabilities(device)

    @staticmethod
    def _format_device_capabilities(device: Optional[DeviceInfo]) -> Optional[str]:
        if not device:
            return None
        capabilities = device.capabilities or {}
        mcp = capabilities.get("mcp") if isinstance(capabilities, dict) else None
        servers = (mcp or {}).get("servers") if isinstance(mcp, dict) else None
        if not servers:
            return None

        lines: list[str] = ["设备已上报的 MCP 能力如下，请在生成指令时参考："]
        for server in servers:
            if not isinstance(server, dict):
                continue
            name = server.get("name") or server.get("id") or "未知服务器"
            provider = server.get("provider")
            server_type = server.get("type")
            base_url = server.get("baseUrl") or server.get("base_url")
            description = server.get("description")

            header_parts = [name]
            detail_parts = [part for part in [provider, server_type, base_url] if part]
            if detail_parts:
                header_parts.append(f"({', '.join(str(p) for p in detail_parts)})")
            if description:
                header_parts.append(f"- {description}")
            lines.append(f"- {' '.join(header_parts)}")

            tools = server.get("tools") if isinstance(server.get("tools"), list) else []
            if tools:
                tool_lines = []
                for tool in tools:
                    if not isinstance(tool, dict):
                        continue
                    tool_name = tool.get("name") or "未命名工具"
                    tool_desc = tool.get("description")
                    entry = tool_name if not tool_desc else f"{tool_name}（{tool_desc}）"
                    tool_lines.append(entry)
                if tool_lines:
                    lines.append("  工具: " + "; ".join(tool_lines))

            prompts = server.get("prompts") if isinstance(server.get("prompts"), list) else []
            if prompts:
                prompt_lines = []
                for prompt in prompts:
                    if not isinstance(prompt, dict):
                        continue
                    prompt_name = prompt.get("name") or "未命名提示词"
                    prompt_desc = prompt.get("description")
                    entry = prompt_name if not prompt_desc else f"{prompt_name}（{prompt_desc}）"
                    prompt_lines.append(entry)
                if prompt_lines:
                    lines.append("  提示词: " + "; ".join(prompt_lines))

            resources = server.get("resources") if isinstance(server.get("resources"), list) else []
            if resources:
                resource_lines = []
                for resource in resources:
                    if not isinstance(resource, dict):
                        continue
                    res_name = resource.get("name") or resource.get("uri") or "资源"
                    res_desc = resource.get("description")
                    entry = res_name if not res_desc else f"{res_name}（{res_desc}）"
                    resource_lines.append(entry)
                if resource_lines:
                    lines.append("  资源: " + "; ".join(resource_lines))

        collected_at = (mcp or {}).get("collectedAt") or (mcp or {}).get("collected_at")
        if collected_at:
            lines.append(f"(以上能力同步时间: {collected_at})")

        return "\n".join(lines)

    async def chat(self, payload: ChatRequest) -> ChatResponse:
        logger.info("==================== AIChatService.chat 开始 ====================")
        logger.info(f"chat: 用户消息: {payload.message[:100]}...")
        logger.info(f"chat: session_id: {payload.session_id}")
        logger.info(f"chat: remember: {payload.remember}")
        logger.info(
            "chat: target device",
            extra={"target_device_id": payload.target_device_id, "target_device_name": payload.target_device_name},
        )
        
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

        device_capabilities_prompt = await self._build_device_capabilities_prompt(payload.target_device_id)

        # 调用 LangGraph 智能体
        logger.info("chat: 正在调用 agent.ainvoke...")
        try:
            state = await self.agent.ainvoke(
                messages=history_messages,
                system_prompt=payload.system_prompt,
                session_id=session_id,
                target_device_id=payload.target_device_id,
                target_device_name=payload.target_device_name,
                device_capabilities_prompt=device_capabilities_prompt,
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
            answer_text = str(ai_message.content)
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
        logger.info(f"chat_stream: remember: {payload.remember}")
        logger.info(
            "chat_stream: target device",
            extra={"target_device_id": payload.target_device_id, "target_device_name": payload.target_device_name},
        )

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

        device_capabilities_prompt = await self._build_device_capabilities_prompt(payload.target_device_id)

        # 需要设备联动时不做逐字流式，确保工具调用后再返回。
        if payload.target_device_id:
            logger.info("chat_stream: 目标设备存在，使用非流式工具分支")
            try:
                state = await self.agent.ainvoke(
                    messages=history_messages,
                    system_prompt=payload.system_prompt,
                    session_id=session_id,
                    target_device_id=payload.target_device_id,
                    target_device_name=payload.target_device_name,
                    device_capabilities_prompt=device_capabilities_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("chat_stream: 工具分支执行失败: %s", exc, exc_info=True)
                yield self._sse_event({"event": "error", "message": str(exc)})
                return

            messages = state.get("messages", history_messages)
            ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
            answer_text = str(ai_message.content) if ai_message else ""
            logger.info(
                "chat_stream: 工具分支完成",
                extra={"has_answer": bool(answer_text), "message_count": len(messages)},
            )

            if payload.remember:
                logger.info("chat_stream: 保存会话记忆（工具分支）")
                self.memory.save_history(session_id, messages)

            if answer_text:
                yield self._sse_event({"event": "chunk", "content": answer_text})

            yield self._sse_event(
                {
                    "event": "done",
                    "session_id": session_id,
                    "answer": answer_text,
                    "model": self.agent.model_name,
                    "messages": self._to_chat_messages(messages),
                }
            )
            logger.info("==================== AIChatService.chat_stream 完成（工具分支） ====================")
            return

        ai_chunks: List[str] = []
        try:
            async for token in self.agent.astream(
                messages=history_messages,
                system_prompt=payload.system_prompt,
                session_id=session_id,
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
            elif isinstance(msg, ToolMessage):
                role = "system"
            else:
                continue
            result.append(ChatMessage(role=role, content=str(msg.content)))
        return result

    @staticmethod
    def _chat_messages_to_dicts(messages: List[ChatMessage]) -> List[Dict[str, str]]:
        """将 ChatMessage 转为可 JSON 序列化的字典。"""
        dicts: List[Dict[str, str]] = []
        for msg in messages:
            try:
                dicts.append(msg.model_dump())
            except Exception:
                dicts.append({"role": msg.role, "content": msg.content})
        return dicts

    @staticmethod
    def _sse_event(payload: Dict[str, object]) -> str:
        """格式化 SSE 数据行。"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


ai_chat_service = AIChatService()
