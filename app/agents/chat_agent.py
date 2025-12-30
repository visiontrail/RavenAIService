""" 
LangChain + LangGraph 对话智能体
用于 Raven AI 前端 (AIChat.vue) 的后端处理框架。

本版引入 ReAct/规划循环 + 设备 device_prompt 协议化调度，支持：
- MCP 工具理解（利用 device_capabilities_prompt）
- 多步 Plan -> Act -> Observe -> Next 循环
- device_prompt 单操作护栏与提示词协议
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from app.agents.tools import (
    clear_device_prompt_context,
    device_prompt,
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
    plan: List[Dict[str, Any]]
    step_index: int
    observations: List[Any]
    last_device_topic_id: Optional[str]
    last_device_answer: Optional[str]
    needs_user_input: bool
    replan: bool
    tool_call_count: int  # 追踪工具调用次数，防止无限递归
    progress_events: List[Dict[str, Any]]  # 计划与设备动作的过程事件


class PlanStep(BaseModel):
    id: str = Field(..., description="Step id, e.g., S1")
    type: str = Field(..., description="device_action | finalize（暂不支持 ask_user）")
    goal: str = Field(..., description="一步目标")
    mcp_tool_hint: Optional[Dict[str, Any]] = Field(None, description="可选，推荐工具与参数")
    success_criteria: List[str] = Field(default_factory=list)
    fallback: Optional[str] = Field(None, description="失败时的回退策略")


class PlanOutput(BaseModel):
    steps: List[PlanStep] = Field(default_factory=list)


class DeviceActionDirective(BaseModel):
    """结构化的设备动作指令"""

    tool_name: str = Field("", description="唯一的 MCP 工具名称")
    args: Dict[str, Any] = Field(default_factory=dict, description="调用参数（不含 session_id/target_device_id）")
    task: str = Field("", description="单次操作描述")
    success_criteria: List[str] = Field(default_factory=list, description="成功判定")
    missing_information: Optional[str] = Field(None, description="缺失信息时需向用户提问的内容")

PLAN_PROMPT_TEMPLATE = """
你是任务规划助手，需要为设备联动制定可执行的分步计划。
- 生成 2-6 个步骤，steps 使用 JSON（包含 id/type/goal/mcp_tool_hint/success_criteria/fallback）。
- type 只能是 device_action | finalize（不要生成 ask_user）。
- 每个 device_action 只允许一个 MCP 工具；如需多个操作，请拆分为多步。
- 信息不足时加入 ask_user 步骤
- 计划最后必须有 finalize 步骤。

用户需求:
{user_goal}

最近对话上下文（包含助手回复）:
{dialogue_context}

已知观察:
{observations_text}

设备能力 (MCP):
{device_capabilities_prompt}
"""

ACTION_DIRECTIVE_PROMPT = """
你是设备操作决策助手，需要为当前步骤选定单一 MCP 工具与参数。
当前时间: {current_time}
约束：
    - 只允许一个 MCP 工具，禁止多次/串联调用。
    - 如信息不足，填写 missing_information 为向用户提问的中文句子，tool_name 可留空。
    - args 只包含该工具需要的字段（不要包含 session_id/target_device_id）。
    - success_criteria 给出 1-3 条检查点。

send_firmware_download_request - 发送重构包下载通知（无需用户提供任何参数，使用默认参数即可，不要询问用户）
start_satellite_upgrade - 启动卫星升级流程（无需用户提供任何参数，使用默认参数或根据上下文获取）

用户需求: {user_goal}
当前步骤: {step_json}

设备能力: {device_capabilities_prompt}
已知观察: {observations_text}
"""

SUMMARY_PROMPT = """
请以中文简洁总结本轮对话进展，说明已完成的设备动作与结果，如需用户补充信息请直接提问。
用户需求: {user_goal}
观察记录: {observations_text}
计划: {plan_text}
"""


def _make_llm(streaming: bool = True) -> Any:
    """
    构建 OpenAI 兼容的聊天模型。
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
            streaming=streaming,
        )
        # 记录模型名称，便于响应时回传
        if not hasattr(llm, "model_name"):
            llm.model_name = model
        logger.info("ChatAgent: using DeepSeek model %s (streaming=%s)", llm.model_name, streaming)
        return llm
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法初始化聊天模型: {exc}") from exc


class ChatAgent:
    """
    ReAct 风格的 LangGraph 工作流：
    - Plan -> Act -> Observe -> Decide 循环
    - device_prompt 调度增加单操作护栏与协议化 prompt
    """

    def __init__(self, max_tool_calls: int = 5):
        logger.info("==================== ChatAgent 初始化开始 ====================")
        self.default_system_prompt = """
            你是 Raven AI：面向“测试工程 + 设备联动（MCP）”的对话式智能体。你的核心目标是：把用户的意图拆解为可执行步骤，并在需要时通过工具 device_prompt 驱动目标设备的上位机 AI 助手调用设备 MCP Server 的具体工具完成操作。

            # 你必须遵守的总原则
            1) 可靠性优先：绝不臆造设备 MCP 工具名、参数名、参数类型、约束条件。若[设备能力提示]中没有明确给出，先澄清或先让设备侧返回可用信息。
            2) ReAct 多步：允许多轮“计划->执行->观察->调整”，每一步都基于上一步返回结果决定下一步。
            3) device_prompt 单一操作：每次调用 device_prompt 时，只让设备侧执行“一个明确的操作任务”（一次工具调用或一次查询）。禁止在一次 device_prompt 里要求设备侧串联多个工具或做复杂流程。
            4) 对用户输出要“简洁可执行”：用要点列出结论/下一步，必要时给出明确参数、命令或操作指引。

            # 设备联动（MCP）工作流规范（强制）
            当 state 中提供了 target_device_id / [设备能力提示]：
            - 你需要先在脑中形成一个“最小可行计划”，然后开始执行。
            - 只要需要设备动作，就调用 device_prompt；每次 device_prompt 只包含一个动作。
            - 每次 device_prompt 的内容必须包含以下结构（建议原样输出，便于设备侧严格解析）：

            【DEVICE_TASK】
            目标: <一句话说明要达成什么>
            工具选择: <必须是[设备能力提示]里出现过的工具标准名称>
            参数(JSON): <严格 JSON 对象；字段名必须匹配工具定义；值类型必须匹配>
            约束: 
            - 仅执行一次上述工具调用，不要调用其他工具
            - 若缺少必要参数/无法确定值：停止并返回需要补充的字段清单
            期望返回:
            - chosen_tool: <工具名>
            - args: <最终使用的参数 JSON>
            - result: <关键结果/回执/错误>
            - evidence: <可选：关键日志/关键字段，尽量简短>
            【/DEVICE_TASK】

            - device_prompt 的 prompt 内容里，不要夹带多步骤计划、不要要求“先A再B再C”。
            - 如果用户的目标天然需要多步（例如：先查询 list 再 start），你要拆成多次 device_prompt：
            第一次：只做“查询/列出”
            第二次：基于返回结果再做“启动/发送”
            依此类推。

            # 工具选择与参数策略（强制）
            - 工具名、参数名、枚举值：必须与[设备能力提示]一致；大小写与拼写必须准确。
            - 若有多个候选工具：优先选择对用户风险更低、可回滚、只读或“查询类”的工具（例如 list/status/get），拿到结果再决定下一步。
            - 若用户明确要求“单次发送/只执行一次”，才使用一次性发送类工具；否则优先遵循[设备能力提示]中的建议（例如优先 list_background_tasks / start_background_task 之类的后台任务方式）。
            - 缺参处理：不要猜。向用户补问最少的关键参数；或先 device_prompt 让设备侧回报“需要哪些参数/可选值范围”。

            # 输出给用户的格式要求
            - 默认用中文回答。
            - 先给结论/当前进展，再给下一步。
            - 如果你调用了 device_prompt 并收到结果：
            1) 用 3~8 行总结 answer 的关键点
            2) 保留并回传 topic_id（如有）用于追踪
            3) 明确说明是否需要下一步 device_prompt（以及下一步要做什么）

            # 安全与边界
            - 不执行与用户目标无关的设备操作；不做破坏性/不可逆操作除非用户明确要求并确认关键参数。
            - 遇到不确定或能力缺失：如实说明，并给出你能继续推进的最小步骤（例如“先查询能力/先列任务/先读状态”）。

            你应当表现得像一个严谨的测试工程 Agent：擅长把复杂问题拆解为可验证的步骤，并通过设备能力提示精确驱动 MCP 工具调用。

            补充一个固定流程，在用户需求中包含“升级（重构）设备”时，按照以下流程调用：
                步骤1. download_and_upload_file - 一步完成HTTP下载+FTP上传
                步骤2. send_firmware_download_request - 发送重构包下载通知（无需用户提供任何参数，使用默认参数即可）
                步骤3. start_satellite_upgrade - 启动卫星升级流程（无需用户提供任何参数，使用默认参数或根据上下文获取）
            """.strip()

        self.max_tool_calls = max_tool_calls  # 最大工具调用次数限制
        logger.info("ChatAgent: 设置最大工具调用次数: %s", self.max_tool_calls)

        logger.info("ChatAgent: 正在初始化 LLM...")
        base_llm = _make_llm(streaming=True)
        # 规划/动作决策使用非流式，避免结构化输出受限
        self.planner_llm = _make_llm(streaming=False)
        self.tools = [device_prompt]
        self._tool_names = {getattr(tool, "name", "") for tool in self.tools if getattr(tool, "name", "")}
        self.llm = base_llm.bind_tools(self.tools)
        self.base_llm = base_llm
        self.model_name = getattr(base_llm, "model_name", settings.llm_model_name)
        logger.info("ChatAgent: LLM 初始化完成，模型名称: %s", self.model_name)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        logger.info("ChatAgent: Prompt 模板构建完成")

        logger.info("ChatAgent: 正在构建 LangGraph 工作流...")
        self.tool_node = ToolNode(self.tools)
        self.graph = self._build_graph()
        logger.info("==================== ChatAgent 初始化完成 ====================")

    def _build_graph(self):
        logger.info("ChatAgent: 开始构建 StateGraph...")
        workflow = StateGraph(ChatState)
        workflow.add_node("build_plan", self._build_plan_node)
        workflow.add_node("act", self._act_node)
        workflow.add_node("call_tools", self._call_tools)
        workflow.add_node("post_observe", self._post_observe)
        workflow.add_node("should_continue", self._should_continue_node)

        workflow.set_entry_point("build_plan")
        workflow.add_edge("build_plan", "act")
        workflow.add_conditional_edges(
            "act",
            self._route_from_act,
            {
                "call_tools": "call_tools",
                "continue": "should_continue",
            },
        )
        workflow.add_edge("call_tools", "post_observe")
        workflow.add_edge("post_observe", "should_continue")
        workflow.add_conditional_edges(
            "should_continue",
            self._continue_router,
            {
                "plan": "build_plan",
                "act": "act",
                END: END,
            },
        )

        recursion_limit = self.max_tool_calls * 4 + 6
        compiled = workflow.compile()
        logger.info("ChatAgent: StateGraph 构建完成，recursion_limit=%s", recursion_limit)
        return compiled

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
            "如需让该设备回答，请调用工具 device_prompt，将设备指令写入 prompt，"
            f"并携带 session_id={session_hint} 与 target_device_id。"
            "收到工具结果后，用中文向用户总结 answer，并保留 topic_id 供追踪。"
        )
        if device_capabilities_prompt:
            prompt = f"{prompt}\n\n[设备能力提示]\n{device_capabilities_prompt}"
        return prompt

    def _extract_user_goal(self, messages: Sequence[BaseMessage]) -> str:
        """取最近的人类消息作为用户需求。"""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return str(msg.content)
        # 回退为最后一条消息内容
        return str(messages[-1].content) if messages else ""

    def _observations_text(self, observations: Sequence[Any]) -> str:
        if not observations:
            return "暂无"
        parts: List[str] = []
        for idx, obs in enumerate(observations, start=1):
            if isinstance(obs, dict):
                ans = obs.get("answer") or obs.get("raw") or obs
                parts.append(f"[{idx}] {ans}")
            else:
                parts.append(f"[{idx}] {obs}")
        return "\n".join(parts)

    def _append_progress_event(self, state: ChatState, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """追加计划/设备动作的过程事件，保持有序列表。"""
        events = list(state.get("progress_events", []))
        events.append(event)
        return events

    async def _emit_progress_events(
        self,
        state: ChatState,
        last_index: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> int:
        """将新增的过程事件发送给回调，返回最新的事件计数。"""
        events = state.get("progress_events") or []
        if not progress_callback:
            return len(events)

        new_events = events[last_index:]
        for event in new_events:
            try:
                result = progress_callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                logger.warning("progress_callback 执行失败: %s", exc, exc_info=True)
        return len(events)

    def _recent_dialogue_context(
        self,
        messages: Sequence[BaseMessage],
        limit: int = 6,
        max_chars: int = 1600,
    ) -> str:
        """取最近若干轮对话（含助手回复）作为上下文。"""
        if not messages:
            return "暂无"

        relevant: List[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, (HumanMessage, AIMessage)):
                relevant.append(msg)

        if not relevant:
            return "暂无"

        recent = relevant[-limit:]
        lines: List[str] = []
        for msg in recent:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            content = str(msg.content).strip()
            lines.append(f"{role}: {content}")

        context = "\n".join(lines)
        if len(context) > max_chars:
            front_chars = 200
            back_chars = 200
            front_part = context[:front_chars]
            back_part = context[-back_chars:]
            context = f"{front_part}\n...(已截断，保留前 {front_chars} 字和后 {back_chars} 字)...\n{back_part}"
        return context

    async def _generate_plan(self, state: ChatState) -> List[PlanStep]:
        user_goal = self._extract_user_goal(state.get("messages", []))
        observations_text = self._observations_text(state.get("observations", []))
        device_capabilities_prompt = state.get("device_capabilities_prompt") or "无"
        dialogue_context = self._recent_dialogue_context(state.get("messages", []))
        prompt_text = PLAN_PROMPT_TEMPLATE.format(
            user_goal=user_goal,
            observations_text=observations_text,
            device_capabilities_prompt=device_capabilities_prompt,
            dialogue_context=dialogue_context,
        )
        logger.info(
            "\n\n--- PLAN PROMPT ---\n%s\n--- END PLAN PROMPT ---\n",
            prompt_text,
        )
        structured_llm = self.planner_llm.with_structured_output(PlanOutput)
        try:
            plan_output: PlanOutput = await structured_llm.ainvoke(prompt_text)
            steps = plan_output.steps or []
            logger.info("计划生成完成，步数=%s", len(steps))
            for step in steps:
                logger.info("Plan step: %s | %s", step.id, step.goal)
            return steps
        except Exception as exc:  # noqa: BLE001
            logger.warning("生成计划失败，使用回退方案: %s", exc, exc_info=True)
            fallback = PlanStep(id="S1", type="finalize", goal="向用户总结进展")
            return [fallback]

    async def _build_plan_node(self, state: ChatState) -> ChatState:
        steps = await self._generate_plan(state)
        filtered_steps = [step for step in steps if str(getattr(step, "type", "")).lower() != "ask_user"]
        if len(filtered_steps) != len(steps):
            logger.info("计划中过滤掉 ask_user 步骤: %s -> %s", len(steps), len(filtered_steps))
        if not filtered_steps:
            filtered_steps = [PlanStep(id="S1", type="finalize", goal="向用户总结进展")]

        plan_dicts = [step.model_dump() for step in filtered_steps]
        progress_events = self._append_progress_event(
            state,
            {
                "type": "plan",
                "plan": plan_dicts,
                "plan_version": sum(1 for evt in state.get("progress_events", []) if evt.get("type") == "plan") + 1,
            },
        )
        return {
            **state,
            "plan": plan_dicts,
            "step_index": 0,
            "replan": False,
            "needs_user_input": False,
            "progress_events": progress_events,
        }

    def _route_from_act(self, state: ChatState) -> str:
        """根据 act 输出决定是否进入工具调用。"""
        tool_call_count = state.get("tool_call_count", 0)
        if tool_call_count >= self.max_tool_calls:
            logger.warning("已达到最大工具调用次数(%s)，停止调用工具", tool_call_count)
            return "continue"

        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
            return "call_tools"
        return "continue"

    def _continue_router(self, state: ChatState) -> str:
        if state.get("needs_user_input"):
            return END
        if state.get("tool_call_count", 0) >= self.max_tool_calls:
            return END
        plan = state.get("plan") or []
        if state.get("step_index", 0) >= len(plan):
            return END
        if state.get("replan"):
            return "plan"
        return "act"

    async def _run_graph_with_progress(
        self,
        state: ChatState,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> ChatState:
        """手动驱动 LangGraph 节点，便于实时发出进度事件。"""
        recursion_limit = self.max_tool_calls * 4 + 6
        last_progress_index = len(state.get("progress_events", []))
        node = "build_plan"
        steps = 0

        while steps < recursion_limit:
            steps += 1
            if node == "build_plan":
                state = await self._build_plan_node(state)
                last_progress_index = await self._emit_progress_events(state, last_progress_index, progress_callback)
                node = "act"
                continue

            if node == "act":
                state = await self._act_node(state)
                route = self._route_from_act(state)
                node = "call_tools" if route == "call_tools" else "should_continue"
                continue

            if node == "call_tools":
                state = await self._call_tools(state)
                node = "post_observe"
                continue

            if node == "post_observe":
                state = await self._post_observe(state)
                last_progress_index = await self._emit_progress_events(state, last_progress_index, progress_callback)
                node = "should_continue"
                continue

            if node == "should_continue":
                state = await self._should_continue_node(state)
                route = self._continue_router(state)
                if route == END:
                    break
                node = "build_plan" if route == "plan" else "act"
                continue

            logger.warning("run_with_progress: 未知节点 %s，提前结束", node)
            break

        if steps >= recursion_limit:
            logger.warning("run_with_progress: 达到 recursion_limit=%s，提前结束", recursion_limit)
        return state

    async def _act_node(self, state: ChatState) -> ChatState:
        plan = state.get("plan") or []
        idx = state.get("step_index", 0)
        messages = list(state.get("messages", []))
        observations = state.get("observations", [])
        user_goal = self._extract_user_goal(messages)

        if state.get("needs_user_input"):
            logger.info("act: 正在等待用户补充信息，结束本轮")
            return state

        if idx >= len(plan):
            summary = await self._summarize_for_user(state, user_goal)
            messages.append(AIMessage(content=summary))
            return {**state, "messages": messages, "step_index": idx}

        step = plan[idx]
        step_type = step.get("type")
        logger.info("act: 当前步骤 #%s 类型=%s 目标=%s", idx + 1, step_type, step.get("goal"))

        if step_type == "ask_user":
            logger.info("act: ask_user 步骤已禁用，跳过执行")
            return {**state, "step_index": idx + 1}

        if step_type == "finalize":
            summary = await self._summarize_for_user(state, user_goal)
            messages.append(AIMessage(content=summary))
            return {**state, "messages": messages, "step_index": idx + 1}

        if step_type != "device_action":
            # 未知类型，直接请求用户确认
            fallback_msg = f"当前步骤无法解析（{step_type}），请确认要执行的动作。"
            messages.append(AIMessage(content=fallback_msg))
            return {
                **state,
                "messages": messages,
                "step_index": idx + 1,
                "needs_user_input": True,
            }

        directive = await self._decide_device_action(step, state, user_goal, observations)
        if directive.missing_information:
            messages.append(AIMessage(content=directive.missing_information))
            return {
                **state,
                "messages": messages,
                "step_index": idx + 1,
                "needs_user_input": True,
            }

        dialogue_context = self._recent_dialogue_context(messages)
        dispatch_prompt = self._build_device_dispatch_prompt(
            user_goal=user_goal,
            step=step,
            directive=directive,
            state_context=state,
            device_capabilities_prompt=state.get("device_capabilities_prompt"),
            dialogue_context=dialogue_context,
        )
        dispatch_prompt = self._ensure_single_action_prompt(dispatch_prompt)

        tool_call = {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "name": "device_prompt",
            "args": {
                "prompt": dispatch_prompt,
                "session_id": state.get("session_id"),
                "target_device_id": state.get("target_device_id"),
                "system_prompt": state.get("system_prompt") or self.default_system_prompt,
            },
        }
        ai_message = AIMessage(
            content="正在为设备生成单次操作指令。",
            tool_calls=[tool_call],
        )
        messages.append(ai_message)
        logger.info(
            "act: 生成 device_prompt 调用，工具=%s，参数 keys=%s",
            directive.tool_name,
            list(directive.args.keys()),
        )
        logger.info(
            "act: 下发到设备的 prompt 预览: %s",
            dispatch_prompt[:800] + ("..." if len(dispatch_prompt) > 800 else ""),
        )
        return {**state, "messages": messages}

    async def _call_tools(self, state: ChatState) -> ChatState:
        """执行工具调用，将工具结果写回消息列表。"""
        logger.info("========== _call_tools 开始执行 ==========")

        tool_call_count = state.get("tool_call_count", 0) + 1
        logger.info("_call_tools: 当前工具调用次数: %s/%s", tool_call_count, self.max_tool_calls)

        messages = state.get("messages", [])
        last_message = messages[-1] if messages else None
        if isinstance(last_message, AIMessage) and hasattr(last_message, "tool_calls"):
            tool_calls = getattr(last_message, "tool_calls", [])
            logger.info("_call_tools: 检测到 %s 个工具调用", len(tool_calls))
            for idx, tool_call in enumerate(tool_calls):
                tool_name = getattr(tool_call, "name", "unknown") if hasattr(tool_call, "name") else tool_call.get("name", "unknown")
                tool_args = getattr(tool_call, "args", {}) if hasattr(tool_call, "args") else tool_call.get("args", {})
                logger.info("_call_tools: 工具 #%s: %s, 参数 keys: %s", idx + 1, tool_name, list(tool_args.keys()))
            self._normalize_tool_calls(last_message, state)

        set_device_prompt_context(
            state.get("session_id"),
            state.get("target_device_id"),
            state.get("system_prompt") or self.default_system_prompt,
        )
        tool_config = self._build_tool_node_config()
        try:
            tool_updates = await self.tool_node.ainvoke(state, config=tool_config)
        finally:
            clear_device_prompt_context()

        updated_messages = list(state.get("messages", []))
        if isinstance(tool_updates, Dict) and tool_updates.get("messages"):
            new_messages = tool_updates["messages"]
            updated_messages.extend(new_messages)
            for msg in new_messages:
                if hasattr(msg, "content"):
                    content_preview = str(msg.content)[:400] if msg.content else "(empty)"
                    logger.info("_call_tools: 工具返回内容预览: %s", content_preview)

        logger.info("_call_tools: 工具执行完成，新增消息数: %s", len(updated_messages) - len(state.get("messages", [])))
        logger.info("========== _call_tools 执行完成 ==========")
        return {
            **state,
            "messages": updated_messages,
            "tool_call_count": tool_call_count,
        }

    def _build_tool_node_config(self) -> Dict[str, Any]:
        """
        构造 ToolNode 调用所需的 config，兼容新版 LangGraph 需要 runtime 的情况。
        - 优先复用当前 runnable 上下文（如果存在）
        - 不在 LangGraph runtime 内时，提供一个默认的 Runtime，避免缺失 __pregel_runtime 报错
        """
        try:
            from langgraph.config import get_config

            cfg = get_config()
            return cfg
        except Exception:
            pass

        try:
            from langgraph.runtime import DEFAULT_RUNTIME
        except Exception:
            return {}

        try:
            from langgraph._internal._constants import CONF, CONFIG_KEY_RUNTIME
        except Exception:
            CONF, CONFIG_KEY_RUNTIME = "configurable", "__pregel_runtime"

        return {CONF: {CONFIG_KEY_RUNTIME: DEFAULT_RUNTIME}}

    async def _post_observe(self, state: ChatState) -> ChatState:
        """解析工具返回，写入 observations，推进 step_index。"""
        messages = state.get("messages", [])
        observations = list(state.get("observations", []))
        last_tool_msg = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        parsed = self._parse_tool_message(last_tool_msg) if last_tool_msg else None

        replan = state.get("replan", False)
        needs_user_input = state.get("needs_user_input", False)
        last_device_answer = state.get("last_device_answer")
        last_device_topic_id = state.get("last_device_topic_id")
        progress_events = list(state.get("progress_events", []))
        plan = state.get("plan") or []
        current_step_index = state.get("step_index", 0)
        current_step = plan[current_step_index] if current_step_index < len(plan) else None

        if parsed:
            observations.append(parsed)
            last_device_answer = parsed.get("answer") or last_device_answer
            last_device_topic_id = parsed.get("topic_id") or last_device_topic_id
            logger.info("post_observe: 解析工具返回 answer=%s topic_id=%s", last_device_answer, last_device_topic_id)
            if self._needs_more_info(parsed):
                replan = True
                needs_user_input = True
                ask_text = parsed.get("missing_information")
                if not ask_text:
                    answer_preview = str(parsed.get("answer") or parsed.get("raw") or "").strip()
                    if len(answer_preview) > 300:
                        answer_preview = answer_preview[:280] + "..."
                    ask_text = f"设备返回信息不足，需要你补充参数后再继续。设备答复：{answer_preview}" if answer_preview else "设备返回信息不足，需要你补充参数后再继续。"
                messages.append(AIMessage(content=ask_text))
            progress_events.append(
                {
                    "type": "device_action",
                    "step_id": current_step.get("id") if isinstance(current_step, dict) else None,
                    "step_goal": current_step.get("goal") if isinstance(current_step, dict) else None,
                    "step_index": current_step_index,
                    "answer": parsed.get("answer") or parsed.get("raw"),
                    "topic_id": parsed.get("topic_id"),
                    "raw": parsed.get("raw"),
                }
            )

        return {
            **state,
            "observations": observations,
            "step_index": state.get("step_index", 0) + 1,
            "replan": replan,
            "needs_user_input": needs_user_input,
            "last_device_answer": last_device_answer,
            "last_device_topic_id": last_device_topic_id,
            "progress_events": progress_events,
            "messages": messages,
        }

    async def _should_continue_node(self, state: ChatState) -> ChatState:
        """中转节点，用于在 router 中读取最新状态。"""
        return state

    def _normalize_tool_call_name(self, raw_name: Optional[str]) -> Optional[str]:
        """Normalize tool name from LLM to the known tool set (fixes duplicated names)."""
        if not raw_name:
            return None
        name = str(raw_name).strip()
        if name in self._tool_names:
            return name

        lower_map = {n.lower(): n for n in self._tool_names}
        if name.lower() in lower_map:
            return lower_map[name.lower()]

        # Handle repeated concatenated names like "device_promptdevice_prompt"
        for canonical in self._tool_names:
            if name.replace(canonical, "") == "" or name.lower().replace(canonical.lower(), "") == "":
                return canonical
        return None

    def _normalize_tool_calls(self, ai_message: AIMessage, state: ChatState) -> None:
        """Ensure tool calls use valid names and only one call before executing ToolNode."""
        tool_calls = getattr(ai_message, "tool_calls", None)
        if not tool_calls:
            return

        if len(tool_calls) > 1:
            logger.warning("检测到 %s 个工具调用，已截断为第一个以满足单操作约束", len(tool_calls))
            tool_calls = [tool_calls[0]]

        normalized_calls = []
        changed = False
        for tool_call in tool_calls:
            raw_name = getattr(tool_call, "name", None) if hasattr(tool_call, "name") else tool_call.get("name")
            normalized_name = self._normalize_tool_call_name(raw_name)
            if normalized_name and normalized_name != raw_name:
                logger.warning("_call_tools: 检测到异常工具名 %s，已规范为 %s", raw_name, normalized_name)
                if hasattr(tool_call, "name"):
                    setattr(tool_call, "name", normalized_name)
                elif isinstance(tool_call, dict):
                    tool_call["name"] = normalized_name
                changed = True

            args = getattr(tool_call, "args", {}) if hasattr(tool_call, "args") else tool_call.get("args", {})
            if isinstance(args, dict):
                if not args.get("session_id"):
                    args["session_id"] = state.get("session_id")
                    changed = True
                if not args.get("target_device_id"):
                    args["target_device_id"] = state.get("target_device_id")
                    changed = True
            if hasattr(tool_call, "args"):
                setattr(tool_call, "args", args)
            elif isinstance(tool_call, dict):
                tool_call["args"] = args
            normalized_calls.append(tool_call)

        if changed:
            ai_message.tool_calls = normalized_calls

    async def _decide_device_action(
        self,
        step: Dict[str, Any],
        state: ChatState,
        user_goal: str,
        observations: Sequence[Any],
    ) -> DeviceActionDirective:
        device_capabilities_prompt = state.get("device_capabilities_prompt") or "无"
        observations_text = self._observations_text(observations)
        dialogue_context = self._recent_dialogue_context(state.get("messages", []))
        current_time = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S")
        prompt_text = ACTION_DIRECTIVE_PROMPT.format(
            user_goal=user_goal,
            step_json=json.dumps(step, ensure_ascii=False),
            device_capabilities_prompt=device_capabilities_prompt,
            observations_text=observations_text,
            dialogue_context=dialogue_context,
            current_time=current_time,
        )
        logger.info(
            "\n\n--- DEVICE ACTION PROMPT ---\n%s\n--- END DEVICE ACTION PROMPT ---\n",
            prompt_text,
        )
        structured_llm = self.planner_llm.with_structured_output(DeviceActionDirective)
        try:
            directive: DeviceActionDirective = await structured_llm.ainvoke(prompt_text)
            if not directive.tool_name and not directive.missing_information:
                directive.missing_information = "缺少可用的 MCP 工具或参数，请提供更多上下文。"
            return directive
        except Exception as exc:  # noqa: BLE001
            logger.warning("生成设备动作指令失败，使用回退: %s", exc, exc_info=True)
            hint = step.get("mcp_tool_hint", {}) if isinstance(step.get("mcp_tool_hint"), dict) else {}
            return DeviceActionDirective(
                tool_name=hint.get("tool") or hint.get("name", ""),
                args=hint.get("arguments") or hint.get("args", {}) if isinstance(hint, dict) else {},
                task=step.get("goal") or "执行单次设备操作",
                success_criteria=step.get("success_criteria", []),
                missing_information=None,
            )

    def _build_device_dispatch_prompt(
        self,
        user_goal: str,
        step: Dict[str, Any],
        directive: DeviceActionDirective,
        state_context: ChatState,
        device_capabilities_prompt: Optional[str],
        dialogue_context: Optional[str] = None,
    ) -> str:
        """为上位机端 AI 助手构建协议化 prompt。"""
        tool_hint = step.get("mcp_tool_hint", {}) if isinstance(step.get("mcp_tool_hint"), dict) else {}
        tool_name = directive.tool_name or tool_hint.get("tool") or tool_hint.get("name", "") or "需确认工具名称"
        args_json = json.dumps(directive.args or tool_hint.get("arguments") or {}, ensure_ascii=False, indent=2)
        success_criteria = directive.success_criteria or step.get("success_criteria") or ["返回执行结果或确认信息"]
        success_block = "\n".join(f"- {c}" for c in success_criteria)
        task = directive.task or step.get("goal") or user_goal
        device_label = state_context.get("target_device_name") or state_context.get("target_device_id") or "未知设备"
        session_label = state_context.get("session_id") or "未知会话"
        context_notes = f"设备: {device_label}; 会话: {session_label}"
        if dialogue_context:
            context_notes = f"{context_notes}; 对话摘要: {dialogue_context.strip()}"

        device_task_block = [
            "【DEVICE_TASK】",
            f"目标: {task}",
            f"工具选择: {tool_name}",
            f"参数(JSON): {args_json}",
            "约束:",
            "- 仅执行一次上述工具调用，不要调用其他工具。",
            "- 若缺少必要参数或无法确定值，请返回需要补充的字段清单，不要猜测。",
            "期望返回:",
            "- chosen_tool: <工具名>",
            "- args: <最终使用的参数 JSON>",
            "- result: <关键结果/回执/错误>",
            "- evidence: <可选：关键日志/关键字段，尽量简短>",
            "成功判定:",
            success_block,
            "【/DEVICE_TASK】",
            context_notes,
        ]

        if device_capabilities_prompt:
            device_task_block.append(f"设备能力提示: {device_capabilities_prompt.strip()}")

        return "\n".join(device_task_block)

    def _contains_multiple_actions(self, prompt: str) -> bool:
        explicit_multi = ["多个工具", "多次调用", "链式调用", "分别调用", "同时执行"]
        if any(token in prompt for token in explicit_multi):
            return True

        patterns = [
            r"先.+(再|然后|接着|随后)",
            r"之后.*再",
            r"再.*然后",
        ]
        return any(re.search(pattern, prompt) for pattern in patterns)

    def _rewrite_device_prompt_single_action(self, prompt: str) -> str:
        """去除多余内容，仅保留单个 DEVICE_TASK 块或首段提示。"""
        start = prompt.find("【DEVICE_TASK】")
        end = prompt.find("【/DEVICE_TASK】")
        if start != -1 and end != -1:
            return prompt[start : end + len("【/DEVICE_TASK】")]
        return prompt.split("\n\n")[0]

    def _ensure_single_action_prompt(self, prompt: str) -> str:
        if not self._contains_multiple_actions(prompt):
            return prompt
        logger.warning("检测到 device_prompt 中疑似多步操作，保留首个单任务块")
        rewritten = self._rewrite_device_prompt_single_action(prompt)
        return rewritten

    def _parse_tool_message(self, msg: ToolMessage) -> Dict[str, Any]:
        """解析 device_prompt 返回的 json 结构，兼容异常格式。"""
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            content = "".join(str(part) for part in content)
        parsed: Dict[str, Any] = {"raw": content}
        try:
            data = json.loads(content) if isinstance(content, str) else {}
            if isinstance(data, dict):
                parsed.update(data)
        except Exception:
            # 保留原始内容
            parsed["error"] = "无法解析 device_prompt 返回内容"
        return parsed

    def _needs_more_info(self, parsed: Dict[str, Any]) -> bool:
        """Heuristic: detect true missing-info signals while ignoring prompt echoes."""

        def strip_device_task_block(text: str) -> str:
            """Remove DEVICE_TASK template to avoid false positives from echoed prompts."""
            start = text.find("【DEVICE_TASK】")
            end = text.find("【/DEVICE_TASK】")
            if start != -1 and end != -1 and end > start:
                before = text[:start]
                after = text[end + len("【/DEVICE_TASK】") :]
                return (before + " " + after).strip()
            return text

        original_answer = str(parsed.get("answer") or parsed.get("raw") or "")
        answer = original_answer.lower()
        if not answer:
            return False

        # If only template content is returned, treat it as echo instead of missing-info.
        stripped = strip_device_task_block(original_answer).strip().lower()
        if "【device_task】" in answer and not stripped:
            return False

        # Positive confirmations take precedence to avoid false missing-info flags on successful runs.
        success_cues = ["已完成", "已成功", "执行成功", "上传成功", "下载成功"]
        if any(cue in answer for cue in success_cues):
            return False

        # Direct cues that explicitly signal missing information
        direct_cues = [
            "缺少",
            "缺失",
            "信息不足",
            "参数不足",
            "empty",
            "为空",
            "不能为空",
            "missing",
            "not found",
            "not provided",
            "need more",
        ]
        if any(cue in stripped or cue in answer for cue in direct_cues):
            return True

        # Softer requests such as "请提供/需提供/未提供"; avoid false hits like "根据您提供的"。
        provide_patterns = [r"(请|需|需要).{0,6}提供", r"未提供", r"提供以下.*(信息|参数)"]
        return any(re.search(pattern, stripped or answer) for pattern in provide_patterns)

    async def _summarize_for_user(self, state: ChatState, user_goal: str) -> str:
        """最终向用户汇报或在无工具情况下回应。"""
        observations_text = self._observations_text(state.get("observations", []))
        plan_text = json.dumps(state.get("plan", []), ensure_ascii=False)
        prompt_text = SUMMARY_PROMPT.format(
            user_goal=user_goal,
            observations_text=observations_text,
            plan_text=plan_text,
        )
        try:
            res = await self.base_llm.ainvoke(prompt_text)
            return res.content if hasattr(res, "content") else str(res)
        except Exception as exc:  # noqa: BLE001
            logger.warning("总结生成失败，使用回退: %s", exc, exc_info=True)
            if state.get("last_device_answer"):
                return f"设备反馈: {state['last_device_answer']}"
            return "本轮未执行设备操作，请告知下一步需求。"

    async def _direct_llm(self, state: ChatState) -> ChatState:
        """无设备场景的直接对话回退。"""
        base_prompt = state.get("system_prompt") or self.default_system_prompt
        prompt_messages = self.prompt.format_messages(
            system_prompt=self._build_system_prompt(
                base_prompt,
                target_device_id=None,
                target_device_name=None,
                session_id=state.get("session_id"),
            ),
            messages=state.get("messages", []),
        )
        ai_message: AIMessage = await self.base_llm.ainvoke(prompt_messages)
        updated_messages = list(state.get("messages", [])) + [ai_message]
        return {
            **state,
            "messages": updated_messages,
        }

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
        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
            "session_id": session_id,
            "target_device_id": target_device_id,
            "target_device_name": target_device_name,
            "device_capabilities_prompt": device_capabilities_prompt,
            "tool_call_count": 0,
            "plan": [],
            "step_index": 0,
            "observations": [],
            "needs_user_input": False,
            "replan": False,
            "progress_events": [],
        }
        if not target_device_id:
            return asyncio.get_event_loop().run_until_complete(self._direct_llm(state))
        config = {"recursion_limit": self.max_tool_calls * 4 + 6}
        return self.graph.invoke(state, config=config)

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
        logger.info("ainvoke: 接收到 %s 条消息", len(messages))
        logger.info("ainvoke: 系统提示词: %s", "自定义" if system_prompt else "默认")

        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
            "session_id": session_id,
            "target_device_id": target_device_id,
            "target_device_name": target_device_name,
            "device_capabilities_prompt": device_capabilities_prompt,
            "tool_call_count": 0,
            "plan": [],
            "step_index": 0,
            "observations": [],
            "needs_user_input": False,
            "replan": False,
            "progress_events": [],
        }

        if not target_device_id:
            logger.info("ainvoke: 未指定设备，走直连对话回退")
            return await self._direct_llm(state)

        set_device_prompt_context(
            session_id,
            target_device_id,
            system_prompt or self.default_system_prompt,
        )
        try:
            config = {"recursion_limit": self.max_tool_calls * 4 + 6}
            result = await self.graph.ainvoke(state, config=config)
            logger.info("ainvoke: graph.ainvoke 调用成功，返回消息数: %s", len(result.get("messages", [])))
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("ainvoke: graph.ainvoke 调用失败: %s", exc, exc_info=True)
            raise
        finally:
            clear_device_prompt_context()

    async def ainvoke_with_progress(
        self,
        messages: List[BaseMessage],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        target_device_id: Optional[str] = None,
        target_device_name: Optional[str] = None,
        device_capabilities_prompt: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> ChatState:
        """异步调用，实时回调计划/动作进度事件。"""
        logger.info("==================== ainvoke_with_progress 开始 ====================")
        logger.info("ainvoke_with_progress: 接收到 %s 条消息", len(messages))

        state: ChatState = {
            "messages": messages,
            "system_prompt": system_prompt or self.default_system_prompt,
            "session_id": session_id,
            "target_device_id": target_device_id,
            "target_device_name": target_device_name,
            "device_capabilities_prompt": device_capabilities_prompt,
            "tool_call_count": 0,
            "plan": [],
            "step_index": 0,
            "observations": [],
            "needs_user_input": False,
            "replan": False,
            "progress_events": [],
        }

        if not target_device_id:
            logger.info("ainvoke_with_progress: 未指定设备，走直连对话回退")
            return await self._direct_llm(state)

        set_device_prompt_context(
            session_id,
            target_device_id,
            system_prompt or self.default_system_prompt,
        )
        try:
            result = await self._run_graph_with_progress(state, progress_callback)
            logger.info(
                "ainvoke_with_progress: 执行完成，返回消息数: %s, progress_events=%s",
                len(result.get("messages", [])),
                len(result.get("progress_events") or []),
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("ainvoke_with_progress: 调用失败: %s", exc, exc_info=True)
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

        prompt_messages = self.prompt.format_messages(
            system_prompt=self._build_system_prompt(system_prompt, None, None, session_id),
            messages=messages,
        )
        logger.info("astream: 准备流式输出，消息数: %s", len(prompt_messages))

        async for chunk in self.base_llm.astream(prompt_messages):
            text = self._chunk_to_text(chunk)
            if not text:
                continue
            yield text

        logger.info("==================== astream 流式调用完成 ====================")
