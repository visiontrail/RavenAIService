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
        self.default_system_prompt = (
            "你是 Raven AI，对话助手，擅长日志分析、RAG 方案和平台使用指导。"
            "回答要简洁可执行，如需操作请给出具体指引。"
        )
        self.llm = _make_llm()
        self.model_name = getattr(self.llm, "model_name", settings.llm_model_name)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ChatState)
        workflow.add_node("call_llm", self._call_model)
        workflow.set_entry_point("call_llm")
        workflow.add_edge("call_llm", END)
        return workflow.compile()

    def _call_model(self, state: ChatState) -> ChatState:
        """单节点调用 LLM 并返回新的状态。"""
        system_prompt = state.get("system_prompt") or self.default_system_prompt
        prompt_messages = self.prompt.format_messages(
            system_prompt=system_prompt,
            messages=state.get("messages", []),
        )
        ai_message: AIMessage = self.llm.invoke(prompt_messages)
        updated_messages = list(state.get("messages", [])) + [ai_message]
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
        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
        }
        return self.graph.invoke(state)

    async def ainvoke(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
    ) -> ChatState:
        """异步调用，供 FastAPI 路由使用"""
        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
        }
        return await self.graph.ainvoke(state)
