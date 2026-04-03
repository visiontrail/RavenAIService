"""五维多智能体日志+代码联合分析图（含 Supervisor 总控）。"""

from __future__ import annotations

import json
import logging
import operator
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Annotated, Dict, List, Optional, Tuple, TypedDict
from urllib.parse import urlparse, urlunparse

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
except Exception:  # pragma: no cover
    StateGraph = None  # type: ignore
    END = None  # type: ignore

from app.agents.log_agent import get_llm
from app.config import settings
from app.tools.grep_tool import grep_file_xml

logger = logging.getLogger(__name__)

# ─────────────────────────────── 常量 ─────────────────────────────────────
_RG_BIN: Optional[str] = shutil.which("rg") or shutil.which("ripgrep")
_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".svn", "venv", ".venv",
    "build", "dist", "target", ".cache", ".tox", "coverage", ".idea", ".vscode",
})
_MAX_GREP_OUTPUT  = 8000   # grep 结果最大字符数
_MAX_GLOB_FILES   = 80     # glob 结果最大文件数
_MAX_TREE_LINES   = 150    # 文件树最大行数
_MAX_LIST_ENTRIES = 200    # 目录列表最大条目数
_MAX_FIND_OUTPUT  = 6000   # 符号定义搜索最大字符数
_MAX_TOOL_LOG_CHARS = 2400  # TOOL_RESULT 日志最大字符数（摘要后）
_FILE_TREE_LOG_HEAD_LINES = 24
_FILE_TREE_LOG_TAIL_LINES = 12
_MAX_CODE_AGENT_STEPS_PER_VISIT = 4  # 单次 code_agent 节点内最多连续执行的 ReAct 步数
_MAX_SUBAGENT_RESULT_CHARS = 2200
_EXPLORE_STEP_LIMITS = {
    "quick": 2,
    "medium": 4,
    "very_thorough": 6,
}

# 日志类型 -> 仓库 URL 的映射键
_LOG_TYPE_OAM_KEYS   = {"oam", "oam_antenna"}
_LOG_TYPE_STACK_KEYS = {"stack", "full"}
_CODE_EXECUTION_TOOL_NAMES = frozenset({
    "CloneRepoTool",
    "ReadCodeTool",
    "GrepCodeTool",
    "GlobCodeTool",
    "ListDirTool",
    "FindDefinitionTool",
    "GetFileTreeTool",
})
_EXPLORE_AGENT_TOOL_NAMES = frozenset({
    "ReadCodeTool",
    "GrepCodeTool",
    "GlobCodeTool",
    "ListDirTool",
    "FindDefinitionTool",
    "GetFileTreeTool",
})
_CODE_CONTROL_TOOL_NAMES = frozenset({
    "DelegateSubAgentTool",
    "SubmitDiagnosisTool",
})
_LOG_AGENT_TOOL_NAMES = frozenset({
    "LogKeywordSearchTool",
})
_CODE_EVIDENCE_TOOLS = frozenset({
    "ReadCodeTool",
    "GrepCodeTool",
    "GlobCodeTool",
    "ListDirTool",
    "FindDefinitionTool",
    "GetFileTreeTool",
})
_NO_LOG_MATCH_MARKERS = (
    "未找到匹配的异常日志",
    "无有效检索结果",
    "no matching log",
    "no match",
)


# ─────────────────────────────── 状态 ─────────────────────────────────────

class InvestigationState(TypedDict):
    # --- 基础上下文 ---
    query: str
    workspace_dir: str
    log_file_path: str
    log_type: str        # "oam_antenna" | "stack" | "full" | "unknown"
    repo_url: str        # 本轮分析允许使用的仓库 URL（优先元数据）
    repo_branch: str     # 本轮分析优先分支（从日志元数据提取）
    repo_commit_id: str  # 本轮分析优先 commit（从日志元数据提取）
    repo_cloned: bool    # workspace_dir 是否已指向克隆好的代码仓库
    trace_id: str        # 本次分析链路追踪ID（便于与HTTP日志关联）
    llm_call_count: int  # 当前 run 内累计 LLM 调用轮次

    # --- 对话与上下文管理 ---
    messages: Annotated[List[BaseMessage], operator.add]
    working_memory: str
    token_count: int
    iteration_count: int

    # --- 动态指令流转 ---
    pending_log_keywords: List[str]
    purified_logs: str
    log_search_attempts: int
    code_tool_invocations: int
    supervisor_plan: str
    supervisor_reflection: str
    supervisor_round: int
    next_node: str

    # --- 结果产出 ---
    raw_root_cause: str
    final_report: str


# ─────────────────────────────── 主图 ─────────────────────────────────────

class CodeAnalysisGraph:
    """多智能体排障编排：Supervisor -> Code/(SubAgents)/Compaction -> Summary。"""

    def __init__(self, token_limit: int = 8000, max_iterations: int = 10):
        if StateGraph is None or END is None:
            raise RuntimeError("langgraph 不可用，无法初始化 CodeAnalysisGraph")

        self.token_limit = int(token_limit)
        self.max_iterations = int(max_iterations)
        self.llm = get_llm()
        self._code_execution_tools = self._build_code_execution_tools()
        self._explore_tools = [
            tool for tool in self._code_execution_tools
            if tool.name in _EXPLORE_AGENT_TOOL_NAMES
        ]
        self._code_control_tools = self._build_code_control_tools()
        self._code_tools = [*self._code_execution_tools, *self._code_control_tools]
        self._log_tools = self._build_log_agent_tools()
        self._code_llm_with_tools = self._bind_tools_with_fallback(
            tools=self._code_tools,
            agent_label="Code Agent",
        )
        self._explore_llm_with_tools = self._bind_tools_with_fallback(
            tools=self._explore_tools,
            agent_label="Explore SubAgent",
        )

        logger.info(
            "AGENT_TOOLSETS_INIT code_execution=%s code_control=%s explore_subagent=%s log_agent=%s",
            sorted(_CODE_EXECUTION_TOOL_NAMES),
            sorted(_CODE_CONTROL_TOOL_NAMES),
            sorted(_EXPLORE_AGENT_TOOL_NAMES),
            sorted(_LOG_AGENT_TOOL_NAMES),
        )

        graph = StateGraph(InvestigationState)
        graph.add_node("supervisor_agent", self._supervisor_agent_node)
        graph.add_node("code_agent", self._code_agent_node)
        graph.add_node("compaction_agent", self._compaction_agent_node)
        graph.add_node("summary_agent", self._summary_agent_node)

        graph.set_entry_point("supervisor_agent")
        graph.add_conditional_edges(
            "supervisor_agent",
            self._route_after_supervisor,
            {
                "code_agent": "code_agent",
                "compaction_agent": "compaction_agent",
                "summary_agent": "summary_agent",
            },
        )
        graph.add_edge("code_agent", "supervisor_agent")
        graph.add_edge("compaction_agent", "supervisor_agent")
        graph.add_edge("summary_agent", END)

        self._app = graph.compile()

    # ─────────────────────── Public API ────────────────────────────────────

    def run(
        self,
        query: str,
        workspace_dir: str,
        log_file_path: str,
        log_type: str = "unknown",
        repo_url: str = "",
        repo_branch: str = "",
        repo_commit_id: str = "",
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        runtime_trace_id = (trace_id or f"ca-{uuid.uuid4().hex[:10]}").strip()
        logger.info(
            "CodeAnalysisGraph run started: trace_id=%s log_type=%s workspace_dir=%s log_file=%s query=%s",
            runtime_trace_id,
            log_type or "unknown",
            workspace_dir or "(empty)",
            log_file_path or "(empty)",
            self._truncate_for_log(query, max_len=180),
        )
        state: InvestigationState = {
            "query": query,
            "workspace_dir": workspace_dir,
            "log_file_path": log_file_path,
            "log_type": log_type or "unknown",
            "repo_url": (repo_url or "").strip(),
            "repo_branch": (repo_branch or "").strip(),
            "repo_commit_id": (repo_commit_id or "").strip(),
            "repo_cloned": bool(workspace_dir),
            "trace_id": runtime_trace_id,
            "llm_call_count": 0,
            "messages": [HumanMessage(content=query, id=self._new_id())],
            "working_memory": "",
            "token_count": 0,
            "iteration_count": 0,
            "pending_log_keywords": [],
            "purified_logs": "",
            "log_search_attempts": 0,
            "code_tool_invocations": 0,
            "supervisor_plan": "",
            "supervisor_reflection": "",
            "supervisor_round": 0,
            "next_node": "code_agent",
            "raw_root_cause": "",
            "final_report": "",
        }

        final_state = self._app.invoke(state, config={"recursion_limit": 80})
        elapsed = time.time() - start_time
        logger.info(
            "CodeAnalysisGraph run completed: trace_id=%s elapsed=%.3fs iterations=%s llm_calls=%s final_report_chars=%d",
            runtime_trace_id,
            elapsed,
            final_state.get("iteration_count", 0),
            final_state.get("llm_call_count", 0),
            len(final_state.get("final_report", "") or ""),
        )
        return self._to_structured_result(final_state, execution_time=elapsed)

    def get_agent_toolset_allocation(self) -> Dict[str, List[str]]:
        """返回多 Agent 的工具分配，便于审计与后续调参。"""
        return {
            "supervisor_agent": [],
            "code_agent.execution": sorted(_CODE_EXECUTION_TOOL_NAMES),
            "code_agent.control": sorted(_CODE_CONTROL_TOOL_NAMES),
            "subagent.explore": sorted(_EXPLORE_AGENT_TOOL_NAMES),
            "subagent.log": sorted(_LOG_AGENT_TOOL_NAMES),
            "compaction_agent": [],
            "summary_agent": [],
        }

    # ─────────────────────── Routing ───────────────────────────────────────

    def _route_after_supervisor(self, state: InvestigationState) -> str:
        nxt = str(state.get("next_node", "code_agent") or "code_agent")
        if nxt not in {"code_agent", "compaction_agent", "summary_agent"}:
            return "code_agent"
        return nxt

    def _bind_tools_with_fallback(self, tools: List[StructuredTool], agent_label: str) -> Any:
        try:
            return self.llm.bind_tools(tools)
        except Exception as e:
            logger.warning(
                "bind_tools 失败，%s 将退化为无工具模式: llm_class=%s error_type=%s error=%r",
                agent_label,
                type(self.llm).__name__,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return self.llm

    # ────────────────────── Tool Definitions ───────────────────────────────

    def _build_code_execution_tools(self) -> List[StructuredTool]:
        """构建 Code Agent 的代码执行工具集合。"""

        def clone_repo_tool(log_type: str, branch: str = "", force_refresh: bool = True) -> str:
            """根据日志类型将对应的代码仓库克隆到临时工作区，并切换当前工作区路径。

            log_type 可选: 'oam_antenna'（OAM天线模块）或 'stack'（协议栈模块）。
            branch 可选：优先切换到该分支（为空则使用远端默认分支）。
            force_refresh 默认为 true：每次都重新克隆，避免使用陈旧工作区。
            必须在使用任何代码阅读/搜索工具之前调用，否则工作区为空。
            """
            return f"已请求克隆仓库: log_type={log_type}, branch={branch}, force_refresh={force_refresh}"

        def read_code_tool(file_path: str, start_line: int, end_line: int) -> str:
            """读取工作区中指定源码文件的片段，每次最多 100 行。

            file_path: 相对于工作区根目录的路径，例如 'src/radio/oam_handler.c'。
            start_line / end_line: 起止行号（1-indexed）。
            """
            return f"已请求读取代码: {file_path}:{start_line}-{end_line}"

        def grep_code_tool(
            pattern: str,
            directory: str = "",
            file_glob: str = "",
            context_lines: int = 2,
        ) -> str:
            """在工作区源码中搜索匹配正则或字面量模式的代码行（类似 ripgrep/grep -n）。

            pattern: 正则表达式或字面量搜索词，如 'NullPointerException', 'oam_init\\s*\\('。
            directory: 限定搜索的子目录（相对于工作区根，空则搜索全工作区）。
            file_glob: 文件类型过滤，如 '*.c', '*.h', '**/*.py', 'src/**/*.java'。
            context_lines: 每个匹配行前后显示的上下文行数（默认 2）。
            返回值将优先提炼为“函数名 / 日志关键词”候选，而不是完整代码片段。
            """
            return f"已请求代码搜索: pattern={pattern}"

        def glob_code_tool(pattern: str, directory: str = "") -> str:
            """按 glob 模式查找工作区中匹配的文件路径列表，适合快速定位文件。

            pattern: glob 模式，如 '**/*.h', 'src/**/*.c', '**/Makefile', '**/*oam*.c'。
            directory: 搜索的起始子目录（空则从工作区根目录开始）。
            """
            return f"已请求文件 glob 搜索: pattern={pattern}"

        def list_dir_tool(directory: str = "", max_depth: int = 2) -> str:
            """列出工作区指定目录下的文件和子目录（带层级缩进）。

            directory: 相对于工作区根的子目录路径（空则列出根目录）。
            max_depth: 最大遍历深度（默认 2）。
            """
            return f"已请求列目录: directory={directory}"

        def find_definition_tool(symbol: str, file_glob: str = "") -> str:
            """在工作区源码中快速定位函数、类、结构体、宏等符号的定义位置。

            symbol: 要查找的符号名，如 'oam_init', 'RadioContext', 'MAX_RETRY'。
            file_glob: 文件过滤，如 '*.c', '*.h', '*.py'（空则搜索所有文本文件）。
            返回值将优先给出定义命中的函数名候选列表。
            """
            return f"已请求查找符号定义: symbol={symbol}"

        def get_file_tree_tool(directory: str = "", max_depth: int = 3) -> str:
            """获取工作区目录树的概览视图，帮助快速理解代码结构。

            自动忽略 .git、node_modules、__pycache__ 等噪音目录。
            directory: 起始子目录（空则从工作区根目录开始）。
            max_depth: 最大显示深度（默认 3）。
            """
            return f"已请求获取文件树: directory={directory}"

        return [
            StructuredTool.from_function(clone_repo_tool,      name="CloneRepoTool"),
            StructuredTool.from_function(read_code_tool,       name="ReadCodeTool"),
            StructuredTool.from_function(grep_code_tool,       name="GrepCodeTool"),
            StructuredTool.from_function(glob_code_tool,       name="GlobCodeTool"),
            StructuredTool.from_function(list_dir_tool,        name="ListDirTool"),
            StructuredTool.from_function(find_definition_tool, name="FindDefinitionTool"),
            StructuredTool.from_function(get_file_tree_tool,   name="GetFileTreeTool"),
        ]

    def _build_code_control_tools(self) -> List[StructuredTool]:
        """构建 Code Agent 的跨 Agent 控制工具集合。"""

        def delegate_subagent_tool(
            subagent_type: str,
            task: str,
            expected_output: str = "",
            thoroughness: str = "medium",
            keywords: Optional[List[str]] = None,
        ) -> str:
            """委托受限子代理执行聚焦任务，并把结果作为单条消息返回给当前 Code Agent。

            这是参考 opencode TaskTool 的协作模式：主 Agent 不做硬切换，而是在需要时主动发起委托。
            - subagent_type: 'explore' | 'log'
            - task: 明确描述子代理要解决的子问题、搜索范围、返回形式
            - expected_output: 希望子代理最终回传的结果结构
            - thoroughness: explore 子代理的探索强度，可选 quick | medium | very thorough
            - keywords: log 子代理使用的英文日志关键词；为空时会自动从 task / query 中推断
            """
            return (
                "已请求子代理: "
                f"subagent_type={subagent_type}, thoroughness={thoroughness}, keywords={keywords or []}"
            )

        def submit_diagnosis_tool(root_cause_analysis: str) -> str:
            """当通过源码找到了确凿的缺陷后，调用此工具提交技术分析报告并结束排查。"""
            return f"已提交根因分析: {root_cause_analysis[:120]}"

        return [
            StructuredTool.from_function(delegate_subagent_tool, name="DelegateSubAgentTool"),
            StructuredTool.from_function(submit_diagnosis_tool, name="SubmitDiagnosisTool"),
        ]

    def _build_log_agent_tools(self) -> Dict[str, Any]:
        """构建 Log Agent 的日志取证工具集合。"""

        def log_keyword_search_tool(
            log_file_path: str,
            keywords: List[str],
            context_lines: int = 2,
            trace_id: str = "unknown",
            attempt: int = 0,
        ) -> str:
            if not keywords:
                return "[LogAgent] 未收到关键词，无法执行日志检索。"

            chunks: List[str] = []
            for raw_keyword in keywords[:8]:
                keyword = str(raw_keyword).strip()
                if not keyword:
                    continue
                try:
                    xml = grep_file_xml(log_file_path, keyword, context=context_lines)
                    logger.info(
                        "LOG_AGENT_RAW_GREP trace_id=%s attempt=%s keyword=%s xml=%s",
                        trace_id,
                        attempt,
                        keyword,
                        xml,
                    )
                    chunks.append(f"<keyword>{keyword}</keyword>\n{xml}")
                except Exception as e:
                    chunks.append(f"<keyword>{keyword}</keyword>\n<error>{e}</error>")
            return "\n\n".join(chunks).strip() or "[LogAgent] 无有效检索结果。"

        return {
            "LogKeywordSearchTool": log_keyword_search_tool,
        }

    # ─────────────────────── Agent Nodes ───────────────────────────────────

    def _supervisor_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        """总控节点：统一做计划、调度与反思。"""
        trace_id = state.get("trace_id", "unknown")
        llm_call_count = int(state.get("llm_call_count", 0))
        supervisor_round = int(state.get("supervisor_round", 0)) + 1
        current_plan = state.get("supervisor_plan", "")
        default_next = self._default_next_node(state)

        prompt = (
            "# 角色设定\n"
            "你是多智能体排障流程的总控 Supervisor，职责是：规划 -> 调度 -> 反思。\n\n"
            "注意：`explore/log` 是 Code Agent 可自主委托的受限子代理，不是需要你硬切换的顶层节点。\n\n"
            "# 当前状态\n"
            f"- 用户问题：{state.get('query', '')}\n"
            f"- 日志类型：{state.get('log_type', 'unknown')}\n"
            f"- 工作区：{state.get('workspace_dir', '') or '(empty)'}\n"
            f"- 元数据分支：{state.get('repo_branch', '') or '(none)'}\n"
            f"- 元数据提交：{state.get('repo_commit_id', '') or '(none)'}\n"
            f"- 迭代轮次：{state.get('iteration_count', 0)} / {self.max_iterations}\n"
            f"- token计数：{state.get('token_count', 0)} / {self.token_limit}\n"
            f"- 当前根因状态：{('已提交' if state.get('raw_root_cause', '').strip() else '未提交')}\n"
            f"- 既有计划：{current_plan or '(empty)'}\n"
            f"- 默认下一跳（规则推导）：{default_next}\n\n"
            "# 最近上下文（节选）\n"
            "<recent_messages>\n"
            f"{self._messages_to_text((state.get('messages') or [])[-6:])}\n"
            "</recent_messages>\n\n"
            "# 输出要求\n"
            "只输出一个 JSON 对象，字段如下：\n"
            "{\n"
            '  "plan": "3-5 步简要计划，200字以内",\n'
            '  "reflection": "本轮反思与纠偏建议，180字以内",\n'
            '  "next_agent": "code_agent | compaction_agent | summary_agent"\n'
            "}\n"
            "禁止输出 JSON 之外的任何内容。"
        )

        plan = current_plan
        reflection = state.get("supervisor_reflection", "")
        chosen_next = default_next

        try:
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self.llm,
                payload=prompt,
                trace_id=trace_id,
                call_no=call_no,
                agent_name="supervisor_agent",
                purpose="planning_reflection_and_routing",
            )
            content = self._message_content(response).strip()
            decision = self._extract_json_dict(content)
            if decision:
                plan = str(decision.get("plan", plan) or plan).strip()
                reflection = str(decision.get("reflection", reflection) or reflection).strip()
                chosen_next = str(decision.get("next_agent", chosen_next) or chosen_next).strip()
        except Exception as exc:
            logger.warning("Supervisor LLM 失败，回退规则路由: %s", exc)

        # 总控约束优先于 LLM 建议
        constrained_next = self._apply_supervisor_constraints(state=state, suggested_next=chosen_next, fallback=default_next)
        if constrained_next != chosen_next:
            logger.info(
                "SUPERVISOR_ROUTE_ADJUST trace_id=%s round=%s suggested=%s constrained=%s",
                trace_id,
                supervisor_round,
                chosen_next,
                constrained_next,
            )
        chosen_next = constrained_next

        short_plan = (plan or "")[:400]
        short_reflection = (reflection or "")[:320]
        token_delta = self._estimate_tokens(short_plan + "\n" + short_reflection)

        logger.info(
            "SUPERVISOR_DECISION trace_id=%s round=%s next=%s plan=%s reflection=%s",
            trace_id,
            supervisor_round,
            chosen_next,
            self._truncate_for_log(short_plan, 220),
            self._truncate_for_log(short_reflection, 220),
        )

        return {
            "supervisor_round": supervisor_round,
            "supervisor_plan": short_plan,
            "supervisor_reflection": short_reflection,
            "next_node": chosen_next,
            "llm_call_count": llm_call_count,
            "token_count": int(state.get("token_count", 0)) + token_delta,
        }

    def _code_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        trace_id = state.get("trace_id", "unknown")
        workspace_dir = state.get("workspace_dir", "")
        log_type = state.get("log_type", "unknown")
        repo_cloned = bool(state.get("repo_cloned", False))
        repo_branch = state.get("repo_branch", "")
        repo_commit_id = state.get("repo_commit_id", "")

        llm_call_count = int(state.get("llm_call_count", 0))
        iteration_count = int(state.get("iteration_count", 0))
        token_count = int(state.get("token_count", 0))
        code_tool_invocations = int(state.get("code_tool_invocations", 0))

        produced_messages: List[BaseMessage] = []
        conversation_messages: List[BaseMessage] = list(state.get("messages", []))
        raw_root_cause = ""
        merged_extra_state: Dict[str, Any] = {}
        exit_reason = "step_limit_reached"

        for step in range(1, _MAX_CODE_AGENT_STEPS_PER_VISIT + 1):
            sys_prompt = self._build_code_agent_prompt(
                query=state.get("query", ""),
                workspace_dir=workspace_dir,
                log_type=log_type,
                repo_cloned=repo_cloned,
                code_tool_invocations=code_tool_invocations,
                log_search_attempts=int(state.get("log_search_attempts", 0)),
                working_memory=state.get("working_memory", ""),
                purified_logs=state.get("purified_logs", ""),
                supervisor_plan=state.get("supervisor_plan", ""),
                supervisor_reflection=state.get("supervisor_reflection", ""),
                repo_branch=repo_branch,
                repo_commit_id=repo_commit_id,
            )
            prompt_messages: List[BaseMessage] = [
                SystemMessage(content=sys_prompt, id=self._new_id()),
                *conversation_messages,
            ]

            call_no = llm_call_count + 1
            response = self._invoke_llm_with_trace(
                llm=self._code_llm_with_tools,
                payload=prompt_messages,
                trace_id=trace_id,
                call_no=call_no,
                agent_name="code_agent",
                purpose=f"reasoning_and_tool_selection_step_{step}",
            )
            response = self._normalize_ai_message(response)

            llm_call_count = call_no
            iteration_count += 1
            token_count += self._estimate_tokens_for_message(response)
            produced_messages.append(response)
            conversation_messages.append(response)

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                exit_reason = "no_tool_call"
                break

            first_call = tool_calls[0]
            tool_name = first_call.get("name")
            args = self._coerce_args(first_call.get("args"))
            call_id = str(first_call.get("id") or self._new_id())

            if tool_name == "SubmitDiagnosisTool":
                analysis = str(args.get("root_cause_analysis", "")).strip()
                if analysis:
                    raw_root_cause = analysis
                logger.info(
                    "TOOL_CONTROL trace_id=%s iter=%s tool=%s args=%s accepted=%s",
                    trace_id,
                    iteration_count,
                    tool_name,
                    json.dumps(args, ensure_ascii=False, sort_keys=True),
                    bool(analysis),
                )
                exit_reason = "diagnosis_submitted"
                break

            logger.info(
                "TOOL_CALL trace_id=%s iter=%s tool=%s args=%s",
                trace_id,
                iteration_count,
                tool_name or "unknown",
                json.dumps(args, ensure_ascii=False, sort_keys=True),
            )
            result_content, extra_state = self._dispatch_tool(
                tool_name=tool_name,
                args=args,
                workspace_dir=workspace_dir,
                log_type=log_type,
                repo_url=state.get("repo_url", ""),
                repo_branch=repo_branch,
                repo_commit_id=repo_commit_id,
                trace_id=trace_id,
                llm_call_count=llm_call_count,
                query=state.get("query", ""),
                working_memory=state.get("working_memory", ""),
                purified_logs=state.get("purified_logs", ""),
                log_file_path=state.get("log_file_path", ""),
                log_search_attempts=int(state.get("log_search_attempts", 0)),
                supervisor_plan=state.get("supervisor_plan", ""),
                supervisor_reflection=state.get("supervisor_reflection", ""),
            )

            tool_msg = ToolMessage(
                content=result_content,
                tool_call_id=call_id,
                name=tool_name or "UnknownTool",
                id=self._new_id(),
            )
            produced_messages.append(tool_msg)
            conversation_messages.append(tool_msg)
            token_count += self._estimate_tokens(result_content)

            if extra_state:
                merged_extra_state.update(extra_state)
                workspace_dir = str(extra_state.get("workspace_dir", workspace_dir) or workspace_dir)
                log_type = str(extra_state.get("log_type", log_type) or log_type)
                repo_branch = str(extra_state.get("repo_branch", repo_branch) or repo_branch)
                repo_commit_id = str(extra_state.get("repo_commit_id", repo_commit_id) or repo_commit_id)
                repo_cloned = bool(extra_state.get("repo_cloned", repo_cloned))
                llm_call_count = int(extra_state.get("llm_call_count", llm_call_count))

            if tool_name in _CODE_EVIDENCE_TOOLS:
                code_tool_invocations += 1
            elif tool_name == "DelegateSubAgentTool" and str(extra_state.get("subagent_type", "")).lower() == "explore":
                code_tool_invocations += 1

            logged_content = self._summarize_tool_result_for_log(
                tool_name=tool_name or "unknown",
                result_content=result_content,
            )
            logger.info(
                "TOOL_RESULT trace_id=%s iter=%s tool=%s result_chars=%d extra_state_keys=%s content=%s",
                trace_id,
                iteration_count,
                tool_name or "unknown",
                len(result_content or ""),
                ",".join(sorted(extra_state.keys())) if extra_state else "(none)",
                logged_content,
            )
            exit_reason = "tool_executed_continue"

        logger.info(
            "CODE_AGENT_VISIT_END trace_id=%s final_iter=%s llm_calls=%s steps_limit=%s exit_reason=%s produced_msgs=%s",
            trace_id,
            iteration_count,
            llm_call_count,
            _MAX_CODE_AGENT_STEPS_PER_VISIT,
            exit_reason,
            len(produced_messages),
        )

        updates: Dict[str, Any] = {
            "messages": produced_messages,
            "iteration_count": iteration_count,
            "token_count": token_count,
            "llm_call_count": llm_call_count,
            "code_tool_invocations": code_tool_invocations,
        }
        if raw_root_cause:
            updates["raw_root_cause"] = raw_root_cause
        if merged_extra_state:
            updates.update(merged_extra_state)
        return updates

    def _dispatch_tool(
        self,
        tool_name: Optional[str],
        args: Dict[str, Any],
        workspace_dir: str,
        log_type: str,
        repo_url: str,
        repo_branch: str,
        repo_commit_id: str,
        trace_id: str = "unknown",
        llm_call_count: int = 0,
        query: str = "",
        working_memory: str = "",
        purified_logs: str = "",
        log_file_path: str = "",
        log_search_attempts: int = 0,
        supervisor_plan: str = "",
        supervisor_reflection: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        """执行工具并返回 (result_text, extra_state_updates)。"""
        extra: Dict[str, Any] = {}

        if tool_name == "CloneRepoTool":
            requested_type = str(args.get("log_type", log_type) or log_type).lower().strip()
            requested_branch = str(args.get("branch", repo_branch) or repo_branch).strip()
            force_refresh = self._safe_bool(args.get("force_refresh"), True)
            new_workspace, msg = self._clone_repo(
                log_type=requested_type,
                branch=requested_branch,
                repo_url_override=str(repo_url or ""),
                commit_id=str(repo_commit_id or ""),
                force_refresh=force_refresh,
            )
            if new_workspace:
                extra["workspace_dir"] = new_workspace
                extra["repo_cloned"]   = True
                if requested_branch:
                    extra["repo_branch"] = requested_branch
            return msg, extra

        if tool_name == "ReadCodeTool":
            return self._read_code_snippet(
                workspace_dir = workspace_dir,
                file_path     = str(args.get("file_path", "")),
                start_line    = self._safe_int(args.get("start_line"), 1),
                end_line      = self._safe_int(args.get("end_line"), 80),
            ), extra

        if tool_name == "GrepCodeTool":
            return self._grep_code(
                workspace_dir = workspace_dir,
                pattern       = str(args.get("pattern", "")),
                directory     = str(args.get("directory", "") or ""),
                file_glob     = str(args.get("file_glob", "") or ""),
                context_lines = self._safe_int(args.get("context_lines"), 2),
            ), extra

        if tool_name == "GlobCodeTool":
            return self._glob_code(
                workspace_dir = workspace_dir,
                pattern       = str(args.get("pattern", "")),
                directory     = str(args.get("directory", "") or ""),
            ), extra

        if tool_name == "ListDirTool":
            return self._list_dir(
                workspace_dir = workspace_dir,
                directory     = str(args.get("directory", "") or ""),
                max_depth     = self._safe_int(args.get("max_depth"), 2),
            ), extra

        if tool_name == "FindDefinitionTool":
            return self._find_definition(
                workspace_dir = workspace_dir,
                symbol        = str(args.get("symbol", "")),
                file_glob     = str(args.get("file_glob", "") or ""),
            ), extra

        if tool_name == "GetFileTreeTool":
            return self._get_file_tree(
                workspace_dir = workspace_dir,
                directory     = str(args.get("directory", "") or ""),
                max_depth     = self._safe_int(args.get("max_depth"), 3),
            ), extra

        if tool_name == "DelegateSubAgentTool":
            subagent_type = self._normalize_subagent_type(args.get("subagent_type"))
            task = str(args.get("task", "") or "").strip()
            expected_output = str(args.get("expected_output", "") or "").strip()
            thoroughness = self._normalize_thoroughness(args.get("thoroughness"))
            raw_keywords = args.get("keywords")

            if subagent_type == "explore":
                return self._run_explore_subagent(
                    task=task,
                    expected_output=expected_output,
                    thoroughness=thoroughness,
                    workspace_dir=workspace_dir,
                    query=query,
                    working_memory=working_memory,
                    purified_logs=purified_logs,
                    trace_id=trace_id,
                    llm_call_count=llm_call_count,
                    supervisor_plan=supervisor_plan,
                    supervisor_reflection=supervisor_reflection,
                )

            if subagent_type == "log":
                keywords = raw_keywords
                if isinstance(keywords, str):
                    keywords = [k.strip() for k in re.split(r"[,，\s]+", keywords) if k.strip()]
                if not isinstance(keywords, list):
                    keywords = []
                return self._run_log_subagent(
                    task=task,
                    expected_output=expected_output,
                    keywords=keywords,
                    query=query,
                    log_file_path=log_file_path,
                    trace_id=trace_id,
                    llm_call_count=llm_call_count,
                    log_search_attempts=log_search_attempts,
                )

            return (
                "DelegateSubAgentTool error: 未知子代理类型。"
                "可选值：explore | log",
                {"subagent_type": subagent_type, "llm_call_count": llm_call_count},
            )

        return f"未知工具: {tool_name}", extra

    def _dispatch_log_tool(self, tool_name: str, **kwargs: Any) -> str:
        tool_fn = self._log_tools.get(tool_name)
        if not callable(tool_fn):
            return f"[LogAgent] 未知工具: {tool_name}"
        try:
            return str(tool_fn(**kwargs))
        except Exception as e:
            logger.warning("Log tool '%s' execution failed: %s", tool_name, e)
            return f"[LogAgent] 工具执行失败({tool_name}): {e}"

    @staticmethod
    def _normalize_subagent_type(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"explore", "search", "file_search", "file-search"}:
            return "explore"
        if text in {"log", "logs", "log_agent", "log-agent"}:
            return "log"
        return text

    @staticmethod
    def _normalize_thoroughness(value: Any) -> str:
        text = str(value or "medium").strip().lower().replace("-", " ").replace("_", " ")
        if text in {"quick", "fast"}:
            return "quick"
        if text in {"very thorough", "verythorough", "thorough", "deep"}:
            return "very_thorough"
        return "medium"

    def _explore_step_limit(self, thoroughness: str) -> int:
        return int(_EXPLORE_STEP_LIMITS.get(thoroughness, _EXPLORE_STEP_LIMITS["medium"]))

    def _build_explore_agent_prompt(
        self,
        task: str,
        expected_output: str,
        thoroughness: str,
        workspace_dir: str,
        query: str,
        working_memory: str,
        purified_logs: str,
        supervisor_plan: str,
        supervisor_reflection: str,
    ) -> str:
        thoroughness_display = {
            "quick": "quick",
            "medium": "medium",
            "very_thorough": "very thorough",
        }.get(thoroughness, "medium")
        return (
            "You are a file search specialist. You excel at thoroughly navigating and exploring codebases.\n\n"
            "Your strengths:\n"
            "- Rapidly finding files using glob patterns\n"
            "- Searching code and text with powerful regex patterns\n"
            "- Reading and analyzing file contents\n\n"
            "Available tools in this sandbox:\n"
            "- GlobCodeTool for broad file pattern matching\n"
            "- GrepCodeTool for searching file contents with regex\n"
            "- ReadCodeTool when you know the specific file path to inspect\n"
            "- ListDirTool and GetFileTreeTool for directory discovery\n"
            "- FindDefinitionTool for locating symbols\n\n"
            "Guidelines:\n"
            "- Adapt your search approach based on the caller thoroughness level\n"
            "- Return file paths as absolute paths in your final response\n"
            "- Do not create files, do not modify the workspace, and do not ask for agent switching\n"
            "- Prefer concise findings that help the caller decide what to read next\n\n"
            "Caller context:\n"
            f"- Workspace root: {workspace_dir}\n"
            f"- Thoroughness: {thoroughness_display}\n"
            f"- User issue: {query or '(none)'}\n"
            f"- Working memory: {working_memory or '(none)'}\n"
            f"- Latest log evidence: {purified_logs or '(none)'}\n"
            f"- Supervisor plan: {supervisor_plan or '(none)'}\n"
            f"- Supervisor reflection: {supervisor_reflection or '(none)'}\n\n"
            "Task from caller:\n"
            f"{task or query or '(empty)'}\n\n"
            "Expected output:\n"
            f"{expected_output or 'Summarize the most relevant files/symbols and suggest the next code reads.'}\n\n"
            "Final response format:\n"
            "## Findings\n"
            "- key findings\n"
            "## Candidate Files\n"
            "- /abs/path/to/file: why it matters\n"
            "## Suggested Next Reads\n"
            "- /abs/path/to/file:start-end"
        )

    def _fallback_explore_summary(self, messages: List[BaseMessage]) -> str:
        tool_outputs = [
            self._message_content(msg).strip()
            for msg in messages
            if isinstance(msg, ToolMessage) and self._message_content(msg).strip()
        ]
        if not tool_outputs:
            return "未产出有效探索结果。"
        tail = "\n\n".join(tool_outputs[-3:])
        return f"基于工具检索，当前最相关的线索如下：\n{tail}"[:_MAX_SUBAGENT_RESULT_CHARS]

    def _format_subagent_result(
        self,
        subagent_type: str,
        task: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        lines = [f"# {subagent_type} subagent result", f"- task: {task or '(empty)'}"]
        for key, value in (metadata or {}).items():
            text = str(value or "").strip()
            if text:
                lines.append(f"- {key}: {text}")
        lines.append("")
        lines.append((body or "未产出结果。").strip())
        text = "\n".join(lines).strip()
        if len(text) <= _MAX_SUBAGENT_RESULT_CHARS:
            return text
        return text[: _MAX_SUBAGENT_RESULT_CHARS - 3] + "..."

    def _run_explore_subagent(
        self,
        task: str,
        expected_output: str,
        thoroughness: str,
        workspace_dir: str,
        query: str,
        working_memory: str,
        purified_logs: str,
        trace_id: str,
        llm_call_count: int,
        supervisor_plan: str,
        supervisor_reflection: str,
    ) -> Tuple[str, Dict[str, Any]]:
        if not workspace_dir:
            result = self._format_subagent_result(
                subagent_type="explore",
                task=task or query,
                body="Explore subagent error: workspace_dir 为空，请先调用 CloneRepoTool 准备代码工作区。",
                metadata={"thoroughness": thoroughness},
            )
            return result, {"subagent_type": "explore", "llm_call_count": llm_call_count}

        system_prompt = self._build_explore_agent_prompt(
            task=task,
            expected_output=expected_output,
            thoroughness=thoroughness,
            workspace_dir=workspace_dir,
            query=query,
            working_memory=working_memory,
            purified_logs=purified_logs,
            supervisor_plan=supervisor_plan,
            supervisor_reflection=supervisor_reflection,
        )
        conversation: List[BaseMessage] = [
            HumanMessage(
                content=(
                    "# Caller Request\n"
                    f"{task or query or '(empty)'}\n\n"
                    "# Expected Output\n"
                    f"{expected_output or 'Return the most relevant files and why they matter.'}"
                ),
                id=self._new_id(),
            )
        ]
        final_text = ""
        max_steps = self._explore_step_limit(thoroughness)
        steps_used = 0

        for step in range(1, max_steps + 1):
            steps_used = step
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self._explore_llm_with_tools,
                payload=[SystemMessage(content=system_prompt, id=self._new_id()), *conversation],
                trace_id=trace_id,
                call_no=call_no,
                agent_name="explore_subagent",
                purpose=f"exploration_step_{step}",
            )
            response = self._normalize_ai_message(response)
            conversation.append(response)

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                final_text = self._message_content(response).strip()
                break

            first_call = tool_calls[0]
            tool_name = first_call.get("name")
            args = self._coerce_args(first_call.get("args"))
            call_id = str(first_call.get("id") or self._new_id())

            if tool_name not in _EXPLORE_AGENT_TOOL_NAMES:
                blocked_result = (
                    "Explore subagent error: 不允许使用该工具。"
                    f"tool={tool_name}; allowed={sorted(_EXPLORE_AGENT_TOOL_NAMES)}"
                )
                conversation.append(
                    ToolMessage(
                        content=blocked_result,
                        tool_call_id=call_id,
                        name=tool_name or "UnknownTool",
                        id=self._new_id(),
                    )
                )
                continue

            result_content, nested_extra = self._dispatch_tool(
                tool_name=tool_name,
                args=args,
                workspace_dir=workspace_dir,
                log_type="",
                repo_url="",
                repo_branch="",
                repo_commit_id="",
                trace_id=trace_id,
                llm_call_count=llm_call_count,
                query=query,
                working_memory=working_memory,
                purified_logs=purified_logs,
                supervisor_plan=supervisor_plan,
                supervisor_reflection=supervisor_reflection,
            )
            llm_call_count = int(nested_extra.get("llm_call_count", llm_call_count))
            conversation.append(
                ToolMessage(
                    content=result_content,
                    tool_call_id=call_id,
                    name=tool_name or "UnknownTool",
                    id=self._new_id(),
                )
            )

        if not final_text:
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self.llm,
                payload=[
                    SystemMessage(
                        content=(
                            system_prompt
                            + "\n\nYou have finished tool use. Summarize the findings now."
                            " Do not ask for more tools."
                        ),
                        id=self._new_id(),
                    ),
                    *conversation,
                ],
                trace_id=trace_id,
                call_no=call_no,
                agent_name="explore_subagent",
                purpose="final_summary",
            )
            final_text = self._message_content(response).strip()

        final_text = final_text or self._fallback_explore_summary(conversation)
        result = self._format_subagent_result(
            subagent_type="explore",
            task=task or query,
            body=final_text,
            metadata={
                "thoroughness": {
                    "quick": "quick",
                    "medium": "medium",
                    "very_thorough": "very thorough",
                }.get(thoroughness, "medium"),
                "workspace": workspace_dir,
                "steps_used": steps_used,
            },
        )
        return result, {
            "subagent_type": "explore",
            "llm_call_count": llm_call_count,
            "pending_log_keywords": [],
        }

    def _build_log_purification_prompt(
        self,
        query: str,
        task: str,
        keywords: List[str],
        raw_log_output: str,
        expected_output: str,
    ) -> str:
        effective_query = task or query
        if self._is_metric_analysis_query(effective_query):
            return (
                "# 角色设定\n"
                "你是一个极其严谨的性能日志提纯专家，目标是提取可用于画时序曲线的指标样本。\n\n"
                "# 当前任务\n"
                f"用户问题：{query}\n"
                f"子任务：{effective_query}\n"
                f"关键词：{keywords}\n"
                f"期望输出：{expected_output or '(none)'}\n\n"
                "<raw_logs>\n"
                f"{raw_log_output}\n"
                "</raw_logs>\n\n"
                "# 处理指令\n"
                "1. 仅保留与 CPU/负载/利用率/采样时间 相关的行。\n"
                "2. 优先提取形如“时间戳 + 数值”的片段；保留最少必要上下文。\n"
                "3. 如果没有任何可画曲线的样本，必须明确说明“未提取到CPU时序样本”。\n"
                "4. 严禁编造不存在的数据点。\n\n"
                "# 输出格式\n"
                "输出 Markdown，包含 `证据摘要` 与 `时序样本` 两段。"
            )
        return (
            "# 角色设定\n"
            "你是一个极其严谨的日志分析与数据清洗专家。你的唯一目标是从原始日志中提取最致命的报错线索。\n\n"
            "# 当前任务\n"
            f"用户问题：{query}\n"
            f"子任务：{effective_query}\n"
            f"关键词：{keywords}\n"
            f"期望输出：{expected_output or '(none)'}\n\n"
            "<raw_logs>\n"
            f"{raw_log_output}\n"
            "</raw_logs>\n\n"
            "# 处理指令\n"
            "1. 去噪：剔除无意义的 DEBUG/INFO 与健康检查噪音。\n"
            "2. 提取堆栈：优先保留 ERROR、Exception、FATAL、WARN 以及带文件名/行号的栈信息。\n"
            "3. 保留上下文：如果报错前有关键请求体或变量打印，保留最少必要上下文。\n"
            "4. 如实汇报：没有异常时必须明确写“未找到匹配的异常日志”。\n\n"
            "# 输出格式\n"
            "请直接输出提纯后的日志内容（不超过 1000 字）。"
        )

    def _run_log_subagent(
        self,
        task: str,
        expected_output: str,
        keywords: List[Any],
        query: str,
        log_file_path: str,
        trace_id: str,
        llm_call_count: int,
        log_search_attempts: int,
    ) -> Tuple[str, Dict[str, Any]]:
        if not log_file_path:
            result = self._format_subagent_result(
                subagent_type="log",
                task=task or query,
                body="Log subagent error: log_file_path 为空，无法检索生产日志。",
            )
            return result, {"subagent_type": "log", "llm_call_count": llm_call_count}

        normalized_keywords = self._normalize_english_keywords(
            keywords=list(keywords or []),
            query=f"{query}\n{task}",
            limit=8,
        )
        current_attempt = int(log_search_attempts) + 1
        raw_log_output = self._dispatch_log_tool(
            "LogKeywordSearchTool",
            log_file_path=log_file_path,
            keywords=normalized_keywords,
            context_lines=2,
            trace_id=trace_id,
            attempt=current_attempt,
        )
        log_prompt = self._build_log_purification_prompt(
            query=query,
            task=task,
            keywords=normalized_keywords,
            raw_log_output=raw_log_output,
            expected_output=expected_output,
        )

        try:
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self.llm,
                payload=log_prompt,
                trace_id=trace_id,
                call_no=call_no,
                agent_name="log_subagent",
                purpose="log_purification",
            )
            purified_logs = self._message_content(response).strip()
        except Exception as e:
            logger.warning("Log subagent 提纯失败，退化为原始片段: %s", e)
            purified_logs = raw_log_output

        purified_logs = purified_logs or "未找到匹配的异常日志，当前的日志均为常规/正常打印。"
        result_body = purified_logs
        if self._is_no_log_match_result(purified_logs):
            suggested_keywords = self._suggest_next_log_keywords(
                query=task or query,
                used_keywords=normalized_keywords,
            )
            result_body = (
                f"{purified_logs}\n\n"
                f"建议下一轮关键词: {suggested_keywords}\n"
                "若仍无结果，请回到代码侧定位打印点/采样点，再反向构造关键词。"
            )

        result = self._format_subagent_result(
            subagent_type="log",
            task=task or query,
            body=result_body,
            metadata={
                "keywords": ", ".join(normalized_keywords),
                "attempt": current_attempt,
            },
        )
        return result, {
            "subagent_type": "log",
            "purified_logs": purified_logs,
            "pending_log_keywords": [],
            "log_search_attempts": current_attempt,
            "llm_call_count": llm_call_count,
        }

    def _log_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        result_content, extra_state = self._run_log_subagent(
            task=state.get("query", ""),
            expected_output="返回精简后的高信噪比日志证据。",
            keywords=state.get("pending_log_keywords") or [],
            query=state.get("query", ""),
            log_file_path=state.get("log_file_path", ""),
            trace_id=state.get("trace_id", "unknown"),
            llm_call_count=int(state.get("llm_call_count", 0)),
            log_search_attempts=int(state.get("log_search_attempts", 0)),
        )
        msg = SystemMessage(content=result_content, id=self._new_id())
        return {
            "purified_logs": extra_state.get("purified_logs", ""),
            "pending_log_keywords": [],
            "messages": [msg],
            "token_count": int(state.get("token_count", 0)) + self._estimate_tokens_for_message(msg),
            "llm_call_count": int(extra_state.get("llm_call_count", state.get("llm_call_count", 0))),
            "log_search_attempts": int(extra_state.get("log_search_attempts", state.get("log_search_attempts", 0))),
        }

    def _compaction_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        messages = state.get("messages", [])
        mem      = state.get("working_memory", "")
        trace_id = state.get("trace_id", "unknown")
        llm_call_count = int(state.get("llm_call_count", 0))
        summary_prompt = (
            "# 角色设定\n"
            "你是一个负责「信息熵压缩」的记忆整理专家。由于排障过程极为漫长，当前对话上下文的 Token 已经接近熔断阈值，你需要将冗长的对话历史折叠成高度浓缩的「排障备忘录（Working Memory）」。\n\n"
            "# 当前状态\n"
            f"- 旧版本的排障备忘录：{mem}\n"
            "- 最新一轮的冗长对话记录：\n"
            "<recent_messages>\n"
            f"{self._messages_to_text(messages)}\n"
            "</recent_messages>\n\n"
            "# 压缩指令\n"
            "请生成一份全新的、覆盖全局的排障备忘录。你必须遵循 MECE（相互独立、完全穷尽）原则：\n"
            "1. **必须保留的硬核线索**：\n"
            "   - 已尝试过哪些日志搜索关键词（避免重复盲搜）？\n"
            "   - 已用 GrepCodeTool/FindDefinitionTool 确认的代码路径和行号？\n"
            "   - 已用 CloneRepoTool 克隆的仓库路径？\n"
            "   - 已推翻了哪些假设（如：「已确认不是 DB 超时导致」）？\n"
            "2. **必须丢弃的废料**：\n"
            "   - 具体的几十行报错堆栈（只需记录 'XXX文件在YY行报了ZZZ' 即可）。\n"
            "   - Agent 之间的客套话、冗长思考过程、工具调用的 JSON 外壳。\n\n"
            "# 输出格式\n"
            "输出一篇字数极简（通常不超过 500 字）、以 Markdown 列表为主的纯粹备忘录。"
        )

        try:
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self.llm,
                payload=summary_prompt,
                trace_id=trace_id,
                call_no=call_no,
                agent_name="compaction_agent",
                purpose="context_compaction",
            )
            new_summary = self._message_content(response).strip()
        except Exception as e:
            logger.warning("Compaction LLM 失败，退化为截断摘要: %s", e)
            raw = f"{mem}\n{self._messages_to_text(messages)}"
            new_summary = raw[-4000:]
        new_summary = new_summary[:500]

        delete_ops = [RemoveMessage(id=m.id) for m in state["messages"][:-1]]
        return {
            "working_memory": new_summary,
            "messages": delete_ops,
            "token_count": 0,
            "llm_call_count": llm_call_count,
        }

    def _summary_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        raw_root_cause = state.get("raw_root_cause", "").strip()
        trace_id = state.get("trace_id", "unknown")
        llm_call_count = int(state.get("llm_call_count", 0))
        inconclusive = False
        if not raw_root_cause:
            inconclusive = True
            raw_root_cause = "未在循环上限内拿到确凿根因，以下为当前最可信线索。\n" + (
                state.get("working_memory", "") or "暂无可用线索"
            )
        if "未在循环上限内拿到确凿根因" in raw_root_cause:
            inconclusive = True

        if inconclusive:
            logger.info(
                "SUMMARY_GUARDRAIL trace_id=%s mode=inconclusive report_mode=template_fallback llm_calls=%s",
                trace_id,
                llm_call_count,
            )
            report = self._build_inconclusive_report(state=state, raw_root_cause=raw_root_cause)
            return {"final_report": report, "llm_call_count": llm_call_count}

        prompt = (
            "# 角色设定\n"
            "你是一位资深的研发技术总监。请把输入证据整理为《故障复盘与修复报告》。\n\n"
            "# 输入信息\n"
            f"- 触发本次排障的用户原始反馈：{state.get('query', '')}\n"
            f"- Code Agent 提交的硬核技术诊断结果：{raw_root_cause}\n\n"
            "# 撰写要求\n"
            "请使用专业的 Markdown 格式，生成一份结构清晰的报告。语气应保持客观、专业、有建设性。报告必须严格包含以下 4 个部分：\n\n"
            "## 🚨 1. 故障现象摘要\n"
            "- 用一句通俗的话概括用户遇到了什么问题。\n\n"
            "## 🔍 2. 根本原因分析 (Root Cause)\n"
            "- 简明扼要地解释为什么会报错（Why it happened）。\n"
            "- **仅当输入证据明确给出时**才填写：代码文件路径、方法名、行号；若未给出，必须写“未定位到具体文件/方法/行号”。\n\n"
            "## 🛠️ 3. 修复方案 (Resolution)\n"
            "- 针对该 Root Cause 提出具体的代码修改建议。\n"
            "- 请使用 Markdown 代码块给出修复前后的对比或补丁示例。\n\n"
            "## 💡 4. 后续改进建议 (Action Items)\n"
            "- 从架构、日志规范或防御性编程的角度，给出 1-2 条改进建议。\n\n"
            "## 强约束（必须遵守）\n"
            "- 只允许使用输入中出现过的事实。\n"
            "- 严禁虚构编程语言、文件路径、类名、方法名、行号、补丁内容。\n"
            "- 不确定时必须显式写“证据不足”。\n\n"
            "请直接输出 Markdown 报告，无需前言后语。"
        )

        try:
            last_error: Optional[Exception] = None
            response = None
            for attempt in range(1, 4):
                try:
                    call_no = llm_call_count + 1
                    llm_call_count = call_no
                    response = self._invoke_llm_with_trace(
                        llm=self.llm,
                        payload=prompt,
                        trace_id=trace_id,
                        call_no=call_no,
                        agent_name="summary_agent",
                        purpose=f"final_report_generation_attempt_{attempt}",
                    )
                    last_error = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    logger.warning(
                        "Summary Agent LLM 调用失败，第 %d/3 次: error_type=%s error=%r",
                        attempt,
                        type(e).__name__,
                        e,
                    )
                    if attempt < 3:
                        time.sleep(attempt)
            if response is None and last_error is not None:
                raise last_error

            report = self._message_content(response).strip()
        except Exception as e:
            logger.warning("Summary Agent LLM 失败，使用模板兜底: error_type=%s error=%r", type(e).__name__, e)
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

        return {"final_report": report, "llm_call_count": llm_call_count}

    # ─────────────────────── Tool Implementations ──────────────────────────

    def _clone_repo(
        self,
        log_type: str,
        branch: str = "",
        repo_url_override: str = "",
        commit_id: str = "",
        force_refresh: bool = True,
    ) -> Tuple[str, str]:
        """克隆代码仓库到工作区，返回 (workspace_path, result_message)。"""
        normalized = log_type.lower().strip()

        if normalized in _LOG_TYPE_OAM_KEYS:
            configured_repo_url = settings.code_repo_oam_url
            repo_label = "OAM天线"
        elif normalized in _LOG_TYPE_STACK_KEYS:
            configured_repo_url = settings.code_repo_stack_url
            repo_label = "协议栈"
        else:
            return "", (
                f"CloneRepoTool error: 未知的日志类型 '{log_type}'。\n"
                f"可选值：{list(_LOG_TYPE_OAM_KEYS | _LOG_TYPE_STACK_KEYS)}"
            )

        repo_url = (repo_url_override or configured_repo_url or "").strip()
        normalized_branch = self._normalize_branch_name(branch) or ""
        normalized_commit = str(commit_id or "").strip()

        if not repo_url:
            return "", (
                f"CloneRepoTool error: {repo_label}代码仓库 URL 未配置。\n"
                "请在配置文件或环境变量中设置 CODE_REPO_OAM_URL / CODE_REPO_STACK_URL。"
            )

        # 固定路径 + 强制刷新：保证每次分析都是最新干净工作区
        base_dir = Path(settings.base_dir) / settings.code_repo_clone_base_dir
        clone_dir = base_dir / normalized
        base_dir.mkdir(parents=True, exist_ok=True)

        if clone_dir.exists() and force_refresh:
            logger.info(
                "CloneRepoTool: 清理旧工作区后重克隆: %s (log_type=%s branch=%s commit=%s)",
                clone_dir,
                normalized,
                normalized_branch or "(default)",
                normalized_commit or "(none)",
            )
            shutil.rmtree(clone_dir, ignore_errors=True)

        reuse_existing = clone_dir.exists() and (clone_dir / ".git").exists()
        if clone_dir.exists() and not (clone_dir / ".git").exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
            reuse_existing = False

        # 构建带认证的 URL
        auth_url = self._build_auth_url(repo_url)
        depth = max(1, int(settings.code_repo_clone_depth))

        if not reuse_existing:
            cmd = [
                "git", "clone",
                f"--depth={depth}",
                "--single-branch",
            ]
            if normalized_branch:
                cmd.extend(["--branch", normalized_branch])
            cmd.extend([auth_url, str(clone_dir)])

            logger.info(
                "CloneRepoTool: 开始克隆 %s 仓库 -> %s (depth=%d branch=%s)",
                repo_label,
                clone_dir,
                depth,
                normalized_branch or "(default)",
            )

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                return "", "CloneRepoTool error: 克隆超时（超过 5 分钟），请检查网络或仓库大小。"
            except FileNotFoundError:
                return "", "CloneRepoTool error: 系统中未找到 git 命令，请确认 git 已安装。"
            except Exception as exc:
                return "", f"CloneRepoTool error: 克隆失败: {exc}"

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()[:500]
                try:
                    shutil.rmtree(clone_dir, ignore_errors=True)
                except Exception:
                    pass
                return "", f"CloneRepoTool error: git clone 失败（exit={result.returncode}）\n{stderr}"
        else:
            logger.info("CloneRepoTool: 复用已有仓库: %s", clone_dir)

        # 分支/提交对齐：优先 commit，再 fallback 分支
        if normalized_commit:
            checkout_cmd = ["git", "-C", str(clone_dir), "checkout", "--quiet", normalized_commit]
            try:
                checkout_ret = subprocess.run(checkout_cmd, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                return "", f"CloneRepoTool error: checkout commit 超时 '{normalized_commit}'"
            except Exception as exc:
                return "", f"CloneRepoTool error: checkout commit 失败: {exc}"
            if checkout_ret.returncode != 0:
                try:
                    fetch_ret = subprocess.run(
                        ["git", "-C", str(clone_dir), "fetch", "--all", "--tags", "--quiet"],
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                except subprocess.TimeoutExpired:
                    return "", "CloneRepoTool error: git fetch 超时（checkout commit 前置步骤）"
                except Exception as exc:
                    return "", f"CloneRepoTool error: git fetch 失败: {exc}"
                if fetch_ret.returncode != 0:
                    stderr = (fetch_ret.stderr or "").strip()[:500]
                    return "", f"CloneRepoTool error: git fetch 失败（checkout commit 前置步骤）\n{stderr}"
                try:
                    checkout_ret = subprocess.run(checkout_cmd, capture_output=True, text=True, timeout=180)
                except subprocess.TimeoutExpired:
                    return "", f"CloneRepoTool error: checkout commit 超时 '{normalized_commit}'"
                except Exception as exc:
                    return "", f"CloneRepoTool error: checkout commit 失败: {exc}"
                if checkout_ret.returncode != 0:
                    stderr = (checkout_ret.stderr or "").strip()[:500]
                    return "", f"CloneRepoTool error: checkout commit 失败 '{normalized_commit}'\n{stderr}"
        elif normalized_branch and reuse_existing:
            try:
                branch_ret = subprocess.run(
                    ["git", "-C", str(clone_dir), "checkout", "--quiet", normalized_branch],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except subprocess.TimeoutExpired:
                return "", f"CloneRepoTool error: checkout 分支超时 '{normalized_branch}'"
            except Exception as exc:
                return "", f"CloneRepoTool error: checkout 分支失败: {exc}"
            if branch_ret.returncode != 0:
                stderr = (branch_ret.stderr or "").strip()[:500]
                return "", f"CloneRepoTool error: checkout 分支失败 '{normalized_branch}'\n{stderr}"

        logger.info(
            "CloneRepoTool: 仓库就绪 type=%s dir=%s branch=%s commit=%s refreshed=%s",
            repo_label,
            clone_dir,
            normalized_branch or "(default)",
            normalized_commit or "(none)",
            force_refresh,
        )
        return str(clone_dir), (
            f"# 仓库已就绪（{'重克隆' if force_refresh else '复用'}）\n"
            f"- 类型: {repo_label}\n"
            f"- 来源: {repo_url}\n"
            f"- 工作区: {clone_dir}\n"
            f"- 克隆深度: {depth}\n"
            f"- 分支: {normalized_branch or '(远端默认分支)'}\n"
            f"- 提交: {normalized_commit or '(未指定)'}\n"
            "工作区已切换，请使用 GetFileTreeTool 了解代码结构，然后开始分析。"
        )

    def _read_code_snippet(
        self, workspace_dir: str, file_path: str, start_line: int, end_line: int
    ) -> str:
        if not workspace_dir:
            return "ReadCodeTool error: workspace_dir 为空，请先调用 CloneRepoTool 克隆代码仓库。"

        ws, requested, err = self._resolve_workspace_path(workspace_dir, file_path)
        if err:
            return f"ReadCodeTool error: {err}"
        if not requested.exists() or not requested.is_file():
            return f"ReadCodeTool error: 文件不存在: {requested}"

        s = max(1, int(start_line))
        e = max(s, int(end_line))
        if e - s + 1 > 100:
            e = s + 99

        try:
            lines = requested.read_text(encoding="utf-8", errors="ignore").splitlines()
            selected = lines[s - 1: e]
        except Exception as exc:
            return f"ReadCodeTool error: 读取失败: {exc}"

        numbered = "\n".join(f"{i + s:>6} | {line}" for i, line in enumerate(selected))
        rel = requested.relative_to(ws)
        return f"# {rel}:{s}-{e}\n```\n{numbered}\n```"

    def _grep_code(
        self,
        workspace_dir: str,
        pattern: str,
        directory: str,
        file_glob: str,
        context_lines: int,
    ) -> str:
        if not workspace_dir:
            return "GrepCodeTool error: workspace_dir 为空，请先调用 CloneRepoTool。"
        if not pattern:
            return "GrepCodeTool error: pattern 不能为空。"

        ws, search_root, err = self._resolve_workspace_path(workspace_dir, directory or "")
        if err:
            return f"GrepCodeTool error: {err}"
        if not search_root.exists():
            return f"GrepCodeTool error: 目录不存在: {search_root}"

        ctx = max(0, min(int(context_lines), 5))

        if _RG_BIN:
            return self._grep_with_rg(pattern, str(search_root), file_glob, ctx)
        return self._grep_with_python(pattern, str(search_root), file_glob, ctx)

    def _grep_with_rg(
        self, pattern: str, path: str, file_glob: str, context: int
    ) -> str:
        _ = context  # 关键词抽取模式下不返回上下文片段
        cmd = [
            _RG_BIN, "-n", "--no-heading",
            "--max-count=120", "--max-filesize=5M",
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.extend([pattern, path])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, errors="ignore"
            )
            output = (result.stdout or "").strip()
        except subprocess.TimeoutExpired:
            return "GrepCodeTool error: 搜索超时（30s）"
        except Exception as exc:
            return f"GrepCodeTool error: {exc}"

        if not output:
            return f"GrepCodeTool: 未在 {path} 中找到匹配 '{pattern}'"

        lines = [ln for ln in output.splitlines() if ln.strip()]
        fn_names, log_keywords = self._extract_candidate_terms(lines=lines, max_items=24)
        if not fn_names and not log_keywords:
            for token in self._extract_ascii_tokens(pattern):
                t = token.strip()
                if t and t not in fn_names:
                    fn_names.append(t)
                if len(fn_names) >= 5:
                    break
        result = self._format_candidate_result(
            tool_name="GrepCodeTool",
            query_value=pattern,
            function_names=fn_names,
            log_keywords=log_keywords,
        )
        return result[:_MAX_GREP_OUTPUT]

    def _grep_with_python(
        self, pattern: str, path: str, file_glob: str, context: int
    ) -> str:
        """纯 Python 回退实现（当 ripgrep 不可用时）。"""
        _ = context
        try:
            regex = re.compile(pattern, re.MULTILINE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.MULTILINE)

        import fnmatch
        glob_pat = file_glob or "*"
        lines_out: List[str] = []
        match_count = 0

        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not fnmatch.fnmatch(fname, glob_pat):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        file_lines = f.readlines()
                except Exception:
                    continue
                for i, line in enumerate(file_lines):
                    if regex.search(line):
                        rel = os.path.relpath(fpath, path)
                        lines_out.append(f"{rel}:{i + 1}:{line.rstrip()}")
                        match_count += 1
                        if match_count >= 120:
                            fn_names, log_keywords = self._extract_candidate_terms(lines_out, max_items=24)
                            return self._format_candidate_result(
                                tool_name="GrepCodeTool",
                                query_value=pattern,
                                function_names=fn_names,
                                log_keywords=log_keywords,
                            )[:_MAX_GREP_OUTPUT]

        if not lines_out:
            return f"GrepCodeTool: 未在 {path} 中找到匹配 '{pattern}'"

        fn_names, log_keywords = self._extract_candidate_terms(lines=lines_out, max_items=24)
        if not fn_names and not log_keywords:
            for token in self._extract_ascii_tokens(pattern):
                t = token.strip()
                if t and t not in fn_names:
                    fn_names.append(t)
                if len(fn_names) >= 5:
                    break
        return self._format_candidate_result(
            tool_name="GrepCodeTool",
            query_value=pattern,
            function_names=fn_names,
            log_keywords=log_keywords,
        )[:_MAX_GREP_OUTPUT]

    def _glob_code(self, workspace_dir: str, pattern: str, directory: str) -> str:
        if not workspace_dir:
            return "GlobCodeTool error: workspace_dir 为空，请先调用 CloneRepoTool。"
        if not pattern:
            return "GlobCodeTool error: pattern 不能为空。"

        ws, search_root, err = self._resolve_workspace_path(workspace_dir, directory or "")
        if err:
            return f"GlobCodeTool error: {err}"
        if not search_root.exists():
            return f"GlobCodeTool error: 目录不存在: {search_root}"

        if _RG_BIN:
            try:
                cmd = [_RG_BIN, "--files", "--glob", pattern, str(search_root)]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=20, errors="ignore"
                )
                files = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
            except Exception:
                files = []
        else:
            files = [str(p) for p in search_root.rglob(pattern) if p.is_file()]

        if not files:
            return f"GlobCodeTool: 未找到匹配 '{pattern}' 的文件"

        files.sort()
        if len(files) > _MAX_GLOB_FILES:
            truncated = files[:_MAX_GLOB_FILES]
            suffix = f"\n... 仅显示前 {_MAX_GLOB_FILES} 个，共 {len(files)} 个文件匹配"
        else:
            truncated = files
            suffix = ""

        rel_lines = []
        for fp in truncated:
            try:
                rel = os.path.relpath(fp, workspace_dir)
            except ValueError:
                rel = fp
            rel_lines.append(rel)

        return f"# GlobCode: '{pattern}'\n" + "\n".join(rel_lines) + suffix

    def _list_dir(self, workspace_dir: str, directory: str, max_depth: int) -> str:
        if not workspace_dir:
            return "ListDirTool error: workspace_dir 为空，请先调用 CloneRepoTool。"

        ws, target, err = self._resolve_workspace_path(workspace_dir, directory or "")
        if err:
            return f"ListDirTool error: {err}"
        if not target.exists():
            return f"ListDirTool error: 目录不存在: {target}"
        if not target.is_dir():
            return f"ListDirTool error: 路径不是目录: {target}"

        max_d = max(1, min(int(max_depth), 6))
        lines: List[str] = []
        count = 0

        for dirpath, dirnames, filenames in os.walk(str(target)):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            depth = len(Path(dirpath).relative_to(target).parts)
            if depth > max_d:
                dirnames.clear()
                continue

            indent = "  " * depth
            rel_dir = Path(dirpath).relative_to(target)
            if depth == 0:
                lines.append(f"{target.name}/")
            else:
                lines.append(f"{indent}{rel_dir.name}/")

            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                try:
                    size = fpath.stat().st_size
                    size_str = f"  ({size:,} B)" if size < 10240 else f"  ({size // 1024:,} KB)"
                except Exception:
                    size_str = ""
                lines.append(f"{indent}  {fname}{size_str}")
                count += 1
                if count >= _MAX_LIST_ENTRIES:
                    lines.append("  ... (已截断)")
                    return "\n".join(lines)

        if not lines:
            return f"ListDirTool: 目录为空: {target}"
        rel_root = target.relative_to(ws)
        return f"# 目录: {rel_root}\n" + "\n".join(lines)

    def _find_definition(
        self, workspace_dir: str, symbol: str, file_glob: str
    ) -> str:
        if not workspace_dir:
            return "FindDefinitionTool error: workspace_dir 为空，请先调用 CloneRepoTool。"
        if not symbol:
            return "FindDefinitionTool error: symbol 不能为空。"

        ws = Path(workspace_dir).resolve()
        if not ws.exists():
            return f"FindDefinitionTool error: 工作区不存在: {ws}"

        # 构建覆盖 C/C++/Python/Java 等主流语言的定义模式
        esc = re.escape(symbol)
        patterns = [
            # Python: def symbol / class symbol / async def symbol
            rf"(?:def|class|async\s+def)\s+{esc}\s*[:(]",
            # C/C++: 函数定义、类、结构体（字符类中不包含 { 以避免 f-string 解析问题）
            r"(?:void|int|char|bool|auto|static|inline|struct|class|enum)\s+" + esc + r"\s*[(]",
            r"\b" + esc + r"\s*\([^)]*\)\s*\{",
            # C 宏
            rf"#\s*define\s+{esc}\b",
            # Java/Kotlin
            r"(?:public|private|protected|static|final|class|interface|enum)\s+\w*\s*" + esc + r"\s*[(]",
        ]
        combined_pattern = "|".join(f"(?:{p})" for p in patterns)

        if _RG_BIN:
            cmd = [_RG_BIN, "-n", "--no-heading", "-C1", "--max-count=30"]
            if file_glob:
                cmd.extend(["--glob", file_glob])
            cmd.extend([combined_pattern, str(ws)])
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=20, errors="ignore"
                )
                output = (result.stdout or "").strip()
            except Exception as exc:
                output = ""
                logger.debug("FindDefinitionTool rg error: %s", exc)
        else:
            output = self._grep_with_python(combined_pattern, str(ws), file_glob, 1)
            if output.startswith("GrepCodeTool"):
                output = ""

        if not output:
            # 回退：简单字符串搜索（更宽松）
            fallback_pattern = rf"\b{re.escape(symbol)}\b"
            if _RG_BIN:
                cmd = [_RG_BIN, "-n", "--no-heading", "--max-count=20"]
                if file_glob:
                    cmd.extend(["--glob", file_glob])
                cmd.extend([fallback_pattern, str(ws)])
                try:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=15, errors="ignore"
                    )
                    output = (result.stdout or "").strip()
                except Exception:
                    output = ""
            if not output:
                return f"FindDefinitionTool: 未找到符号 '{symbol}' 的定义"
        lines = [ln for ln in (output or "").splitlines() if ln.strip()]
        fn_names, _ = self._extract_candidate_terms(lines=lines, max_items=20)
        if symbol not in fn_names:
            fn_names.insert(0, symbol)
        return self._format_candidate_result(
            tool_name="FindDefinitionTool",
            query_value=symbol,
            function_names=fn_names[:20],
            log_keywords=[],
        )[:_MAX_FIND_OUTPUT]

    def _get_file_tree(
        self, workspace_dir: str, directory: str, max_depth: int
    ) -> str:
        if not workspace_dir:
            return "GetFileTreeTool error: workspace_dir 为空，请先调用 CloneRepoTool。"

        ws, root, err = self._resolve_workspace_path(workspace_dir, directory or "")
        if err:
            return f"GetFileTreeTool error: {err}"
        if not root.exists():
            return f"GetFileTreeTool error: 目录不存在: {root}"

        max_d = max(1, min(int(max_depth), 8))
        lines: List[str] = []
        line_count = 0

        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth > max_d:
                dirnames.clear()
                continue

            indent = "  " * depth
            name = Path(dirpath).name if depth > 0 else root.name
            lines.append(f"{indent}{name}/")

            for fname in sorted(filenames):
                lines.append(f"{indent}  {fname}")
                line_count += 1
                if line_count >= _MAX_TREE_LINES:
                    lines.append(f"{indent}  ... (已截断，文件过多)")
                    rel_root = root.relative_to(ws) if root != ws else Path(".")
                    return f"# 文件树: {rel_root}\n" + "\n".join(lines)

        if not lines:
            return f"GetFileTreeTool: 目录为空: {root}"

        rel_root = root.relative_to(ws) if root != ws else Path(".")
        return f"# 文件树: {rel_root}\n" + "\n".join(lines)

    # ─────────────────────── Prompt Builder ────────────────────────────────

    def _build_code_agent_prompt(
        self,
        query: str,
        workspace_dir: str,
        log_type: str,
        repo_cloned: bool,
        code_tool_invocations: int,
        log_search_attempts: int,
        working_memory: str,
        purified_logs: str,
        supervisor_plan: str,
        supervisor_reflection: str,
        repo_branch: str,
        repo_commit_id: str,
    ) -> str:
        log_type_display = {
            "oam_antenna": "OAM天线模块",
            "oam":         "OAM天线模块",
            "stack":       "协议栈模块",
            "full":        "全量日志（协议栈 + OAM天线）",
        }.get(log_type.lower(), log_type or "未知")

        workspace_info = (
            f"已就绪（路径：{workspace_dir}）" if repo_cloned and workspace_dir
            else "**尚未克隆**，必须先调用 CloneRepoTool"
        )

        return (
            "# 角色设定\n"
            "你是一位拥有 15 年经验的顶级架构师和线上故障排查专家（Senior Principal Engineer）。\n"
            "你的任务是根据用户的故障描述，在隔离的代码沙箱中定位代码级 Root Cause。\n\n"

            "# 当前上下文\n"
            f"- **用户原始故障描述**：{query}\n"
            f"- **日志类型**：{log_type_display}\n"
            f"- **代码工作区**：{workspace_info}\n"
            f"- **已执行代码工具次数**：{code_tool_invocations}\n"
            f"- **日志检索轮次**：{log_search_attempts}\n"
            f"- **Supervisor 计划**：{supervisor_plan or '(暂无)'}\n"
            f"- **Supervisor 反思**：{supervisor_reflection or '(暂无)'}\n"
            f"- **元数据分支提示**：{repo_branch or '(未提供)'}\n"
            f"- **元数据提交提示**：{repo_commit_id or '(未提供)'}\n"
            f"- **历史排障备忘录（必读）**：{working_memory or '(空)'}\n"
            f"- **最新日志取证结果**：{purified_logs or '(暂无)'}\n\n"

            "# 可用工具说明\n"
            "## A. Code 执行工具（仅用于源码操作）\n"
            "| 工具 | 用途 |\n"
            "|------|------|\n"
            "| CloneRepoTool | 按日志类型克隆对应代码仓库，支持 `branch` 且默认强制重克隆 |\n"
            "| GetFileTreeTool | 获取目录树概览，快速理解代码结构 |\n"
            "| GrepCodeTool | 在源码中搜索关键词/正则，类似 ripgrep |\n"
            "| GlobCodeTool | 按 glob 模式查找文件，如 `**/*.h` |\n"
            "| ListDirTool | 列出目录详细内容 |\n"
            "| FindDefinitionTool | 定位函数/类/宏的定义位置 |\n"
            "| ReadCodeTool | 读取指定文件的代码片段（最多 100 行）|\n\n"
            "## B. 协作控制工具（仅用于跨 Agent 协作）\n"
            "| 工具 | 用途 |\n"
            "|------|------|\n"
            "| DelegateSubAgentTool | 参考 opencode TaskTool，委托 `explore` 或 `log` 子代理做聚焦任务，并把结果回传给当前 Code Agent |\n"
            "| SubmitDiagnosisTool | 提交确凿的根因分析，结束排查 |\n\n"

            "## C. 可委托子代理（由 `DelegateSubAgentTool` 触发，不做硬切换）\n"
            "| 子代理 | 擅长问题 |\n"
            "|------|------|\n"
            "| explore | 大范围找文件、按模式扫代码、先帮你缩小候选文件/符号集合 |\n"
            "| log | 根据英文关键词去日志里取证，并回传高信噪比日志证据 |\n\n"

            "# 标准排查工作流\n"
            "**第 0 步 - 克隆代码**（如工作区未就绪）：\n"
            "   调用 `CloneRepoTool(log_type=..., branch=..., force_refresh=true)` 克隆对应仓库。\n\n"
            "**第 1 步 - 代码结构探索**：\n"
            "   小范围问题直接自己调用 `GetFileTreeTool`/`GlobCodeTool`/`GrepCodeTool`；大范围找文件时优先委托 `explore` 子代理。\n\n"
            "**第 2 步 - 日志取证**（当缺乏具体报错线索时）：\n"
            "   把用户问题翻译为英文检索词，并通过 `DelegateSubAgentTool(subagent_type='log', ...)` 委托日志子代理取证。\n\n"
            "**第 3 步 - 代码溯源**：\n"
            "   - 用 `GrepCodeTool` 搜索报错字符串、函数名；\n"
            "   - 用 `FindDefinitionTool` 找到函数/类的定义文件和行号；\n"
            "   - 用 `ReadCodeTool` 精读关键代码逻辑。\n\n"
            "**第 4 步 - 深度推理**：\n"
            "   结合日志证据和源码，推理变量为何为空、条件为何未命中。\n"
            "   若搜索空间过大，可再次委托 `explore` 子代理而不是机械切换到别的顶层节点。\n\n"
            "**第 5 步 - 结案**：\n"
            "   当确信找到具体代码缺陷后，调用 `SubmitDiagnosisTool` 提交分析报告。\n\n"

            "# 纪律约束\n"
            "- **英文检索强制**：`pattern` / `symbol` / `keywords` 必须优先使用英文；中文描述先翻译成英文关键词后再搜索。\n"
            "- **返回约束**：优先让工具结果只包含“函数名”或“日志打印关键词”，避免返回大段源码和整行日志。\n"
            "- **零幻觉原则**：未读取源码前，绝不猜测代码实现逻辑。\n"
            "- **协作约束**：优先把子代理当成可选工具，委托时必须写清楚任务范围和期望回传内容。\n"
            "- **反思机制**：若日志子代理返回「未找到匹配」，换一组更宽泛的关键词再试，最多 3 次。\n"
            "- **输出约束**：禁止输出 `<think>`/`<thinking>` 标签内容。"
        )

    # ─────────────────────── Result Builder ────────────────────────────────

    def _to_structured_result(
        self, final_state: InvestigationState, execution_time: float
    ) -> Dict[str, Any]:
        final_report   = final_state.get("final_report", "")
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
                "title": "Supervisor 总控",
                "description": "负责计划制定、路由调度与每轮反思纠偏",
                "status": "completed" if final_state.get("supervisor_round", 0) else "pending",
            },
            {
                "id": "step_2",
                "title": "Code Agent 推理",
                "description": "克隆代码仓库，利用多种代码工具结合日志证据逐步定位根因",
                "status": "completed",
            },
            {
                "id": "step_3",
                "title": "SubAgent 协作",
                "description": "Code Agent 按需委托 explore/log 子代理取证，再回到主推理链继续分析",
                "status": "completed" if final_state.get("purified_logs") else "pending",
            },
            {
                "id": "step_4",
                "title": "Compaction Agent 压缩",
                "description": "当 token 超阈值时压缩上下文并清理历史消息",
                "status": "completed" if final_state.get("working_memory") else "pending",
            },
            {
                "id": "step_5",
                "title": "Summary Agent 出报告",
                "description": "输出业务友好的故障报告",
                "status": "completed" if final_report else "pending",
            },
        ]

        return {
            "id":        str(uuid.uuid4()),
            "query":     final_state.get("query", ""),
            "status":    "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "plan": {
                "content":         "多智能体流程已执行：Supervisor -> Code/(Explore|Log SubAgents)/(Compaction) -> Summary",
                "steps":           plan_steps,
                "total_steps":     len(plan_steps),
                "completed_steps": sum(1 for s in plan_steps if s["status"] == "completed"),
            },
            "acts": [],
            "final_result": {
                "content":         final_report,
                "summary":         summary,
                "recommendations": recommendations,
                "confidence":      0.9 if raw_root_cause else 0.6,
            },
            "metadata": {
                "execution_time": round(float(execution_time), 3),
                "model_used":     getattr(self.llm, "model_name", "unknown"),
                "tokens_used":    final_state.get("token_count", 0),
                "llm_calls":      final_state.get("llm_call_count", 0),
                "log_search_attempts": final_state.get("log_search_attempts", 0),
                "code_tool_invocations": final_state.get("code_tool_invocations", 0),
                "trace_id":       final_state.get("trace_id", ""),
                "log_type":       final_state.get("log_type", "unknown"),
                "repo_url":       final_state.get("repo_url", ""),
                "repo_branch":    final_state.get("repo_branch", ""),
                "repo_commit_id": final_state.get("repo_commit_id", ""),
                "repo_cloned":    final_state.get("repo_cloned", False),
                "workspace_dir":  final_state.get("workspace_dir", ""),
                "supervisor_round": final_state.get("supervisor_round", 0),
            },
            "graph_state": {
                "raw_root_cause":  raw_root_cause,
                "working_memory":  final_state.get("working_memory", ""),
                "iteration_count": final_state.get("iteration_count", 0),
                "token_count":     final_state.get("token_count", 0),
                "llm_call_count":  final_state.get("llm_call_count", 0),
                "log_search_attempts": final_state.get("log_search_attempts", 0),
                "code_tool_invocations": final_state.get("code_tool_invocations", 0),
                "supervisor_plan": final_state.get("supervisor_plan", ""),
                "supervisor_reflection": final_state.get("supervisor_reflection", ""),
                "supervisor_round": final_state.get("supervisor_round", 0),
                "trace_id":        final_state.get("trace_id", ""),
            },
        }

    # ─────────────────────── Private Helpers ───────────────────────────────

    def _default_next_node(self, state: InvestigationState) -> str:
        if str(state.get("raw_root_cause", "")).strip():
            return "summary_agent"
        if int(state.get("iteration_count", 0)) >= self.max_iterations:
            return "summary_agent"
        if int(state.get("token_count", 0)) > self.token_limit:
            return "compaction_agent"
        return "code_agent"

    def _apply_supervisor_constraints(
        self,
        state: InvestigationState,
        suggested_next: str,
        fallback: str,
    ) -> str:
        allowed = {"code_agent", "compaction_agent", "summary_agent"}
        candidate = suggested_next if suggested_next in allowed else fallback

        if str(state.get("raw_root_cause", "")).strip():
            return "summary_agent"
        if int(state.get("iteration_count", 0)) >= self.max_iterations:
            return "summary_agent"
        if int(state.get("token_count", 0)) > self.token_limit:
            return "compaction_agent"

        workspace_ready = bool(state.get("repo_cloned")) and bool(state.get("workspace_dir"))
        if not workspace_ready:
            return "code_agent"

        if candidate == "summary_agent":
            # 防止 Supervisor LLM 在未满足完成条件时提前收敛到 summary。
            return fallback if fallback in {"code_agent", "compaction_agent"} else "code_agent"
        return candidate

    @staticmethod
    def _extract_json_dict(text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            raw = raw.strip()

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _resolve_workspace_path(
        self, workspace_dir: str, relative_path: str
    ) -> Tuple[Path, Path, str]:
        """将相对路径解析为绝对路径，并执行工作区沙箱安全检查。

        返回 (workspace_root, resolved_path, error_message)；无错误时 error_message 为空。
        """
        ws = Path(workspace_dir).resolve()
        if relative_path:
            candidate = Path(relative_path)
            if candidate.is_absolute():
                resolved = candidate.resolve()
            else:
                resolved = (ws / relative_path).resolve()
        else:
            resolved = ws

        try:
            resolved.relative_to(ws)
        except ValueError:
            return ws, resolved, f"路径越界，禁止访问工作区外路径: {resolved}"

        return ws, resolved, ""

    @staticmethod
    def _build_auth_url(repo_url: str) -> str:
        """将 Git Token 注入到 HTTPS URL 中（如果配置了 token）。"""
        token = settings.code_repo_git_token
        if not token:
            return repo_url
        try:
            parsed = urlparse(repo_url)
            if parsed.scheme in ("http", "https") and not parsed.username:
                authed = parsed._replace(netloc=f"oauth2:{token}@{parsed.hostname}" + (
                    f":{parsed.port}" if parsed.port else ""
                ))
                return urlunparse(authed)
        except Exception:
            pass
        return repo_url

    @staticmethod
    def _normalize_branch_name(value: str) -> str:
        branch = str(value or "").strip()
        if not branch:
            return ""
        low = branch.lower()
        if low in {"head", "origin/head", "refs/head"}:
            return ""
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]
        if branch.startswith("origin/"):
            branch = branch[len("origin/"):]
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", branch):
            return ""
        if len(branch) > 128:
            return ""
        if re.search(r"\s", branch):
            return ""
        if not re.fullmatch(r"[A-Za-z0-9._/\-]+", branch):
            return ""
        return branch

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _safe_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return int(default)

    @staticmethod
    def _safe_bool(v: Any, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            lv = v.strip().lower()
            if lv in {"1", "true", "yes", "y", "on"}:
                return True
            if lv in {"0", "false", "no", "n", "off"}:
                return False
        return bool(default)

    def _invoke_llm_with_trace(
        self,
        llm: Any,
        payload: Any,
        trace_id: str,
        call_no: int,
        agent_name: str,
        purpose: str,
    ) -> Any:
        """统一封装 LLM 调用日志，便于将 HTTP 200 与业务轮次一一对应。"""
        model_name = getattr(llm, "model_name", getattr(self.llm, "model_name", "unknown"))
        payload_summary = self._summarize_payload(payload)
        payload_full = self._format_payload_for_log(payload)
        logger.info(
            "LLM_CALL_START trace_id=%s call_no=%d agent=%s purpose=%s model=%s payload=%s",
            trace_id,
            call_no,
            agent_name,
            purpose,
            model_name,
            payload_summary,
        )
        logger.info(
            "LLM_CALL_INPUT_FULL trace_id=%s call_no=%d agent=%s payload=\n======\n%s\n======",
            trace_id,
            call_no,
            agent_name,
            payload_full,
        )
        started_at = time.time()
        try:
            response = llm.invoke(payload)
            elapsed_ms = int((time.time() - started_at) * 1000)
            response_text = self._message_content(response)
            response_text_sanitized = self._strip_thinking_blocks(response_text).strip()
            tool_calls = []
            if isinstance(response, BaseMessage):
                tool_calls = self._extract_tool_calls(response)
            tool_names = [str(tc.get("name")) for tc in tool_calls if isinstance(tc, dict) and tc.get("name")]
            logger.info(
                "LLM_CALL_END trace_id=%s call_no=%d agent=%s elapsed_ms=%d output_chars=%d tool_calls=%d tool_names=%s output=%s",
                trace_id,
                call_no,
                agent_name,
                elapsed_ms,
                len(response_text_sanitized or ""),
                len(tool_names),
                tool_names if tool_names else [],
                response_text_sanitized,
            )
            logger.info(
                "LLM_CALL_OUTPUT_FULL trace_id=%s call_no=%d agent=%s output=\n++++++\n%s\n++++++",
                trace_id,
                call_no,
                agent_name,
                response_text_sanitized,
            )
            return response
        except Exception as exc:
            elapsed_ms = int((time.time() - started_at) * 1000)
            logger.warning(
                "LLM_CALL_ERROR trace_id=%s call_no=%d agent=%s elapsed_ms=%d error_type=%s error=%r",
                trace_id,
                call_no,
                agent_name,
                elapsed_ms,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise

    def _summarize_payload(self, payload: Any) -> str:
        if isinstance(payload, str):
            return (
                f"type=text chars={len(payload)} preview="
                f"{self._truncate_for_log(payload, max_len=260)}"
            )

        if isinstance(payload, list):
            message_parts: List[str] = []
            total_chars = 0
            for idx, msg in enumerate(payload[-6:], start=1):
                role = getattr(msg, "type", msg.__class__.__name__)
                content = self._message_content(msg)
                msg_chars = len(content)
                total_chars += msg_chars
                message_parts.append(f"{idx}:{role}[{msg_chars}]")
            return (
                f"type=messages count={len(payload)} total_chars={total_chars} "
                f"tail_roles={','.join(message_parts)}"
            )

        text = self._message_content(payload)
        return (
            f"type={type(payload).__name__} chars={len(text)} "
            f"preview={self._truncate_for_log(text, max_len=220)}"
        )

    def _format_payload_for_log(self, payload: Any) -> str:
        """输出用于审计的完整 payload 文本（移除 thinking 内容）。"""
        if isinstance(payload, str):
            return self._strip_thinking_blocks(payload)

        if isinstance(payload, list):
            lines: List[str] = []
            for idx, msg in enumerate(payload, start=1):
                role = getattr(msg, "type", msg.__class__.__name__)
                content = self._strip_thinking_blocks(self._message_content(msg))
                lines.append(f"[{idx}] role={role}\n{content}")
            return "\n\n".join(lines)

        return self._strip_thinking_blocks(self._message_content(payload))

    @staticmethod
    def _strip_thinking_blocks(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE)
        return cleaned

    @staticmethod
    def _truncate_for_log(text: Any, max_len: int = 240) -> str:
        value = str(text or "").replace("\n", "\\n").replace("\r", "\\r")
        if len(value) <= max_len:
            return value
        return value[: max_len - 3] + "..."

    def _summarize_tool_result_for_log(self, tool_name: str, result_content: Any) -> str:
        text = str(result_content or "")
        if tool_name != "GetFileTreeTool":
            return self._truncate_for_log(text, max_len=_MAX_TOOL_LOG_CHARS)

        lines = text.splitlines()
        keep = _FILE_TREE_LOG_HEAD_LINES + _FILE_TREE_LOG_TAIL_LINES
        if len(lines) <= keep + 1:
            return self._truncate_for_log(text, max_len=_MAX_TOOL_LOG_CHARS)

        head = lines[:_FILE_TREE_LOG_HEAD_LINES]
        tail = lines[-_FILE_TREE_LOG_TAIL_LINES:]
        omitted = len(lines) - len(head) - len(tail)
        summary = "\n".join([*head, f"... (日志省略 {omitted} 行)", *tail])
        return self._truncate_for_log(summary, max_len=_MAX_TOOL_LOG_CHARS)

    def _normalize_ai_message(self, response: Any) -> AIMessage:
        if isinstance(response, AIMessage):
            msg = response
        else:
            msg = AIMessage(content=self._message_content(response), id=self._new_id())

        cleaned_content = self._strip_thinking_blocks(self._message_content(msg)).strip()
        if cleaned_content != self._message_content(msg):
            msg = msg.model_copy(update={"content": cleaned_content})

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
            parsed.append({
                "id":   item.get("id") or self._new_id(),
                "name": fn.get("name"),
                "args": self._coerce_args(fn.get("arguments")),
            })
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

    @staticmethod
    def _extract_ascii_tokens(text: str) -> List[str]:
        if not text:
            return []
        return re.findall(r"[A-Za-z][A-Za-z0-9_]{1,63}", text)

    def _normalize_english_keywords(self, keywords: List[Any], query: str, limit: int = 8) -> List[str]:
        """标准化日志检索关键词：优先英文 token，缺失时从用户描述推断英文关键词。"""
        normalized: List[str] = []
        seen = set()
        for raw in keywords:
            for token in self._extract_ascii_tokens(str(raw or "")):
                tk = token.strip().lower()
                if not tk or tk in seen:
                    continue
                seen.add(tk)
                normalized.append(tk)
                if len(normalized) >= limit:
                    return normalized

        if len(normalized) < limit:
            for token in self._derive_english_keywords_from_text(query):
                tk = token.strip().lower()
                if not tk or tk in seen:
                    continue
                seen.add(tk)
                normalized.append(tk)
                if len(normalized) >= limit:
                    break
        return normalized

    def _derive_english_keywords_from_text(self, text: str) -> List[str]:
        """从用户问题中提炼英文检索词，兼容中英混输场景。"""
        candidates: List[str] = []
        for token in self._extract_ascii_tokens(text):
            tk = token.lower()
            if tk not in candidates:
                candidates.append(tk)

        zh_map = {
            "超时": "timeout",
            "失败": "failed",
            "异常": "exception",
            "报错": "error",
            "错误": "error",
            "空指针": "null",
            "崩溃": "crash",
            "重启": "restart",
            "升级": "upgrade",
            "下载": "download",
            "上传": "upload",
            "连接": "connect",
            "网络": "network",
            "内存": "memory",
            "磁盘": "disk",
            "线程": "thread",
            "死锁": "deadlock",
            "卡死": "hang",
            "性能": "performance",
            "告警": "alarm",
            "cpu": "cpu",
        }
        lowered = str(text or "").lower()
        for zh, en in zh_map.items():
            if zh in lowered and en not in candidates:
                candidates.append(en)

        if not candidates:
            candidates = ["error", "exception", "failed", "timeout", "null", "crash"]
        return candidates[:12]

    @staticmethod
    def _extract_candidate_terms(lines: List[str], max_items: int = 20) -> Tuple[List[str], List[str]]:
        """从搜索命中行提取函数名和日志关键词。"""
        function_names: List[str] = []
        log_keywords: List[str] = []
        fn_seen = set()
        kw_seen = set()

        fn_stop = {
            "if", "for", "while", "switch", "return", "sizeof", "catch", "throw",
            "new", "delete", "case", "else", "do", "try", "finally", "class", "def",
            "async", "log", "printf", "print", "logger",
        }
        kw_stop = {
            "info", "debug", "warn", "warning", "error", "failed", "failure",
            "start", "stop", "success", "value", "message",
        }

        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^[^:]+:\d+:(.*)$", line)
            code = (m.group(1) if m else line).strip()
            if not code:
                continue

            for p in (
                r"\b(?:def|async\s+def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
                r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            ):
                for hit in re.findall(p, code):
                    name = str(hit).strip()
                    low = name.lower()
                    if not name or low in fn_stop or low in fn_seen:
                        continue
                    fn_seen.add(low)
                    function_names.append(name)
                    if len(function_names) >= max_items:
                        break
                if len(function_names) >= max_items:
                    break

            quoted = re.findall(r"['\"]([^'\"]{3,120})['\"]", code)
            for seg in quoted:
                for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,63}", seg):
                    low = token.lower()
                    if low in kw_stop or low in kw_seen:
                        continue
                    kw_seen.add(low)
                    log_keywords.append(low)
                    if len(log_keywords) >= max_items:
                        break
                if len(log_keywords) >= max_items:
                    break

            if len(function_names) >= max_items and len(log_keywords) >= max_items:
                break

        return function_names[:max_items], log_keywords[:max_items]

    @staticmethod
    def _format_candidate_result(tool_name: str, query_value: str, function_names: List[str], log_keywords: List[str]) -> str:
        """统一格式化：仅返回函数名或日志关键词。"""
        if not function_names and not log_keywords:
            return f"{tool_name}: 未提取到函数名或日志关键词 (query={query_value})"
        fn_text = ", ".join(function_names) if function_names else "(none)"
        kw_text = ", ".join(log_keywords) if log_keywords else "(none)"
        return (
            f"{tool_name} candidates ({query_value})\n"
            f"function_names: {fn_text}\n"
            f"log_keywords: {kw_text}"
        )

    def _estimate_tokens_for_message(self, msg: BaseMessage) -> int:
        return self._estimate_tokens(self._message_content(msg))

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        ascii_chars = sum(1 for c in text if c.isascii())
        non_ascii   = max(0, len(text) - ascii_chars)
        return max(1, int(non_ascii + ascii_chars * 0.3))

    def _messages_to_text(self, messages: List[BaseMessage]) -> str:
        chunks: List[str] = []
        for m in messages:
            role = getattr(m, "type", m.__class__.__name__)
            chunks.append(f"[{role}] {self._message_content(m)}")
        return "\n\n".join(chunks)

    def _has_code_evidence(self, state: InvestigationState) -> bool:
        if int(state.get("code_tool_invocations", 0)) > 0:
            return True
        for m in state.get("messages", []):
            if not isinstance(m, ToolMessage):
                continue
            if getattr(m, "name", "") in _CODE_EVIDENCE_TOOLS:
                return True
        return False

    @staticmethod
    def _is_metric_analysis_query(query: str) -> bool:
        q = (query or "").lower()
        markers = (
            "cpu",
            "利用率",
            "曲线",
            "趋势",
            "performance",
            "load",
            "usage",
            "指标",
            "时序",
        )
        return any(m in q for m in markers)

    @staticmethod
    def _is_no_log_match_result(text: str) -> bool:
        value = (text or "").strip().lower()
        if not value:
            return True
        return any(marker in value for marker in _NO_LOG_MATCH_MARKERS)

    def _suggest_next_log_keywords(self, query: str, used_keywords: List[str]) -> List[str]:
        used = {str(k).strip().lower() for k in used_keywords if str(k).strip()}
        base_keywords = [
            "cpu", "CPU", "cpu_usage", "cpuUsage", "util", "utilization",
            "load", "top", "idle", "busy", "/proc/stat", "sched", "thread",
            "tick", "percent", "usage", "process", "system_resource",
        ]
        if "温度" in (query or ""):
            base_keywords.extend(["temperature", "temp"])
        candidates = [k for k in base_keywords if k.lower() not in used]
        return candidates[:8]

    def _build_inconclusive_report(self, state: InvestigationState, raw_root_cause: str) -> str:
        query = state.get("query", "")
        purified_logs = state.get("purified_logs", "") or "暂无日志提纯证据"
        memory = state.get("working_memory", "") or "暂无工作记忆"
        log_attempts = int(state.get("log_search_attempts", 0))
        code_invocations = int(state.get("code_tool_invocations", 0))

        return (
            "# 故障复盘与修复报告\n\n"
            "## 🚨 1. 故障现象摘要\n"
            f"- 用户诉求：{query}\n"
            "- 本轮分析已完成代码与日志联合检索，但当前证据不足以得出唯一根因。\n\n"
            "## 🔍 2. 根本原因分析 (Root Cause)\n"
            "- 结论：**未定位到确凿 Root Cause（证据不足）**。\n"
            f"- 日志检索轮次：{log_attempts}；代码工具调用次数：{code_invocations}。\n"
            "- 具体代码文件路径/方法名/行号：**未定位到具体文件/方法/行号**。\n"
            f"- 当前最可信线索：\n{raw_root_cause}\n\n"
            "## 🛠️ 3. 修复方案 (Resolution)\n"
            "- 当前阶段不建议提交“定点修复补丁”，避免误修。\n"
            "- 建议先补采样证据后再进入代码修复：\n"
            "```text\n"
            "1) 在目标进程开启 CPU 周期采样日志（含 timestamp + process/thread + usage%）\n"
            "2) 对照生命周期关键阶段（启动/运行/回收）打点\n"
            "3) 用新增样本反向定位到具体函数与行号后再提交修复\n"
            "```\n\n"
            "## 💡 4. 后续改进建议 (Action Items)\n"
            f"- 最近一次日志提纯结果：{purified_logs}\n"
            f"- 当前工作记忆摘要：{memory}\n"
            "- 为性能问题建立标准化取证模板：指标名、采样周期、时间窗口、阈值、模块维度。"
        )
