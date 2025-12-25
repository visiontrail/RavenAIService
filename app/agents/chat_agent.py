"""
LangChain + LangGraph 对话智能体
用于 Raven AI 前端 (AIChat.vue) 的后端处理框架。
"""
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from app.agents.tools import (
    clear_device_prompt_context,
    device_prompt_tool,
    set_device_prompt_context,
)
from app.config import settings

logger = logging.getLogger(__name__)


class ChatState(TypedDict, total=False):
    """LangGraph 状态"""

    messages: List[BaseMessage]
    system_prompt: str
    session_id: Optional[str]
    target_device_id: Optional[str]
    target_device_name: Optional[str]
    device_capabilities_prompt: Optional[str]
    tool_call_count: int  # 追踪工具调用次数，防止无限递归


def _make_llm() -> Any:
    """
    构建 OpenAI 兼容的聊天模型，统一使用 DeepSeek 配置。
    """
    api_key = getattr(settings, "deepseek_api_key", None)
    base_url = getattr(settings, "deepseek_base_url", None)
    model = getattr(settings, "llm_model_name", None)

    if not api_key or not base_url or not model:
        raise RuntimeError("DeepSeek 配置缺失，无法初始化聊天模型")

    try:
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_API_BASE"] = base_url
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=settings.llm_temperature,
            streaming=True,
        )
        # 记录模型名称，便于响应时回传
        if not hasattr(llm, "model_name"):
            llm.model_name = model
        logger.info("ChatAgent: using DeepSeek model %s", llm.model_name)
        return llm
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法初始化聊天模型: {exc}") from exc


class ChatAgent:
    """
    极简 LangGraph 工作流：
    - State: messages + system_prompt (+ device/session context)
    - Node: call_llm -> tool_router -> call_tools -> call_llm
    """

    def __init__(self, max_tool_calls: int = 5):
        logger.info("==================== ChatAgent 初始化开始 ====================")
        self.default_system_prompt = (
            "你是 Raven AI，对话助手，擅长日志分析、RAG 方案和平台使用指导。"
            "回答要简洁可执行，如需操作请给出具体指引。"
        )
        self.max_tool_calls = max_tool_calls  # 最大工具调用次数限制
        logger.info(f"ChatAgent: 设置最大工具调用次数: {self.max_tool_calls}")

        logger.info("ChatAgent: 正在初始化 LLM...")
        base_llm = _make_llm()
        self.tools = [device_prompt_tool]
        self.llm = base_llm.bind_tools(self.tools)
        self.base_llm = base_llm
        self.model_name = getattr(base_llm, "model_name", settings.llm_model_name)
        logger.info(f"ChatAgent: LLM 初始化完成，模型名称: {self.model_name}")

        logger.info("ChatAgent: 正在构建 Prompt 模板...")
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        logger.info("ChatAgent: Prompt 模板构建完成")

        logger.info("ChatAgent: 正在构建 LangGraph 工作流...")
        self.graph = self._build_graph()
        self.tool_node = ToolNode(self.tools)
        logger.info("==================== ChatAgent 初始化完成 ====================")

    def _build_graph(self):
        logger.info("ChatAgent: 开始构建 StateGraph...")
        workflow = StateGraph(ChatState)
        workflow.add_node("call_llm", self._call_model)
        workflow.add_node("call_tools", self._call_tools)
        workflow.set_entry_point("call_llm")
        workflow.add_conditional_edges(
            "call_llm",
            self._tool_router,
            {
                END: END,
                "call_tools": "call_tools",
            },
        )
        workflow.add_edge("call_tools", "call_llm")

        # 设置 recursion_limit，防止无限递归
        # 每次循环包含：call_llm -> call_tools，所以实际工具调用次数 = recursion_limit / 2
        # 我们设置为 max_tool_calls * 2 + 2（额外的缓冲）
        recursion_limit = self.max_tool_calls * 2 + 2
        compiled = workflow.compile()
        logger.info(f"ChatAgent: StateGraph 构建完成，recursion_limit={recursion_limit}")
        return compiled

    async def _call_model(self, state: ChatState) -> ChatState:
        """单节点调用 LLM 并返回新的状态。"""
        logger.info("========== _call_model 开始执行 ==========")
        logger.info(f"_call_model: 使用模型: {self.model_name}")
        logger.info(f"_call_model: 收到的消息数量: {len(state.get('messages', []))}")

        base_prompt = state.get("system_prompt") or self.default_system_prompt
        system_prompt = self._build_system_prompt(
            base_prompt,
            target_device_id=state.get("target_device_id"),
            target_device_name=state.get("target_device_name"),
            session_id=state.get("session_id"),
            device_capabilities_prompt=state.get("device_capabilities_prompt"),
        )
        logger.info(f"_call_model: 系统提示词长度: {len(system_prompt)} 字符")

        logger.info("_call_model: 正在格式化 Prompt...")
        prompt_messages = self.prompt.format_messages(
            system_prompt=system_prompt,
            messages=state.get("messages", []),
        )
        logger.info(f"_call_model: Prompt 格式化完成，消息数量: {len(prompt_messages)}")
        
        logger.info(f"_call_model: 正在调用 LLM (模型: {self.model_name})...")
        try:
            ai_message: AIMessage = await self.llm.ainvoke(prompt_messages)
            content_len = len(ai_message.content) if ai_message.content else 0
            logger.info(f"_call_model: LLM 调用成功 (模型: {self.model_name})，回复长度: {content_len} 字符")

            # 记录工具调用信息
            if hasattr(ai_message, "tool_calls") and ai_message.tool_calls:
                logger.info(f"_call_model: 模型请求调用 {len(ai_message.tool_calls)} 个工具")
                for idx, tool_call in enumerate(ai_message.tool_calls):
                    tool_name = getattr(tool_call, "name", "unknown") if hasattr(tool_call, "name") else tool_call.get("name", "unknown")
                    logger.info(f"_call_model: 工具请求 #{idx + 1}: {tool_name}")
            else:
                logger.info("_call_model: 模型未请求工具调用，将结束对话")

            if ai_message.content:
                content_preview = str(ai_message.content)[:100]
                logger.info(f"_call_model: 回复内容预览: {content_preview}...")
            else:
                logger.warning("_call_model: 警告 - 模型返回了空内容")
        except Exception as e:
            logger.error(f"_call_model: LLM 调用失败 (模型: {self.model_name}): {str(e)}", exc_info=True)
            raise
        
        updated_messages = list(state.get("messages", [])) + [ai_message]
        logger.info(f"_call_model: 更新后的消息总数: {len(updated_messages)}")
        logger.info("========== _call_model 执行完成 ==========")

        # 返回状态，保持 tool_call_count 不变
        return {
            "messages": updated_messages,
            "system_prompt": base_prompt,
            "session_id": state.get("session_id"),
            "target_device_id": state.get("target_device_id"),
            "target_device_name": state.get("target_device_name"),
            "device_capabilities_prompt": state.get("device_capabilities_prompt"),
            "tool_call_count": state.get("tool_call_count", 0),
        }

    async def _call_tools(self, state: ChatState) -> ChatState:
        """执行工具调用，将工具结果写回消息列表。"""
        logger.info("========== _call_tools 开始执行 ==========")

        # 增加工具调用计数
        tool_call_count = state.get("tool_call_count", 0) + 1
        logger.info(f"_call_tools: 当前工具调用次数: {tool_call_count}/{self.max_tool_calls}")

        # 记录具体的工具调用信息
        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls"):
            tool_calls = getattr(last_message, "tool_calls", [])
            logger.info(f"_call_tools: 检测到 {len(tool_calls)} 个工具调用")
            for idx, tool_call in enumerate(tool_calls):
                tool_name = getattr(tool_call, "name", "unknown") if hasattr(tool_call, "name") else tool_call.get("name", "unknown")
                tool_args = getattr(tool_call, "args", {}) if hasattr(tool_call, "args") else tool_call.get("args", {})
                logger.info(f"_call_tools: 工具 #{idx + 1}: {tool_name}, 参数: {tool_args}")

        set_device_prompt_context(
            state.get("session_id"),
            state.get("target_device_id"),
            state.get("system_prompt") or self.default_system_prompt,
        )
        try:
            tool_updates = await self.tool_node.ainvoke(state)
        finally:
            clear_device_prompt_context()

        updated_messages = list(state.get("messages", []))
        if isinstance(tool_updates, Dict) and tool_updates.get("messages"):
            new_messages = tool_updates["messages"]
            updated_messages.extend(new_messages)
            # 记录工具返回结果
            for msg in new_messages:
                if hasattr(msg, "content"):
                    content_preview = str(msg.content)[:200] if msg.content else "(empty)"
                    logger.info(f"_call_tools: 工具返回内容预览: {content_preview}")

        logger.info(f"_call_tools: 工具执行完成，新增消息数: {len(updated_messages) - len(state.get('messages', []))}")
        logger.info("========== _call_tools 执行完成 ==========")
        return {
            "messages": updated_messages,
            "system_prompt": state.get("system_prompt") or self.default_system_prompt,
            "session_id": state.get("session_id"),
            "target_device_id": state.get("target_device_id"),
            "target_device_name": state.get("target_device_name"),
            "device_capabilities_prompt": state.get("device_capabilities_prompt"),
            "tool_call_count": tool_call_count,  # 更新计数
        }

    def _tool_router(self, state: ChatState) -> str:
        """根据最新 AIMessage 是否包含工具调用决定分支，同时检查递归限制。"""
        # 首先检查是否超过最大工具调用次数
        tool_call_count = state.get("tool_call_count", 0)
        if tool_call_count >= self.max_tool_calls:
            logger.warning(
                f"_tool_router: 已达到最大工具调用次数 ({tool_call_count}/{self.max_tool_calls})，终止工具调用"
            )
            return END

        # 检查是否有工具调用需求
        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
            logger.info(f"_tool_router: 检测到工具调用，当前计数: {tool_call_count}/{self.max_tool_calls}")
            return "call_tools"

        logger.info("_tool_router: 无工具调用，结束流程")
        return END

    def _build_system_prompt(
        self,
        base_prompt: Optional[str],
        target_device_id: Optional[str],
        target_device_name: Optional[str],
        session_id: Optional[str],
        device_capabilities_prompt: Optional[str] = None,
    ) -> str:
        """为当前轮次拼接设备上下文的系统提示。"""
        prompt = base_prompt or self.default_system_prompt
        if not target_device_id:
            return prompt

        device_label = target_device_name or target_device_id
        session_hint = session_id or "当前会话ID"
        prompt = (
            f"{prompt}\n\n[Device Link]\n"
            f"当前对话目标设备: {device_label} (ID: {target_device_id})。\n"
            "如需让该设备回答，请调用工具 device_prompt，将用户问题写入 prompt，"
            f"并携带 session_id={session_hint} 与 target_device_id。"
            "收到工具结果后，用中文向用户总结其中的 answer，并保留 topic_id 供追踪。"
        )
        if device_capabilities_prompt:
            prompt = f"{prompt}\n\n[设备能力提示]\n{device_capabilities_prompt}"
        return prompt

    def invoke(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_device_name: Optional[str] = None,
        device_capabilities_prompt: Optional[str] = None,
    ) -> ChatState:
        """同步调用（主要用于调试或同步场景）"""
        logger.info("==================== invoke 同步调用开始 ====================")
        logger.info(f"invoke: 接收到 {len(messages)} 条消息")
        logger.info(f"invoke: 系统提示词: {'自定义' if system_prompt else '默认'}")

        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
            "session_id": session_id,
            "target_device_id": target_device_id,
            "target_device_name": target_device_name,
            "device_capabilities_prompt": device_capabilities_prompt,
            "tool_call_count": 0,  # 初始化工具调用计数
        }
        logger.info("invoke: 正在调用 graph.invoke...")
        try:
            # 配置 recursion_limit
            config = {"recursion_limit": self.max_tool_calls * 2 + 2}
            result = self.graph.invoke(state, config=config)
            logger.info(f"invoke: graph.invoke 调用成功，返回消息数: {len(result.get('messages', []))}")
            logger.info("==================== invoke 同步调用完成 ====================")
            return result
        except Exception as e:
            logger.error(f"invoke: graph.invoke 调用失败: {str(e)}", exc_info=True)
            raise

    async def ainvoke(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_device_name: Optional[str] = None,
        device_capabilities_prompt: Optional[str] = None,
    ) -> ChatState:
        """异步调用，供 FastAPI 路由使用"""
        logger.info("==================== ainvoke 异步调用开始 ====================")
        logger.info(f"ainvoke: 接收到 {len(messages)} 条消息")
        logger.info(f"ainvoke: 系统提示词: {'自定义' if system_prompt else '默认'}")

        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
            "session_id": session_id,
            "target_device_id": target_device_id,
            "target_device_name": target_device_name,
            "device_capabilities_prompt": device_capabilities_prompt,
            "tool_call_count": 0,  # 初始化工具调用计数
        }
        logger.info("ainvoke: 正在调用 graph.ainvoke...")
        set_device_prompt_context(
            session_id,
            target_device_id,
            system_prompt or self.default_system_prompt,
        )
        try:
            # 配置 recursion_limit
            config = {"recursion_limit": self.max_tool_calls * 2 + 2}
            result = await self.graph.ainvoke(state, config=config)
            logger.info(f"ainvoke: graph.ainvoke 调用成功，返回消息数: {len(result.get('messages', []))}")
            logger.info("==================== ainvoke 异步调用完成 ====================")
            return result
        except Exception as e:
            logger.error(f"ainvoke: graph.ainvoke 调用失败: {str(e)}", exc_info=True)
            raise
        finally:
            clear_device_prompt_context()

    @staticmethod
    def _chunk_to_text(chunk: Any) -> str:
        """提取流式分片的文本内容，兼容不同格式。"""
        content = getattr(chunk, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content) if content else ""

    async def astream(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_device_name: Optional[str] = None,
        device_capabilities_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """流式返回模型输出的分片文本；若需要设备工具则退回整段输出。"""
        logger.info("==================== astream 流式调用开始 ====================")
        system_prompt = system_prompt or self.default_system_prompt

        # 当需要设备联动时，走完整 LangGraph（无逐字流式），保障工具调用。
        if target_device_id:
            logger.info("astream: 检测到 target_device_id，使用非流式工具分支")
            state = await self.ainvoke(
                messages=messages,
                system_prompt=system_prompt,
                session_id=session_id,
                target_device_id=target_device_id,
                target_device_name=target_device_name,
                device_capabilities_prompt=device_capabilities_prompt,
            )
            ai_message = next((m for m in reversed(state.get("messages", [])) if isinstance(m, AIMessage)), None)
            if ai_message and ai_message.content:
                yield str(ai_message.content)
            logger.info("==================== astream 流式调用完成（工具分支）====================")
            return

        # 纯模型对话保持逐字流式。
        prompt_messages = self.prompt.format_messages(
            system_prompt=self._build_system_prompt(system_prompt, None, None, session_id),
            messages=messages,
        )
        logger.info(f"astream: 准备流式输出，消息数: {len(prompt_messages)}")

        async for chunk in self.base_llm.astream(prompt_messages):
            text = self._chunk_to_text(chunk)
            if not text:
                continue
            yield text

        logger.info("==================== astream 流式调用完成 ====================")
