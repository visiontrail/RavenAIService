"""四维多智能体日志+代码联合分析图。"""

from __future__ import annotations

import json
import logging
import operator
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Annotated, Dict, List, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool

try:
    from langgraph.graph import END, StateGraph  # type: ignore
except Exception:  # pragma: no cover - 运行环境缺失时由上层降级
    StateGraph = None  # type: ignore
    END = None  # type: ignore

from app.agents.log_agent import get_llm
from app.tools.grep_tool import grep_file_xml

logger = logging.getLogger(__name__)


class InvestigationState(TypedDict):
    # --- 基础上下文 ---
    query: str
    workspace_dir: str
    log_file_path: str

    # --- 对话与上下文管理 ---
    messages: Annotated[List[BaseMessage], operator.add]
    working_memory: str
    token_count: int
    iteration_count: int

    # --- 动态指令流转 ---
    pending_log_keywords: List[str]
    purified_logs: str

    # --- 结果产出 ---
    raw_root_cause: str
    final_report: str


def route_after_log(state: InvestigationState):
    if state["token_count"] > 8000:
        return "compaction_agent"
    return "code_agent"


def route_after_code(state: InvestigationState):
    if state["iteration_count"] >= 5:  # 熔断机制
        return "summary_agent"

    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        tool_name = last_msg.tool_calls[0]["name"]
        if tool_name == "AskLogAgentTool":
            return "log_agent"
        elif tool_name == "SubmitDiagnosisTool":
            return "summary_agent"

    return "code_agent"  # 默认内部工具自循环


class CodeAnalysisGraph:
    """四维智能体编排：Code -> Log/Compaction -> Summary。"""

    def __init__(self, token_limit: int = 8000, max_iterations: int = 5):
        if StateGraph is None or END is None:
            raise RuntimeError("langgraph 不可用，无法初始化 CodeAnalysisGraph")

        self.token_limit = int(token_limit)
        self.max_iterations = int(max_iterations)
        self.llm = get_llm()
        self._tools = self._build_code_tools()

        try:
            self._llm_with_tools = self.llm.bind_tools(self._tools)
        except Exception as e:
            logger.warning("bind_tools 失败，Code Agent 将退化为无工具模式: %s", e)
            self._llm_with_tools = self.llm

        graph = StateGraph(InvestigationState)
        graph.add_node("code_agent", self._code_agent_node)
        graph.add_node("log_agent", self._log_agent_node)
        graph.add_node("compaction_agent", self._compaction_agent_node)
        graph.add_node("summary_agent", self._summary_agent_node)

        graph.set_entry_point("code_agent")
        graph.add_conditional_edges(
            "code_agent",
            route_after_code,
            {
                "code_agent": "code_agent",
                "log_agent": "log_agent",
                "summary_agent": "summary_agent",
            },
        )
        graph.add_conditional_edges(
            "log_agent",
            route_after_log,
            {
                "code_agent": "code_agent",
                "compaction_agent": "compaction_agent",
            },
        )
        graph.add_edge("compaction_agent", "code_agent")
        graph.add_edge("summary_agent", END)

        self._app = graph.compile()

    def run(self, query: str, workspace_dir: str, log_file_path: str) -> Dict[str, Any]:
        start_time = time.time()
        state: InvestigationState = {
            "query": query,
            "workspace_dir": workspace_dir,
            "log_file_path": log_file_path,
            "messages": [HumanMessage(content=query, id=self._new_id())],
            "working_memory": "",
            "token_count": 0,
            "iteration_count": 0,
            "pending_log_keywords": [],
            "purified_logs": "",
            "raw_root_cause": "",
            "final_report": "",
        }

        final_state = self._app.invoke(state, config={"recursion_limit": 60})
        return self._to_structured_result(final_state, execution_time=time.time() - start_time)

    def _build_code_tools(self) -> List[StructuredTool]:
        def ask_log_agent_tool(keywords: List[str]) -> str:
            """当你不确定代码何处报错时，提供关键词组合，让日志专家去生产日志中取证。"""
            return f"日志关键词已提交: {keywords}"

        def read_code_tool(file_path: str, start_line: int, end_line: int) -> str:
            """读取沙箱中指定文件的代码片段。每次最多读取 100 行。"""
            return f"已请求读取代码: {file_path}:{start_line}-{end_line}"

        def submit_diagnosis_tool(root_cause_analysis: str) -> str:
            """当你通过源码找到了确凿的缺陷后，调用此工具提交你的技术分析报告并结束排查。"""
            return f"已提交根因分析: {root_cause_analysis[:120]}"

        return [
            StructuredTool.from_function(
                func=ask_log_agent_tool,
                name="AskLogAgentTool",
                description="当你不确定代码何处报错时，提供关键词组合，让日志专家去生产日志中取证。",
            ),
            StructuredTool.from_function(
                func=read_code_tool,
                name="ReadCodeTool",
                description="读取沙箱中指定文件的代码片段。每次最多读取 100 行。",
            ),
            StructuredTool.from_function(
                func=submit_diagnosis_tool,
                name="SubmitDiagnosisTool",
                description="当你通过源码找到了确凿的缺陷后，调用此工具提交你的技术分析报告并结束排查。",
            ),
        ]

    def _code_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        sys_prompt = (
            "# 角色设定\n"
            "你是一位拥有 15 年经验的顶级架构师和线上故障排查专家（Senior Principal Engineer）。\n"
            "你的任务是根据用户的故障描述，在一个隔离的代码沙箱中定位代码级 Root Cause。\n\n"
            "# 当前上下文\n"
            f"- 用户的原始故障描述：{state.get('query', '')}\n"
            f"- 你的代码沙箱路径：{state.get('workspace_dir', '')}\n"
            f"- 历史排障备忘录（必读）：{state.get('working_memory', '') or '(空)'}\n"
            f"- 最新日志提纯结果：{state.get('purified_logs', '') or '(暂无)'}\n\n"
            "# 工作流与工具协议\n"
            "你必须严格按照以下逻辑推进排查，绝不能依靠猜测来下定论，必须“见码如见面”：\n\n"
            "1. 🔍 **信息收集与试探**：\n"
            "   - 如果你还没有报错的堆栈或确切的文件名，请基于你对业务的理解，构思一组最可能出现在日志里的特征词，并调用 `AskLogAgentTool` 让日志专家去海量日志中检索。\n\n"
            "2. 🔄 **反思与纠偏（Reflection）**：\n"
            "   - 如果日志专家返回“未找到结果”或“无关日志”，**绝不轻言放弃**。仔细阅读《历史排障备忘录》，思考是不是上一次的关键词太长、太具体或拼写错误？换一组更宽泛或不同维度的特征词，再次调用 `AskLogAgentTool`。\n\n"
            "3. 📖 **案发现场勘探**：\n"
            "   - 当日志专家带回了包含确切异常（如 Exception、Error）和具体行号（如 OrderService.java:128）的堆栈时，**立即停止搜索日志**。\n"
            "   - 调用 `ReadCodeTool` 前往工作区读取对应代码。\n\n"
            "4. 🧠 **深度推理**：\n"
            "   - 结合日志和源码，推理变量为何为空、条件为何没命中。如果需要看依赖函数实现，继续调用 `ReadCodeTool`。\n\n"
            "5. 🏁 **结案陈词**：\n"
            "   - 只有当你确信找到了导致该故障的具体代码缺陷时，调用 `SubmitDiagnosisTool` 提交你的硬核技术分析（包含缺陷文件、行号、原因和修复代码），结束排查。\n\n"
            "# 纪律约束（严禁违背）\n"
            "- **零幻觉原则**：绝对不要在没有调用 ReadCodeTool 读取代码前，就瞎猜代码的实现逻辑。\n"
            "- 每一步都必须先输出你的<thinking>（思考过程），然后再输出工具调用。"
        )

        prompt_messages: List[BaseMessage] = [
            SystemMessage(content=sys_prompt, id=self._new_id()),
            *state.get("messages", []),
        ]

        response = self._llm_with_tools.invoke(prompt_messages)
        response = self._normalize_ai_message(response)

        token_delta = self._estimate_tokens_for_message(response)
        updates: Dict[str, Any] = {
            "messages": [response],
            "iteration_count": int(state.get("iteration_count", 0)) + 1,
            "token_count": int(state.get("token_count", 0)) + token_delta,
        }

        tool_calls = self._extract_tool_calls(response)
        if not tool_calls:
            return updates

        first_call = tool_calls[0]
        tool_name = first_call.get("name")
        args = self._coerce_args(first_call.get("args"))

        if tool_name == "AskLogAgentTool":
            keywords = args.get("keywords")
            if isinstance(keywords, str):
                keywords = [k.strip() for k in re.split(r"[,，\s]+", keywords) if k.strip()]
            if not isinstance(keywords, list):
                keywords = []
            updates["pending_log_keywords"] = [str(k).strip() for k in keywords if str(k).strip()][:8]
            return updates

        if tool_name == "SubmitDiagnosisTool":
            analysis = str(args.get("root_cause_analysis", "")).strip()
            if analysis:
                updates["raw_root_cause"] = analysis
            return updates

        if tool_name == "ReadCodeTool":
            snippet = self._read_code_snippet(
                workspace_dir=state.get("workspace_dir", ""),
                file_path=str(args.get("file_path", "")),
                start_line=self._safe_int(args.get("start_line"), 1),
                end_line=self._safe_int(args.get("end_line"), 80),
            )
            tool_msg = ToolMessage(
                content=snippet,
                tool_call_id=str(first_call.get("id") or self._new_id()),
                name="ReadCodeTool",
                id=self._new_id(),
            )
            updates["messages"].append(tool_msg)
            updates["token_count"] = int(updates["token_count"]) + self._estimate_tokens(snippet)
            return updates

        return updates

    def _log_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        keywords = state.get("pending_log_keywords") or []
        log_file_path = state.get("log_file_path", "")

        raw_chunks: List[str] = []
        if not keywords:
            raw_chunks.append("[LogAgent] 未收到关键词，无法执行日志检索。")
        else:
            for kw in keywords[:8]:
                keyword = str(kw).strip()
                if not keyword:
                    continue
                try:
                    xml = grep_file_xml(log_file_path, keyword, context=2)
                    raw_chunks.append(f"<keyword>{keyword}</keyword>\n{xml[:5000]}")
                except Exception as e:
                    raw_chunks.append(f"<keyword>{keyword}</keyword>\n<error>{e}</error>")

        raw_log_output = "\n\n".join(raw_chunks).strip() or "[LogAgent] 无有效检索结果。"
        log_prompt = (
            "# 角色设定\n"
            "你是一个极其严谨的日志分析与数据清洗专家。你的唯一目标是从混杂着正常信息的原始日志堆栈中，提取出最致命的报错线索。\n\n"
            "# 当前任务\n"
            f"Code Agent 刚刚使用关键词组合 {keywords} 在生产服务器上执行了 grep 搜索，并截取了以下原始日志片段：\n\n"
            "<raw_logs>\n"
            f"{raw_log_output}\n"
            "</raw_logs>\n\n"
            "# 处理指令\n"
            "请将上述原始日志提纯为一份高信噪比的“日志化验报告”。你必须遵循以下原则：\n"
            "1. **去噪**：剔除毫无意义的 DEBUG/INFO 日志，忽略健康检查（Health Check）等噪音。\n"
            "2. **提取堆栈**：精准保留包含 ERROR、Exception、FATAL、WARN 的那几行，特别是带有【具体代码文件名和行号】的调用栈（Stack Trace）。\n"
            "3. **保留上下文**：如果报错前紧挨着有 HTTP 请求体（Request Payload）或关键变量打印，必须保留，这往往是诱因。\n"
            "4. **如实汇报**：如果日志中确实没有任何报错信息，请直接输出：“未找到匹配的异常日志，当前的日志均为常规/正常打印。”绝不要伪造报错。\n\n"
            "# 输出格式\n"
            "请直接输出提纯后的日志内容（不超过 1000 字），不需要任何寒暄或解释。"
        )

        try:
            purified_logs = self._message_content(self.llm.invoke(log_prompt)).strip()
        except Exception as e:
            logger.warning("Log Agent 提纯失败，退化为原始片段: %s", e)
            purified_logs = raw_log_output
        purified_logs = (purified_logs or "未找到匹配的异常日志，当前的日志均为常规/正常打印。")[:1000]

        msg = SystemMessage(
            content=(
                "以下是 Log Agent 的日志取证结果（已精简）：\n"
                f"{purified_logs}"
            ),
            id=self._new_id(),
        )

        token_after = int(state.get("token_count", 0)) + self._estimate_tokens_for_message(msg)
        return {
            "purified_logs": purified_logs,
            "pending_log_keywords": [],
            "messages": [msg],
            "token_count": token_after,
        }

    def _compaction_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        mem = state.get("working_memory", "")
        summary_prompt = (
            "# 角色设定\n"
            "你是一个负责“信息熵压缩”的记忆整理专家。由于排障过程极为漫长，当前对话上下文的 Token 已经接近熔断阈值，你需要将冗长的对话历史折叠成高度浓缩的“排障备忘录（Working Memory）”。\n\n"
            "# 当前状态\n"
            f"- 旧版本的排障备忘录：{mem}\n"
            "- 最新一轮的冗长对话记录：\n"
            "<recent_messages>\n"
            f"{self._messages_to_text(messages)}\n"
            "</recent_messages>\n\n"
            "# 压缩指令\n"
            "请生成一份全新的、覆盖全局的排障备忘录。你必须遵循 MECE（相互独立、完全穷尽）原则：\n"
            "1. **必须保留的硬核线索（Entities）**：\n"
            "   - 已经尝试过哪些日志搜索关键词（避免 Code Agent 重复盲搜）？\n"
            "   - 已经确认发生报错的具体代码文件路径和行号？\n"
            "   - 已经推翻了哪些假设（如：“已确认不是 DB 超时导致”）？\n"
            "2. **必须丢弃的废料**：\n"
            "   - 具体的巨长无比的几十行 Java/Python 报错堆栈（只需记录“XXX文件在YY行报了NullPointer”即可）。\n"
            "   - Agent 之间的客套话、冗长的思考过程、工具调用的 JSON 格式外壳。\n\n"
            "# 输出格式\n"
            "输出一篇字数极简（通常不超过 500 字）、以 Markdown 列表（Bullet points）为主的纯粹备忘录。这份备忘录将作为 Code Agent 下一步推理的唯一前置上下文。"
        )

        try:
            response = self.llm.invoke(summary_prompt)
            new_summary = self._message_content(response).strip()
        except Exception as e:
            logger.warning("Compaction LLM 失败，退化为截断摘要: %s", e)
            raw = f"{mem}\n{self._messages_to_text(messages)}"
            new_summary = raw[-4000:]
        new_summary = new_summary[:500]

        delete_ops = [RemoveMessage(id=m.id) for m in state["messages"][:-1]]
        return {"working_memory": new_summary, "messages": delete_ops, "token_count": 0}

    def _summary_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        raw_root_cause = state.get("raw_root_cause", "").strip()
        if not raw_root_cause:
            raw_root_cause = "未在循环上限内拿到确凿根因，以下为当前最可信线索。\n" + (
                state.get("working_memory", "") or "暂无可用线索"
            )

        prompt = (
            "# 角色设定\n"
            "你是一位资深的研发技术总监。你的开发团队（Code Agent）刚刚经过艰苦的排查，找到了一个线上故障的根本原因。\n"
            "你需要将他们提供的硬核技术根因，转译为一份对业务方和开发人员都高度友好的《故障复盘与修复报告》。\n\n"
            "# 输入信息\n"
            f"- 触发本次排障的用户原始反馈：{state.get('query', '')}\n"
            f"- Code Agent 提交的硬核技术诊断结果：{raw_root_cause}\n\n"
            "# 撰写要求\n"
            "请使用专业的 Markdown 格式，生成一份结构清晰的报告。语气应保持客观、专业、有建设性。报告必须严格包含以下 4 个部分：\n\n"
            "## 🚨 1. 故障现象摘要\n"
            "- 用一句通俗的话概括用户遇到了什么问题（What happened）。\n\n"
            "## 🔍 2. 根本原因分析 (Root Cause)\n"
            "- 简明扼要地解释为什么会报错（Why it happened）。\n"
            "- **必须明确指出**：存在缺陷的具体代码文件路径、引发异常的方法名及行号（直击痛点）。\n\n"
            "## 🛠️ 3. 修复方案 (Resolution)\n"
            "- 针对该 Root Cause 提出具体的代码修改建议（How to fix）。\n"
            "- 请使用 Markdown 的代码块 (```语言) 给出修复前后的伪代码对比或补丁（Patch）示例。\n\n"
            "## 💡 4. 后续改进建议 (Action Items)\n"
            "- 从架构、日志规范或防御性编程的角度，给出 1-2 条避免同类问题再次发生的建议。\n\n"
            "请直接输出 Markdown 报告，无需前言后语。"
        )

        try:
            response = self.llm.invoke(prompt)
            report = self._message_content(response).strip()
        except Exception as e:
            logger.warning("Summary Agent LLM 失败，使用模板兜底: %s", e)
            report = (
                "# 故障分析报告\n\n"
                "## 现象\n"
                f"{state.get('query', '')}\n\n"
                "## 技术根因\n"
                f"{raw_root_cause}\n\n"
                "## 修复建议\n"
                "1. 基于上述根因先做最小修复并回归。\n"
                "2. 补充对应模块的监控与告警。\n"
            )

        return {"final_report": report}

    def _to_structured_result(self, final_state: InvestigationState, execution_time: float) -> Dict[str, Any]:
        final_report = final_state.get("final_report", "")
        raw_root_cause = final_state.get("raw_root_cause", "")
        summary = final_report.split("\n", 1)[0].lstrip("# ").strip() if final_report else "分析完成"

        recommendations: List[str] = []
        for line in final_report.splitlines():
            line = line.strip()
            if re.match(r"^(?:[-*]|\d+\.)\s+", line):
                recommendations.append(re.sub(r"^(?:[-*]|\d+\.)\s+", "", line))
        recommendations = recommendations[:6]

        plan_steps = [
            {
                "id": "step_1",
                "title": "Code Agent 推理",
                "description": "结合工作记忆、日志证据和源码逐步定位根因",
                "status": "completed",
            },
            {
                "id": "step_2",
                "title": "Log Agent 取证",
                "description": "按关键词检索日志并回传精简证据",
                "status": "completed" if final_state.get("purified_logs") else "pending",
            },
            {
                "id": "step_3",
                "title": "Compaction Agent 压缩",
                "description": "当 token 超阈值时压缩上下文并清理历史消息",
                "status": "completed" if final_state.get("working_memory") else "pending",
            },
            {
                "id": "step_4",
                "title": "Summary Agent 出报告",
                "description": "输出业务友好的故障报告",
                "status": "completed" if final_report else "pending",
            },
        ]

        return {
            "id": str(uuid.uuid4()),
            "query": final_state.get("query", ""),
            "status": "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "plan": {
                "content": "四维智能体流程已执行：Code -> Log -> (Compaction) -> Summary",
                "steps": plan_steps,
                "total_steps": len(plan_steps),
                "completed_steps": sum(1 for s in plan_steps if s["status"] == "completed"),
            },
            "acts": [],
            "final_result": {
                "content": final_report,
                "summary": summary,
                "recommendations": recommendations,
            },
            "metadata": {
                "execution_time": round(float(execution_time), 3),
                "model_used": getattr(self.llm, "model_name", "unknown"),
                "tokens_used": final_state.get("token_count", 0),
            },
            "graph_state": {
                "raw_root_cause": raw_root_cause,
                "working_memory": final_state.get("working_memory", ""),
                "iteration_count": final_state.get("iteration_count", 0),
                "token_count": final_state.get("token_count", 0),
            },
        }

    def _read_code_snippet(self, workspace_dir: str, file_path: str, start_line: int, end_line: int) -> str:
        if not workspace_dir:
            return "ReadCodeTool error: workspace_dir 为空。"

        ws = Path(workspace_dir).resolve()
        requested = Path(file_path)
        if not requested.is_absolute():
            requested = (ws / requested).resolve()
        else:
            requested = requested.resolve()

        try:
            requested.relative_to(ws)
        except Exception:
            return f"ReadCodeTool error: 路径越界，禁止读取工作区外文件: {requested}"

        if not requested.exists() or not requested.is_file():
            return f"ReadCodeTool error: 文件不存在: {requested}"

        s = max(1, int(start_line))
        e = max(s, int(end_line))
        if e - s + 1 > 100:
            e = s + 99

        try:
            lines = requested.read_text(encoding="utf-8", errors="ignore").splitlines()
            selected = lines[s - 1 : e]
        except Exception as e_read:
            return f"ReadCodeTool error: 读取失败: {e_read}"

        numbered = "\n".join(f"{i + s:>6} | {line}" for i, line in enumerate(selected))
        rel = requested.relative_to(ws)
        return f"# {rel}:{s}-{e}\n```\n{numbered}\n```"

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _safe_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return int(default)

    def _normalize_ai_message(self, response: Any) -> AIMessage:
        if isinstance(response, AIMessage):
            msg = response
        else:
            msg = AIMessage(content=self._message_content(response), id=self._new_id())

        if not getattr(msg, "id", None):
            msg = msg.model_copy(update={"id": self._new_id()})

        tool_calls = self._extract_tool_calls(msg)
        if tool_calls and not getattr(msg, "tool_calls", None):
            msg = msg.model_copy(update={"tool_calls": tool_calls})
        return msg

    def _extract_tool_calls(self, msg: BaseMessage) -> List[Dict[str, Any]]:
        tc = getattr(msg, "tool_calls", None)
        if isinstance(tc, list) and tc:
            return tc

        ak = getattr(msg, "additional_kwargs", {}) or {}
        raw_calls = ak.get("tool_calls") or []
        parsed: List[Dict[str, Any]] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") or {}
            parsed.append(
                {
                    "id": item.get("id") or self._new_id(),
                    "name": fn.get("name"),
                    "args": self._coerce_args(fn.get("arguments")),
                }
            )
        return parsed

    @staticmethod
    def _coerce_args(raw: Any) -> Dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                return {}
        return {}

    @staticmethod
    def _message_content(message: Any) -> str:
        content = getattr(message, "content", message)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out: List[str] = []
            for item in content:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    out.append(str(item.get("text") or item.get("content") or item))
                else:
                    out.append(str(item))
            return "\n".join(out)
        return str(content)

    def _estimate_tokens_for_message(self, msg: BaseMessage) -> int:
        text = self._message_content(msg)
        # 近似估算：1个中文=1 token，1个英文字符≈0.3 token
        return self._estimate_tokens(text)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        ascii_chars = sum(1 for c in text if c.isascii())
        non_ascii_chars = max(0, len(text) - ascii_chars)
        estimate = int(non_ascii_chars + ascii_chars * 0.3)
        return max(1, estimate)

    def _messages_to_text(self, messages: List[BaseMessage]) -> str:
        chunks: List[str] = []
        for m in messages:
            role = getattr(m, "type", m.__class__.__name__)
            chunks.append(f"[{role}] {self._message_content(m)}")
        return "\n\n".join(chunks)
