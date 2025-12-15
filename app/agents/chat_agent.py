"""
LangChain + LangGraph 对话智能体
用于 Raven AI 前端 (AIChat.vue) 的后端处理框架。
"""
import logging
import os
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models import ChatOpenAI
from langgraph.graph import END, StateGraph

from app.config import settings

logger = logging.getLogger(__name__)


class ChatState(TypedDict):
    """LangGraph 状态"""
    messages: List[BaseMessage]
    system_prompt: str


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
            temperature=settings.llm_temperature,
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
    - State: messages + system_prompt
    - Node: call_llm -> 直接调用 LLM，并将回复追加到消息列表
    """

    def __init__(self):
        logger.info("==================== ChatAgent 初始化开始 ====================")
        self.default_system_prompt = (
            "你是 Raven AI，对话助手，擅长日志分析、RAG 方案和平台使用指导。"
            "回答要简洁可执行，如需操作请给出具体指引。"
        )
        logger.info("ChatAgent: 正在初始化 LLM...")
        self.llm = _make_llm()
        self.model_name = getattr(self.llm, "model_name", settings.llm_model_name)
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
        logger.info("==================== ChatAgent 初始化完成 ====================")

    def _build_graph(self):
        logger.info("ChatAgent: 开始构建 StateGraph...")
        workflow = StateGraph(ChatState)
        workflow.add_node("call_llm", self._call_model)
        workflow.set_entry_point("call_llm")
        workflow.add_edge("call_llm", END)
        compiled = workflow.compile()
        logger.info("ChatAgent: StateGraph 构建并编译完成")
        return compiled

    def _call_model(self, state: ChatState) -> ChatState:
        """单节点调用 LLM 并返回新的状态。"""
        logger.info("========== _call_model 开始执行 ==========")
        logger.info(f"_call_model: 使用模型: {self.model_name}")
        logger.info(f"_call_model: 收到的消息数量: {len(state.get('messages', []))}")
        
        system_prompt = state.get("system_prompt") or self.default_system_prompt
        logger.info(f"_call_model: 系统提示词长度: {len(system_prompt)} 字符")
        
        logger.info("_call_model: 正在格式化 Prompt...")
        prompt_messages = self.prompt.format_messages(
            system_prompt=system_prompt,
            messages=state.get("messages", []),
        )
        logger.info(f"_call_model: Prompt 格式化完成，消息数量: {len(prompt_messages)}")
        
        logger.info(f"_call_model: 正在调用 LLM (模型: {self.model_name})...")
        try:
            ai_message: AIMessage = self.llm.invoke(prompt_messages)
            logger.info(f"_call_model: LLM 调用成功 (模型: {self.model_name})，回复长度: {len(ai_message.content)} 字符")
            logger.info(f"_call_model: 回复内容预览: {ai_message.content[:100]}...")
        except Exception as e:
            logger.error(f"_call_model: LLM 调用失败 (模型: {self.model_name}): {str(e)}", exc_info=True)
            raise
        
        updated_messages = list(state.get("messages", [])) + [ai_message]
        logger.info(f"_call_model: 更新后的消息总数: {len(updated_messages)}")
        logger.info("========== _call_model 执行完成 ==========")
        return {
            "messages": updated_messages,
            "system_prompt": system_prompt,
        }

    def invoke(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
    ) -> ChatState:
        """同步调用（主要用于调试或同步场景）"""
        logger.info("==================== invoke 同步调用开始 ====================")
        logger.info(f"invoke: 接收到 {len(messages)} 条消息")
        logger.info(f"invoke: 系统提示词: {'自定义' if system_prompt else '默认'}")
        
        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
        }
        logger.info("invoke: 正在调用 graph.invoke...")
        try:
            result = self.graph.invoke(state)
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
    ) -> ChatState:
        """异步调用，供 FastAPI 路由使用"""
        logger.info("==================== ainvoke 异步调用开始 ====================")
        logger.info(f"ainvoke: 接收到 {len(messages)} 条消息")
        logger.info(f"ainvoke: 系统提示词: {'自定义' if system_prompt else '默认'}")
        
        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
        }
        logger.info("ainvoke: 正在调用 graph.ainvoke...")
        try:
            result = await self.graph.ainvoke(state)
            logger.info(f"ainvoke: graph.ainvoke 调用成功，返回消息数: {len(result.get('messages', []))}")
            logger.info("==================== ainvoke 异步调用完成 ====================")
            return result
        except Exception as e:
            logger.error(f"ainvoke: graph.ainvoke 调用失败: {str(e)}", exc_info=True)
            raise
