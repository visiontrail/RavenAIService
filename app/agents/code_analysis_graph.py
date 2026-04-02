"""四维多智能体日志+代码联合分析图。"""

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

# 日志类型 -> 仓库 URL 的映射键
_LOG_TYPE_OAM_KEYS   = {"oam", "oam_antenna"}
_LOG_TYPE_STACK_KEYS = {"stack", "full"}


# ─────────────────────────────── 状态 ─────────────────────────────────────

class InvestigationState(TypedDict):
    # --- 基础上下文 ---
    query: str
    workspace_dir: str
    log_file_path: str
    log_type: str        # "oam_antenna" | "stack" | "full" | "unknown"
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

    # --- 结果产出 ---
    raw_root_cause: str
    final_report: str


# ─────────────────────────────── 主图 ─────────────────────────────────────

class CodeAnalysisGraph:
    """四维智能体编排：Code -> Log/Compaction -> Summary。"""

    def __init__(self, token_limit: int = 8000, max_iterations: int = 10):
        if StateGraph is None or END is None:
            raise RuntimeError("langgraph 不可用，无法初始化 CodeAnalysisGraph")

        self.token_limit = int(token_limit)
        self.max_iterations = int(max_iterations)
        self.llm = get_llm()
        self._tools = self._build_code_tools()

        try:
            self._llm_with_tools = self.llm.bind_tools(self._tools)
        except Exception as e:
            logger.warning(
                "bind_tools 失败，Code Agent 将退化为无工具模式: llm_class=%s error_type=%s error=%r",
                type(self.llm).__name__,
                type(e).__name__,
                e,
                exc_info=True,
            )
            self._llm_with_tools = self.llm

        graph = StateGraph(InvestigationState)
        graph.add_node("code_agent", self._code_agent_node)
        graph.add_node("log_agent", self._log_agent_node)
        graph.add_node("compaction_agent", self._compaction_agent_node)
        graph.add_node("summary_agent", self._summary_agent_node)

        graph.set_entry_point("code_agent")
        graph.add_conditional_edges(
            "code_agent",
            self._route_after_code,
            {
                "code_agent": "code_agent",
                "log_agent": "log_agent",
                "summary_agent": "summary_agent",
            },
        )
        graph.add_conditional_edges(
            "log_agent",
            self._route_after_log,
            {
                "code_agent": "code_agent",
                "compaction_agent": "compaction_agent",
            },
        )
        graph.add_edge("compaction_agent", "code_agent")
        graph.add_edge("summary_agent", END)

        self._app = graph.compile()

    # ─────────────────────── Public API ────────────────────────────────────

    def run(
        self,
        query: str,
        workspace_dir: str,
        log_file_path: str,
        log_type: str = "unknown",
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
            "repo_cloned": bool(workspace_dir),
            "trace_id": runtime_trace_id,
            "llm_call_count": 0,
            "messages": [HumanMessage(content=query, id=self._new_id())],
            "working_memory": "",
            "token_count": 0,
            "iteration_count": 0,
            "pending_log_keywords": [],
            "purified_logs": "",
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

    # ─────────────────────── Routing ───────────────────────────────────────

    def _route_after_log(self, state: InvestigationState) -> str:
        if state["token_count"] > self.token_limit:
            return "compaction_agent"
        return "code_agent"

    def _route_after_code(self, state: InvestigationState) -> str:
        if state["iteration_count"] >= self.max_iterations:
            return "summary_agent"

        last_msg = state["messages"][-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            tool_name = last_msg.tool_calls[0]["name"]
            if tool_name == "AskLogAgentTool":
                return "log_agent"
            elif tool_name == "SubmitDiagnosisTool":
                return "summary_agent"

        return "code_agent"

    # ────────────────────── Tool Definitions ───────────────────────────────

    def _build_code_tools(self) -> List[StructuredTool]:
        """构建所有代码分析工具（仅用于 bind_tools；实际执行在 _dispatch_tool 中）。"""

        def clone_repo_tool(log_type: str) -> str:
            """根据日志类型将对应的代码仓库克隆到临时工作区，并切换当前工作区路径。

            log_type 可选: 'oam_antenna'（OAM天线模块）或 'stack'（协议栈模块）。
            必须在使用任何代码阅读/搜索工具之前调用，否则工作区为空。
            """
            return f"已请求克隆仓库: log_type={log_type}"

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
            """
            return f"已请求查找符号定义: symbol={symbol}"

        def get_file_tree_tool(directory: str = "", max_depth: int = 3) -> str:
            """获取工作区目录树的概览视图，帮助快速理解代码结构。

            自动忽略 .git、node_modules、__pycache__ 等噪音目录。
            directory: 起始子目录（空则从工作区根目录开始）。
            max_depth: 最大显示深度（默认 3）。
            """
            return f"已请求获取文件树: directory={directory}"

        def ask_log_agent_tool(keywords: List[str]) -> str:
            """当不确定代码何处报错时，提供关键词组合，让日志专家去生产日志中取证。"""
            return f"日志关键词已提交: {keywords}"

        def submit_diagnosis_tool(root_cause_analysis: str) -> str:
            """当通过源码找到了确凿的缺陷后，调用此工具提交技术分析报告并结束排查。"""
            return f"已提交根因分析: {root_cause_analysis[:120]}"

        return [
            StructuredTool.from_function(clone_repo_tool,      name="CloneRepoTool"),
            StructuredTool.from_function(read_code_tool,       name="ReadCodeTool"),
            StructuredTool.from_function(grep_code_tool,       name="GrepCodeTool"),
            StructuredTool.from_function(glob_code_tool,       name="GlobCodeTool"),
            StructuredTool.from_function(list_dir_tool,        name="ListDirTool"),
            StructuredTool.from_function(find_definition_tool, name="FindDefinitionTool"),
            StructuredTool.from_function(get_file_tree_tool,   name="GetFileTreeTool"),
            StructuredTool.from_function(ask_log_agent_tool,   name="AskLogAgentTool"),
            StructuredTool.from_function(submit_diagnosis_tool, name="SubmitDiagnosisTool"),
        ]

    # ─────────────────────── Agent Nodes ───────────────────────────────────

    def _code_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        workspace_dir = state.get("workspace_dir", "")
        log_type      = state.get("log_type", "unknown")
        repo_cloned   = state.get("repo_cloned", False)
        trace_id      = state.get("trace_id", "unknown")

        sys_prompt = self._build_code_agent_prompt(
            query         = state.get("query", ""),
            workspace_dir = workspace_dir,
            log_type      = log_type,
            repo_cloned   = repo_cloned,
            working_memory = state.get("working_memory", ""),
            purified_logs  = state.get("purified_logs", ""),
        )

        prompt_messages: List[BaseMessage] = [
            SystemMessage(content=sys_prompt, id=self._new_id()),
            *state.get("messages", []),
        ]

        call_no = int(state.get("llm_call_count", 0)) + 1
        response = self._invoke_llm_with_trace(
            llm=self._llm_with_tools,
            payload=prompt_messages,
            trace_id=trace_id,
            call_no=call_no,
            agent_name="code_agent",
            purpose="reasoning_and_tool_selection",
        )
        response = self._normalize_ai_message(response)

        token_delta = self._estimate_tokens_for_message(response)
        updates: Dict[str, Any] = {
            "messages": [response],
            "iteration_count": int(state.get("iteration_count", 0)) + 1,
            "token_count": int(state.get("token_count", 0)) + token_delta,
            "llm_call_count": call_no,
        }

        tool_calls = self._extract_tool_calls(response)
        if not tool_calls:
            return updates

        first_call = tool_calls[0]
        tool_name  = first_call.get("name")
        args       = self._coerce_args(first_call.get("args"))
        call_id    = str(first_call.get("id") or self._new_id())

        # ── 不产生 ToolMessage 的控制流工具 ──
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

        # ── 执行工具并产生 ToolMessage ──
        logger.info(
            "TOOL_CALL trace_id=%s iter=%s tool=%s args=%s",
            trace_id,
            updates.get("iteration_count", 0),
            tool_name or "unknown",
            self._truncate_for_log(json.dumps(args, ensure_ascii=False, sort_keys=True), max_len=800),
        )
        result_content, extra_state = self._dispatch_tool(
            tool_name     = tool_name,
            args          = args,
            workspace_dir = workspace_dir,
            log_type      = log_type,
        )

        tool_msg = ToolMessage(
            content      = result_content,
            tool_call_id = call_id,
            name         = tool_name or "UnknownTool",
            id           = self._new_id(),
        )
        updates["messages"].append(tool_msg)
        updates["token_count"] = int(updates["token_count"]) + self._estimate_tokens(result_content)
        updates.update(extra_state)
        logger.info(
            "TOOL_RESULT trace_id=%s iter=%s tool=%s result_chars=%d extra_state_keys=%s preview=%s",
            trace_id,
            updates.get("iteration_count", 0),
            tool_name or "unknown",
            len(result_content or ""),
            ",".join(sorted(extra_state.keys())) if extra_state else "(none)",
            self._truncate_for_log(result_content, max_len=280),
        )
        return updates

    def _dispatch_tool(
        self,
        tool_name: Optional[str],
        args: Dict[str, Any],
        workspace_dir: str,
        log_type: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """执行工具并返回 (result_text, extra_state_updates)。"""
        extra: Dict[str, Any] = {}

        if tool_name == "CloneRepoTool":
            requested_type = str(args.get("log_type", log_type) or log_type).lower().strip()
            new_workspace, msg = self._clone_repo(requested_type)
            if new_workspace:
                extra["workspace_dir"] = new_workspace
                extra["repo_cloned"]   = True
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

        return f"未知工具: {tool_name}", extra

    def _log_agent_node(self, state: InvestigationState) -> Dict[str, Any]:
        keywords     = state.get("pending_log_keywords") or []
        log_file_path = state.get("log_file_path", "")
        trace_id = state.get("trace_id", "unknown")
        llm_call_count = int(state.get("llm_call_count", 0))

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
            "请将上述原始日志提纯为一份高信噪比的「日志化验报告」。你必须遵循以下原则：\n"
            "1. **去噪**：剔除毫无意义的 DEBUG/INFO 日志，忽略健康检查（Health Check）等噪音。\n"
            "2. **提取堆栈**：精准保留包含 ERROR、Exception、FATAL、WARN 的那几行，特别是带有【具体代码文件名和行号】的调用栈（Stack Trace）。\n"
            "3. **保留上下文**：如果报错前紧挨着有 HTTP 请求体或关键变量打印，必须保留，这往往是诱因。\n"
            "4. **如实汇报**：如果日志中确实没有任何报错信息，请直接输出：「未找到匹配的异常日志，当前的日志均为常规/正常打印。」绝不要伪造报错。\n\n"
            "# 输出格式\n"
            "请直接输出提纯后的日志内容（不超过 1000 字），不需要任何寒暄或解释。"
        )

        try:
            call_no = llm_call_count + 1
            llm_call_count = call_no
            response = self._invoke_llm_with_trace(
                llm=self.llm,
                payload=log_prompt,
                trace_id=trace_id,
                call_no=call_no,
                agent_name="log_agent",
                purpose="log_purification",
            )
            purified_logs = self._message_content(response).strip()
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
            "purified_logs":        purified_logs,
            "pending_log_keywords": [],
            "messages":             [msg],
            "token_count":          token_after,
            "llm_call_count":       llm_call_count,
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
            "- 用一句通俗的话概括用户遇到了什么问题。\n\n"
            "## 🔍 2. 根本原因分析 (Root Cause)\n"
            "- 简明扼要地解释为什么会报错（Why it happened）。\n"
            "- **必须明确指出**：存在缺陷的具体代码文件路径、引发异常的方法名及行号。\n\n"
            "## 🛠️ 3. 修复方案 (Resolution)\n"
            "- 针对该 Root Cause 提出具体的代码修改建议。\n"
            "- 请使用 Markdown 代码块给出修复前后的对比或补丁示例。\n\n"
            "## 💡 4. 后续改进建议 (Action Items)\n"
            "- 从架构、日志规范或防御性编程的角度，给出 1-2 条改进建议。\n\n"
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

    def _clone_repo(self, log_type: str) -> Tuple[str, str]:
        """克隆代码仓库到临时工作区，返回 (workspace_path, result_message)。"""
        normalized = log_type.lower().strip()

        if normalized in _LOG_TYPE_OAM_KEYS:
            repo_url = settings.code_repo_oam_url
            repo_label = "OAM天线"
        elif normalized in _LOG_TYPE_STACK_KEYS:
            repo_url = settings.code_repo_stack_url
            repo_label = "协议栈"
        else:
            return "", (
                f"CloneRepoTool error: 未知的日志类型 '{log_type}'。\n"
                f"可选值：{list(_LOG_TYPE_OAM_KEYS | _LOG_TYPE_STACK_KEYS)}"
            )

        if not repo_url:
            return "", (
                f"CloneRepoTool error: {repo_label}代码仓库 URL 未配置。\n"
                "请在配置文件或环境变量中设置 CODE_REPO_OAM_URL / CODE_REPO_STACK_URL。"
            )

        # 确定本地克隆目标路径
        base_dir = Path(settings.base_dir) / settings.code_repo_clone_base_dir
        clone_dir = base_dir / normalized
        clone_dir.mkdir(parents=True, exist_ok=True)

        # 如果已存在有效的 git 仓库则跳过克隆
        if (clone_dir / ".git").exists():
            logger.info("CloneRepoTool: 仓库已存在，跳过克隆: %s", clone_dir)
            return str(clone_dir), (
                f"# 仓库已就绪（已跳过克隆）\n"
                f"- 类型: {repo_label}\n"
                f"- 工作区: {clone_dir}\n"
                "已切换工作区到上述路径，可直接使用代码搜索工具。"
            )

        # 构建带认证的 URL
        auth_url = self._build_auth_url(repo_url)
        depth = max(1, int(settings.code_repo_clone_depth))

        cmd = [
            "git", "clone",
            f"--depth={depth}",
            "--single-branch",
            auth_url,
            str(clone_dir),
        ]

        logger.info(
            "CloneRepoTool: 开始克隆 %s 仓库 -> %s (depth=%d)",
            repo_label, clone_dir, depth,
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
            # 清理可能创建的空目录
            try:
                if clone_dir.exists() and not any(clone_dir.iterdir()):
                    clone_dir.rmdir()
            except Exception:
                pass
            return "", f"CloneRepoTool error: git clone 失败（exit={result.returncode}）\n{stderr}"

        logger.info("CloneRepoTool: 克隆成功: %s -> %s", repo_label, clone_dir)
        return str(clone_dir), (
            f"# 仓库克隆成功\n"
            f"- 类型: {repo_label}\n"
            f"- 来源: {repo_url}\n"
            f"- 工作区: {clone_dir}\n"
            f"- 克隆深度: {depth}\n"
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
        cmd = [
            _RG_BIN, "-n", "--no-heading", f"-C{context}",
            "--max-count=50", "--max-filesize=5M",
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
        header = f"# GrepCode: '{pattern}'" + (f"  glob={file_glob}" if file_glob else "")
        return f"{header}\n{output}"[:_MAX_GREP_OUTPUT]

    def _grep_with_python(
        self, pattern: str, path: str, file_glob: str, context: int
    ) -> str:
        """纯 Python 回退实现（当 ripgrep 不可用时）。"""
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
                        start = max(0, i - context)
                        end   = min(len(file_lines), i + context + 1)
                        lines_out.append(f"# {rel}:{i + 1}")
                        for j in range(start, end):
                            prefix = ">" if j == i else " "
                            lines_out.append(f"{j + 1:>6}{prefix}| {file_lines[j].rstrip()}")
                        lines_out.append("")
                        match_count += 1
                        if match_count >= 50:
                            lines_out.append("(已达到 50 条匹配上限)")
                            return "\n".join(lines_out)[:_MAX_GREP_OUTPUT]

        if not lines_out:
            return f"GrepCodeTool: 未在 {path} 中找到匹配 '{pattern}'"
        return "\n".join(lines_out)[:_MAX_GREP_OUTPUT]

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
            if output.startswith("GrepCodeTool:"):
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

        return f"# FindDefinition: '{symbol}'\n{output}"[:_MAX_FIND_OUTPUT]

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
        working_memory: str,
        purified_logs: str,
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
            f"- **历史排障备忘录（必读）**：{working_memory or '(空)'}\n"
            f"- **最新日志取证结果**：{purified_logs or '(暂无)'}\n\n"

            "# 可用工具说明\n"
            "| 工具 | 用途 |\n"
            "|------|------|\n"
            "| CloneRepoTool | 按日志类型克隆对应代码仓库，**必须首先调用** |\n"
            "| GetFileTreeTool | 获取目录树概览，快速理解代码结构 |\n"
            "| GrepCodeTool | 在源码中搜索关键词/正则，类似 ripgrep |\n"
            "| GlobCodeTool | 按 glob 模式查找文件，如 `**/*.h` |\n"
            "| ListDirTool | 列出目录详细内容 |\n"
            "| FindDefinitionTool | 定位函数/类/宏的定义位置 |\n"
            "| ReadCodeTool | 读取指定文件的代码片段（最多 100 行）|\n"
            "| AskLogAgentTool | 提供关键词，让日志专家从生产日志取证 |\n"
            "| SubmitDiagnosisTool | 提交确凿的根因分析，结束排查 |\n\n"

            "# 标准排查工作流\n"
            "**第 0 步 - 克隆代码**（如工作区未就绪）：\n"
            "   调用 `CloneRepoTool(log_type=...)` 克隆对应仓库。\n\n"
            "**第 1 步 - 代码结构探索**：\n"
            "   调用 `GetFileTreeTool` 了解模块划分；如有报错文件路径，直接跳到第 3 步。\n\n"
            "**第 2 步 - 日志取证**（当缺乏具体报错线索时）：\n"
            "   调用 `AskLogAgentTool` 提交关键词组合，取回精简报错堆栈。\n\n"
            "**第 3 步 - 代码溯源**：\n"
            "   - 用 `GrepCodeTool` 搜索报错字符串、函数名；\n"
            "   - 用 `FindDefinitionTool` 找到函数/类的定义文件和行号；\n"
            "   - 用 `ReadCodeTool` 精读关键代码逻辑。\n\n"
            "**第 4 步 - 深度推理**：\n"
            "   结合日志证据和源码，推理变量为何为空、条件为何未命中。\n"
            "   如需追踪调用链，继续使用 `GrepCodeTool`/`FindDefinitionTool`/`ReadCodeTool`。\n\n"
            "**第 5 步 - 结案**：\n"
            "   当确信找到具体代码缺陷后，调用 `SubmitDiagnosisTool` 提交分析报告。\n\n"

            "# 纪律约束\n"
            "- **零幻觉原则**：未读取源码前，绝不猜测代码实现逻辑。\n"
            "- **反思机制**：若日志专家返回「未找到匹配」，换一组更宽泛的关键词再试，最多 3 次。\n"
            "- **每步先思考**：输出 <thinking>...</thinking> 后再输出工具调用。"
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
                "title": "Code Agent 推理",
                "description": "克隆代码仓库，利用多种代码工具结合日志证据逐步定位根因",
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
            "id":        str(uuid.uuid4()),
            "query":     final_state.get("query", ""),
            "status":    "completed",
            "timestamp": datetime.utcnow().isoformat(),
            "plan": {
                "content":         "四维智能体流程已执行：Code -> Log -> (Compaction) -> Summary",
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
                "trace_id":       final_state.get("trace_id", ""),
                "log_type":       final_state.get("log_type", "unknown"),
                "repo_cloned":    final_state.get("repo_cloned", False),
                "workspace_dir":  final_state.get("workspace_dir", ""),
            },
            "graph_state": {
                "raw_root_cause":  raw_root_cause,
                "working_memory":  final_state.get("working_memory", ""),
                "iteration_count": final_state.get("iteration_count", 0),
                "token_count":     final_state.get("token_count", 0),
                "llm_call_count":  final_state.get("llm_call_count", 0),
                "trace_id":        final_state.get("trace_id", ""),
            },
        }

    # ─────────────────────── Private Helpers ───────────────────────────────

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
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _safe_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return int(default)

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
        logger.info(
            "LLM_CALL_START trace_id=%s call_no=%d agent=%s purpose=%s model=%s payload=%s",
            trace_id,
            call_no,
            agent_name,
            purpose,
            model_name,
            payload_summary,
        )
        started_at = time.time()
        try:
            response = llm.invoke(payload)
            elapsed_ms = int((time.time() - started_at) * 1000)
            response_text = self._message_content(response)
            tool_calls = []
            if isinstance(response, BaseMessage):
                tool_calls = self._extract_tool_calls(response)
            tool_names = [str(tc.get("name")) for tc in tool_calls if isinstance(tc, dict) and tc.get("name")]
            logger.info(
                "LLM_CALL_END trace_id=%s call_no=%d agent=%s elapsed_ms=%d output_chars=%d tool_calls=%d tool_names=%s output_preview=%s",
                trace_id,
                call_no,
                agent_name,
                elapsed_ms,
                len(response_text or ""),
                len(tool_names),
                tool_names if tool_names else [],
                self._truncate_for_log(response_text, max_len=300),
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

    @staticmethod
    def _truncate_for_log(text: Any, max_len: int = 240) -> str:
        value = str(text or "").replace("\n", "\\n").replace("\r", "\\r")
        if len(value) <= max_len:
            return value
        return value[: max_len - 3] + "..."

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
