"""
LangChain/LangGraph-based Log Analysis Agent with ReAct-style loop.

Key changes in this refactor:
- LangGraph StateGraph orchestrates plan -> act -> loop until done
- Planning still produces XML <plan><step>...</step></plan> for compatibility
- Tools execution routes to existing grep/metadata/fs/search helpers and emits XML
- Short-term memory kept (compatible), plus outputs compression to summary
- Backward-compatible API: LogAnalysisAgent.plan(), LogAnalysisAgent.run(), demo_agent_run()
"""
from typing import Any, Dict, List, Optional, TypedDict
import os
import re
import json
import logging
import shutil

# Optional LangChain imports (gracefully degrade if unavailable)
try:
    from langchain_community.chat_models import ChatOpenAI  # type: ignore
except Exception:
    ChatOpenAI = None

try:
    from langchain.prompts import PromptTemplate  # type: ignore
except Exception:
    PromptTemplate = None

try:
    from langgraph.graph import StateGraph, END  # type: ignore
except Exception:
    StateGraph = None
    END = None

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    from langchain_core.tools import tool as lc_tool  # type: ignore
except Exception:
    lc_tool = None
try:
    from langchain.tools import StructuredTool as LCStructuredTool  # type: ignore
except Exception:
    LCStructuredTool = None

logger = logging.getLogger(__name__)

from app.config import settings

def _make_chat_openai(api_key: str, base_url: str, model: str):
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_BASE"] = base_url
    try:
        logger.debug(f"Initializing ChatOpenAI client: base_url={base_url}, model={model}")
        return ChatOpenAI(model=model, temperature=settings.llm_temperature)
    except Exception as e:
        logger.warning(f"ChatOpenAI init failed: base_url={base_url}, model={model}, error={e}")
        return None
from app.agents.xml_utils import wrap_plan, wrap_document
from app.tools.metadata_tool import get_log_package_metadata_xml
from app.tools.grep_tool import grep_file_xml
from app.tools.fs_tools import read_head_xml, read_tail_xml
from app.tools.search_backend import RegexSearchBackend, ElasticSearchBackend, search_to_xml
from app.tools.archive_tool import auto_extract_archive_xml, list_tree_xml, nested_archives_xml, extract_nested_archive_xml




def get_llm() -> Any:
    """Return an LLM client with runtime fallback: deepseek → qwen.
    - Provider 'auto' tries deepseek first, then qwen.
    - Provider 'deepseek' uses deepseek config, falls back to qwen if network/API failure at call time.
    - Provider 'qwen' uses qwen config directly.
    """
    logger.debug(f"get_llm: provider={getattr(settings, 'llm_provider', 'auto')}")
    # If ChatOpenAI class unavailable, error out and return None
    if not ChatOpenAI:
        logger.error("get_llm: ChatOpenAI unavailable")
        return None

    def make_chat_openai(api_key: str, base_url: str, model: str):
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_API_BASE"] = base_url
        try:
            logger.debug(f"Initializing ChatOpenAI client: base_url={base_url}, model={model}")
            return ChatOpenAI(model=model, temperature=settings.llm_temperature)
        except Exception as e:
            logger.warning(f"ChatOpenAI init failed: base_url={base_url}, model={model}, error={e}")
            return None

    # 封装一个具有运行时回退能力的LLM包装器：调用失败时自动切换到Qwen
    class _FallbackLLM:
        def __init__(self, primary_conf: Dict[str, str], fallback_conf: Optional[Dict[str, str]], temperature: float):
            self.temperature = temperature
            self._primary_conf = primary_conf
            self._fallback_conf = fallback_conf
            self._primary = make_chat_openai(primary_conf.get("api_key", ""), primary_conf.get("base_url", ""), primary_conf.get("model", ""))
            self._fallback = None

        def invoke(self, prompt: str):
            # 尝试主模型（DeepSeek）
            if self._primary:
                try:
                    logger.debug("FallbackLLM.invoke: using primary model")
                    return self._primary.invoke(prompt)
                except Exception as e:
                    logger.warning(f"Primary model invocation failed, switching to fallback: {e}")
                    # 出现HTTP错误（如404/502/超时等）时切换到备选（Qwen）
                    pass
            # 构建并尝试备选模型（Qwen）
            if self._fallback_conf and not self._fallback:
                logger.debug("FallbackLLM.invoke: building fallback model")
                self._fallback = make_chat_openai(
                    self._fallback_conf.get("api_key", ""),
                    self._fallback_conf.get("base_url", ""),
                    self._fallback_conf.get("model", "")
                )
            if self._fallback:
                try:
                    logger.debug("FallbackLLM.invoke: using fallback model")
                    return self._fallback.invoke(prompt)
                except Exception as e:
                    logger.warning(f"Fallback model invocation failed: {e}")
            # 无可用后端，抛出运行时异常以避免使用模拟LLM
            logger.error("FallbackLLM.invoke: no available backend after retry")
            raise RuntimeError("No available LLM backend; invocation failed")

        def bind_tools(self, tools: List[Any]):
            return _BoundFallbackLLM(self._primary, self._fallback_conf, tools)

    # Helper: try deepseek, then qwen (初始化阶段)
    def try_deepseek_first_then_qwen():
        # Try DeepSeek
        if getattr(settings, "deepseek_api_key", None) and getattr(settings, "deepseek_base_url", None):
            llm = make_chat_openai(settings.deepseek_api_key, settings.deepseek_base_url, settings.llm_model_name)
            if llm:
                return llm
        # Fallback to Qwen
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            if llm:
                return llm
        return None

    # Provider routing
    provider = getattr(settings, "llm_provider", "auto")
    if provider == "auto":
        # 优先返回具有运行时回退能力的DeepSeek→Qwen包装器
        if getattr(settings, "deepseek_api_key", None) and getattr(settings, "deepseek_base_url", None):
            primary = {
                "api_key": settings.deepseek_api_key,
                "base_url": settings.deepseek_base_url,
                "model": settings.llm_model_name,
            }
            fallback = None
            if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
                fallback = {
                    "api_key": settings.qwen_api_key,
                    "base_url": settings.qwen_base_url,
                    "model": getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"),
                }
            return _FallbackLLM(primary, fallback, settings.llm_temperature)
        # 若DeepSeek未配置，尝试直接Qwen
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            return llm
        return None

    if provider == "deepseek":
        # 始终使用运行时回退包装器：DeepSeek失败时自动切换到Qwen
        primary = {
            "api_key": getattr(settings, "deepseek_api_key", ""),
            "base_url": getattr(settings, "deepseek_base_url", ""),
            "model": getattr(settings, "llm_model_name", "deepseek-v3.1-chat"),
        }
        fallback = None
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            fallback = {
                "api_key": settings.qwen_api_key,
                "base_url": settings.qwen_base_url,
                "model": getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"),
            }
        return _FallbackLLM(primary, fallback, settings.llm_temperature)

    if provider == "qwen":
        if getattr(settings, "qwen_api_key", None) and getattr(settings, "qwen_base_url", None):
            llm = make_chat_openai(settings.qwen_api_key, settings.qwen_base_url, getattr(settings, "qwen_model_name", "qwen-plus-2025-09-11"))
            if llm:
                return llm
        # fallback if qwen missing
        return None

    # OpenAI direct (kept for compatibility)
    if provider == "openai" and getattr(settings, "openai_api_key", None):
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        try:
            return ChatOpenAI(model=settings.llm_model_name, temperature=settings.llm_temperature)
        except Exception:
            return None

    # Final fallback
    return None


class ShortTermMemory:
    def __init__(self, window: int = 5):
        self.window = window
        self._messages: List[Dict[str, str]] = []
        self._summaries: List[str] = []

    def add_message(self, role: str, content: str):
        self._messages.append({"role": role, "content": content})
        self._messages = self._messages[-self.window :]

    def add_summary(self, xml_summary: str):
        self._summaries.append(xml_summary)
        self._summaries = self._summaries[-self.window :]

    def context(self) -> str:
        msgs = "".join([wrap_document(m["content"], {"role": m["role"]}) for m in self._messages])
        sums = "".join(self._summaries)
        return f"<short_term_memory>{msgs}{sums}</short_term_memory>"


def _resolve_prompts_config_path() -> str:
    app_dir = os.path.dirname(os.path.dirname(__file__))  # app/
    project_root = os.path.dirname(app_dir)
    default_path = os.path.join(app_dir, "prompts", "prompts_config.yaml")
    path = getattr(settings, "prompts_config_path", default_path)
    if not os.path.isabs(path):
        # 统一以项目根目录为基准解析相对路径，避免出现 app/app 重复
        path = os.path.join(project_root, os.path.normpath(path))
    return path

def _load_prompts_config() -> Dict[str, Dict[str, Any]]:
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE:
        return _PROMPTS_CACHE
    cfg_path = _resolve_prompts_config_path()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            if cfg_path.lower().endswith((".yaml", ".yml")):
                if yaml:
                    _PROMPTS_CACHE = yaml.safe_load(f) or {}
                else:
                    raise RuntimeError("YAML库未安装，无法解析prompts_config.yaml")
            else:
                _PROMPTS_CACHE = json.load(f)
    except Exception as e:
        # 在异常时记录日志，便于定位问题
        logger.warning("加载提示词配置失败，使用内置回退。路径=%s，错误=%s", cfg_path, e)
        # 内置回退模板，确保功能不受影响
        _PROMPTS_CACHE = {
            "plan_prompt": {
                "template": (
                    "你是一个日志分析Agent，需要制定执行计划。"
                    "输出使用<plan><step>...</step></plan>的XML结构。"
                    "根据用户需求选择：提取元数据、grep检索、全文检索、读取片段。\n\n"
                    "{memory_context}<用户需求>{user_query}</用户需求>"
                ),
                "description": "内置回退：生成执行计划的模板"
            },
            "summary_prompt": {
                "template": (
                    "请对以下日志片段进行简要总结，突出ERROR/WARN及关键事件。\n\n"
                    "<片段>{compact_snippet}</片段>"
                ),
                "description": "内置回退：日志片段摘要模板"
            },
        }
    return _PROMPTS_CACHE

def render_prompt(key: str, **kwargs: Any) -> str:
    conf = _load_prompts_config().get(key, {})
    template_str = conf.get("template", "")
    if not template_str:
        return ""
    if PromptTemplate:
        try:
            pt = _PROMPT_TEMPLATES_CACHE.get(key)
            if not pt:
                input_vars = conf.get("variables") or list(kwargs.keys())
                pt = PromptTemplate(input_variables=input_vars, template=template_str)
                _PROMPT_TEMPLATES_CACHE[key] = pt
            return pt.format(**kwargs)
        except Exception:
            return template_str.format(**kwargs)
    else:
        return template_str.format(**kwargs)

def compress_outputs(outputs: List[str]) -> str:
    """Compression: extractive truncation + optional LLM summary."""
    n = min(3, len(outputs)) or 1
    compact = "".join(o[: settings.agent_max_snippet_bytes // n] for o in outputs[:n])
    llm = get_llm()
    try:
        prompt = render_prompt("summary_prompt", compact_snippet=compact)
        prompt_to_log = prompt[:600] + ("..." if len(prompt) > 600 else "")
        logger.info("\n\n--- START LLM PROMPT [summary] ---\n%s\n--- END LLM PROMPT [summary] ---\n", prompt_to_log)
        if hasattr(llm, "predict"):
            summary_xml = llm.predict(prompt)
            logger.info("\n\n--- START LLM OUTPUT [summary] ---\n%s\n--- END LLM OUTPUT [summary] ---\n", summary_xml)
            return f"<context_summary>{summary_xml}</context_summary>"
        else:
            res = llm.invoke(prompt)
            logger.info("\n\n--- START LLM OUTPUT [summary] ---\n%s\n--- END LLM OUTPUT [summary] ---\n", str(res))
            return wrap_document(str(res), {"type": "summary"})
    except Exception:
        return wrap_document("摘要不可用（降级为提取片段）", {"type": "summary"})


class AgentState(TypedDict):
    query: str
    hints: Optional[Dict[str, Any]]
    plan_xml: str
    steps: List[str]
    idx: int
    outputs: List[str]
    done: bool


class LogAnalysisAgent:
    """Main Agent orchestrating planning and tool execution via LangGraph."""
    def __init__(self):
        self.llm = get_llm()
        logger.info("LogAnalysisAgent.__init__: llm=%s", type(self.llm).__name__)
        self.memory = ShortTermMemory(window=settings.agent_short_term_window)
        self.search_backend = (
            ElasticSearchBackend(url=settings.elasticsearch_url)
            if settings.agent_search_backend == "elasticsearch"
            else RegexSearchBackend(root=settings.agent_root_dir)
        )
        logger.info("LogAnalysisAgent.__init__: backend=%s", type(self.search_backend).__name__)
        self._extracted_dirs: List[str] = []
        try:
            paths: List[str] = []
            logger.debug("Search indexing start: root=%s", settings.agent_root_dir)
            for d, _, files in os.walk(settings.agent_root_dir):
                for f in files:
                    paths.append(os.path.join(d, f))
                if len(paths) > 5000:
                    logger.warning("Indexing truncated at 5000 files to limit scope")
                    break
            self.search_backend.index(paths)
            logger.info("Search indexing done: files=%d", len(paths))
        except Exception as e:
            logger.warning("Search indexing failed: %s", e)

        # Build LangGraph (compact ReAct-style loop)
        if StateGraph:
            graph = StateGraph(AgentState)
            graph.add_node("plan", self._plan_node)
            graph.add_node("act", self._act_node)
            graph.add_edge("plan", "act")
            graph.add_conditional_edges("act", self._should_continue)
            graph.set_entry_point("plan")
            self._app = graph.compile()
        else:
            self._app = None  # Fallback: run() will degrade to sequential execution

    def _build_langchain_tools(self, hints: Optional[Dict[str, Any]]) -> List[Any]:
        if LCStructuredTool is None:
            logger.debug("_build_langchain_tools: LCStructuredTool missing, return empty")
            return []
        tools: List[Any] = []
        hints = hints or {}

        def _metadata_extract(archive_path: Optional[str] = None) -> str:
            path = archive_path or hints.get("archive_path") or settings.agent_root_dir
            try:
                return get_log_package_metadata_xml(path)
            except Exception as e:
                return wrap_document(f"metadata_extract error: {e}", {"tool": "metadata_extract"})

        def _grep_search(path: str, pattern: str, context: int = 2) -> str:
            try:
                return grep_file_xml(path, pattern, context=context)
            except Exception as e:
                return wrap_document(f"grep_search error: {e}", {"tool": "grep_search"})

        def _read_snippet(path: str, head_lines: int = 50, tail_lines: int = 0) -> str:
            try:
                if head_lines and head_lines > 0:
                    return read_head_xml(path, n_lines=head_lines)
                if tail_lines and tail_lines > 0:
                    return read_tail_xml(path, n_lines=tail_lines)
                return read_head_xml(path, n_lines=50)
            except Exception as e:
                return wrap_document(f"read_snippet error: {e}", {"tool": "read_snippet"})

        def _list_tree(root: Optional[str] = None, max_depth: int = 2) -> str:
            try:
                return list_tree_xml(root or settings.agent_root_dir, max_depth=max_depth)
            except Exception as e:
                return wrap_document(f"list_tree error: {e}", {"tool": "list_tree"})

        def _nested_extract(nested_path: Optional[str] = None, extracted_root: Optional[str] = None) -> str:
            r = extracted_root or settings.agent_root_dir
            try:
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=r)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    return xml
                return nested_archives_xml(r)
            except Exception as e:
                return wrap_document(f"nested_extract error: {e}", {"tool": "nested_extract"})

        def _global_search(query: str, k: int = 10) -> str:
            try:
                return search_to_xml(self.search_backend, query=query, k=k)
            except Exception as e:
                return wrap_document(f"global_search error: {e}", {"tool": "global_search"})

        tools.append(LCStructuredTool.from_function(_metadata_extract, name="metadata_extract", description="提取日志包元数据（tar.gz/zip）"))
        tools.append(LCStructuredTool.from_function(_grep_search, name="grep_search", description="在文本文件中执行模式搜索 (grep)"))
        tools.append(LCStructuredTool.from_function(_read_snippet, name="read_snippet", description="读取文件片段 (head/tail)"))
        tools.append(LCStructuredTool.from_function(_nested_extract, name="nested_extract", description="解压或扫描嵌套归档"))
        tools.append(LCStructuredTool.from_function(_list_tree, name="list_tree", description="列出目录树结构"))
        tools.append(LCStructuredTool.from_function(_global_search, name="global_search", description="使用搜索后转为XML"))
        return tools

    def _plan_node(self, state: AgentState) -> AgentState:
        """Graph node that generates plan XML and step list."""
        query = state.get("query", "")
        plan_xml = self.plan(query)
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        return {"plan_xml": plan_xml, "steps": steps}

    def _first_text_file(self) -> Optional[str]:
        for d, _, files in os.walk(settings.agent_root_dir):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found: %s', p)
                    return p
        logger.debug('First text file not found under root=%s', settings.agent_root_dir)
        return None

    def _first_text_file_under(self, root: str) -> Optional[str]:
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found under %s: %s', root, p)
                    return p
        logger.debug('First text file not found under root=%s', root)
        return None

    # Backward-compatible plan() API
    def plan(self, query: str) -> str:
        logger.info("Plan: start query='%s'", query[:200])
        prompt = render_prompt(
            "plan_prompt",
            memory_context=self.memory.context(),
            user_query=query,
        )
        logger.debug("Plan: prompt chars=%d", len(prompt))
        logger.info("\n\n--- START LLM PROMPT [plan] ---\n%s\n--- END LLM PROMPT [plan] ---\n", prompt)
        plan_xml: str = ""
        try:
            logger.debug("Plan: llm=%s", type(self.llm).__name__)
            if hasattr(self.llm, "predict"):
                plan_xml = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    plan_xml = response.content
                else:
                    plan_xml = str(response)
        except Exception as e:
            logger.warning("Plan LLM failed, using fallback: %s", e)
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        logger.info("\n\n--- START LLM OUTPUT [plan] ---\n%s\n--- END LLM OUTPUT [plan] ---\n", plan_xml)
        # Normalize: ensure XML structure
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        if not steps:
            logger.debug("Plan: no <step> found, using fallback plan")
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        self.memory.add_message("user", query)
        self.memory.add_message("system", plan_xml)
        logger.info("Plan: steps=%d", len(re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)))
        return plan_xml

    # Tool routing (XML-producing, refactored)
    def _execute_step(self, step: str, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        logger.info("Execute step (refactored): %s", step)
        hints = hints or {}

        # Attempt function calling via llm.bind_tools
        try:
            tools_bound = self._build_langchain_tools(hints)
            if tools_bound and hasattr(self.llm, "bind_tools"):
                tool_map = {t.name: t for t in tools_bound}
                bound_llm = self.llm.bind_tools(tools_bound)
                # 增加日志：记录绑定工具的名称
                try:
                    logger.info("bind_tools: tools=%s", [getattr(t, "name", str(t)) for t in tools_bound])
                except Exception:
                    logger.info("bind_tools: tools bound (names unavailable)")
                fc_prompt = (
                    "你是一个日志分析Agent的工具路由器。\n"
                    "请基于提供的step、query、hints选择并调用一个工具，使用函数调用（function calling）。\n"
                    "不要输出普通文本，必须返回一个工具调用。\n"
                    f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
                )
                # 增加日志：记录发送给绑定LLM的提示词
                logger.info("\n\n--- START LLM PROMPT [tools_fc] ---\n%s\n--- END LLM PROMPT [tools_fc] ---\n", fc_prompt)
                resp = bound_llm.invoke(fc_prompt)
                tool_calls = getattr(resp, "tool_calls", None)
                if not tool_calls and hasattr(resp, "additional_kwargs"):
                    tool_calls = resp.additional_kwargs.get("tool_calls")
                # 增加日志：记录返回的工具调用
                try:
                    logger.info("bind_tools: tool_calls=%s", tool_calls)
                except Exception:
                    pass
                if tool_calls:
                    tc = tool_calls[0]
                    tname = tc.get("name") or tc.get("tool")
                    targs = tc.get("args") or {}
                    if isinstance(targs, list) and len(targs) == 1 and isinstance(targs[0], dict):
                        targs = targs[0]
                    if tname in tool_map:
                        logger.info("bind_tools selected '%s' with args=%s", tname, targs)
                        try:
                            return tool_map[tname].invoke(targs)
                        except Exception as e:
                            logger.warning("Tool '%s' execution via bind_tools failed: %s", tname, e)
        except Exception as e:
            logger.warning("bind_tools route failed, fallback to manual selection: %s", e)

        tool_specs: Dict[str, Dict[str, Any]] = {
            "metadata_extract": {
                "desc": "提取日志包元数据（tar.gz/zip）",
                "schema": {"archive_path": "str"},
            },
            "grep_search": {
                "desc": "在文本文件中执行模式搜索 (grep)",
                "schema": {"path": "str?", "pattern": "str", "context": "int?"},
            },
            "read_snippet": {
                "desc": "读取文件片段 (head/tail)",
                "schema": {"path": "str?", "head_lines": "int?", "tail_lines": "int?"},
            },
            "nested_extract": {
                "desc": "解压或扫描嵌套归档",
                "schema": {"nested_path": "str?", "extracted_root": "str?"},
            },
            "list_tree": {
                "desc": "列出目录树结构",
                "schema": {"root": "str?", "max_depth": "int?"},
            },
            "global_search": {
                "desc": "使用搜索后转为XML",
                "schema": {"query": "str", "k": "int?"},
            },
        }

        def _extract_json_candidate(s: str) -> Optional[Dict[str, Any]]:
            try:
                s = s.strip()
                if s.startswith("{") and s.endswith("}"):
                    return json.loads(s)
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(s[start : end + 1])
            except Exception:
                return None
            return None

        def _fallback_select(step_text: str) -> Dict[str, Any]:
            st = step_text.lower()
            if ("元数据" in st) or ("metadata" in st):
                return {"tool": "metadata_extract", "args": {}}
            if ("grep" in st) or ("查找" in st) or ("搜索" in st):
                return {"tool": "grep_search", "args": {}}
            if ("读取" in st) or ("片段" in st) or ("head" in st) or ("tail" in st):
                return {"tool": "read_snippet", "args": {}}
            if ("解压" in st) or ("extract" in st) or ("decompress" in st):
                return {"tool": "nested_extract", "args": {}}
            if ("树" in st) or ("tree" in st) or ("结构" in st) or ("list" in st):
                return {"tool": "list_tree", "args": {}}
            return {"tool": "global_search", "args": {}}

        selection: Dict[str, Any] = {}
        try:
            tools_text = "\n".join([f"- {name}: {spec['desc']} schema={spec['schema']}" for name, spec in tool_specs.items()])
            prompt = (
                "你是一个日志分析Agent的工具路由器。\n"
                "基于提供的step、query、hints，从下列工具中选择最合适的一个，并给出JSON参数：\n"
                f"{tools_text}\n\n"
                "返回严格的JSON对象，不要包含解释或多余文字。格式：{\"tool\": \"<name>\", \"args\": { ... }}\n"
                f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
            )
            # 记录手动选择提示词
            logger.info("\n\n--- START LLM PROMPT [tool_select] ---\n%s\n--- END LLM PROMPT [tool_select] ---\n", prompt)
            if hasattr(self.llm, "predict"):
                raw = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    raw = response.content
                else:
                    raw = str(response)
            # 记录手动选择返回内容
            logger.info("\n\n--- START LLM OUTPUT [tool_select] ---\n%s\n--- END LLM OUTPUT [tool_select] ---\n", raw)
            cand = _extract_json_candidate(raw)
            if not cand:
                raise ValueError("LLM未返回可解析的JSON")
            selection = cand
        except Exception as e:
            logger.warning("Tool selection via LLM failed, using fallback: %s", e)
            selection = _fallback_select(step)

        name = str(selection.get("tool", "")).strip()
        args: Dict[str, Any] = selection.get("args", {}) if isinstance(selection.get("args", {}), dict) else {}
        if name not in tool_specs:
            logger.warning("Unknown tool '%s', fallback to global_search", name)
            name = "global_search"

        try:
            if name == "metadata_extract":
                hint_arch = hints.get("archive_path")
                hint_path = hints.get("path")
                ap = args.get("archive_path")
                path = ap or hint_arch or (
                    hint_path if isinstance(hint_path, str) and hint_path.lower().endswith((".tar.gz", ".tgz", ".zip")) else None
                ) or os.path.join(settings.agent_root_dir, "logs.tar.gz")
                logger.info("ToolCall metadata_extract: path=%s", path)
                return get_log_package_metadata_xml(path)

            if name == "grep_search":
                pattern = args.get("pattern") or hints.get("pattern") or query
                path = args.get("path") or hints.get("path") or self._first_text_file()
                context = int(args.get("context") or 2)
                logger.info(
                    "ToolCall grep_search: path=%s pattern=%s context=%d max_matches=%s max_bytes=%s",
                    path,
                    pattern,
                    context,
                    getattr(settings, "agent_max_matches", None),
                    getattr(settings, "agent_max_snippet_bytes", None),
                )
                if not path:
                    return wrap_document("未找到可搜索的文本文件", {"step": step})
                return grep_file_xml(path, pattern, context=context)

            if name == "read_snippet":
                path = args.get("path") or hints.get("path") or self._first_text_file()
                head_n = int(args.get("head_lines") or 50)
                tail_n = int(args.get("tail_lines") or 50)
                logger.info("ToolCall read_snippet: path=%s head_lines=%d tail_lines=%d", path, head_n, tail_n)
                if not path:
                    return wrap_document("未找到可读取的文本文件", {"step": step})
                head = read_head_xml(path, n_lines=head_n)
                tail = read_tail_xml(path, n_lines=tail_n)
                return f"<reads>{head}{tail}</reads>"

            if name == "nested_extract":
                nested_path = args.get("nested_path") or hints.get("nested_path")
                root = args.get("extracted_root") or hints.get("extracted_root") or settings.agent_root_dir
                logger.info("ToolCall nested_extract: nested_path=%s root=%s", nested_path, root)
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=root)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    logger.info("ToolCall nested_extract: extracted_dir=%s", dest)
                    return xml
                else:
                    return nested_archives_xml(root)

            if name == "list_tree":
                root = args.get("root") or hints.get("extracted_root") or settings.agent_root_dir
                max_depth = int(args.get("max_depth") or 2)
                logger.info("ToolCall list_tree: root=%s max_depth=%d", root, max_depth)
                return list_tree_xml(root, max_depth=max_depth)

            if name == "global_search":
                k = int(args.get("k") or 10)
                logger.info("ToolCall global_search: backend=%s query=%s k=%d", type(self.search_backend).__name__, query, k)
                return search_to_xml(self.search_backend, query=query, k=k)

            logger.warning("Unhandled tool '%s', fallback to global_search", name)
            return search_to_xml(self.search_backend, query=query, k=10)
        except Exception as e:
            logger.warning("Tool '%s' execution failed: %s", name, e)
            label = {
                "metadata_extract": "元数据提取失败",
                "grep_search": "grep失败",
                "read_snippet": "读取失败",
                "nested_extract": "解压/扫描嵌套归档失败",
                "list_tree": "树结构生成失败",
                "global_search": "搜索失败",
            }.get(name, "工具执行失败")
            return wrap_document(f"{label}: {e}", {"step": step})

    # Graph node: act
    def _act_node(self, state: AgentState) -> AgentState:
        steps = state["steps"]
        idx = state.get("idx", 0)
        logger.info("Act: idx=%d/%d", idx, len(steps))
        if idx >= len(steps):
            logger.debug("Act: completed all steps")
            return {"done": True}
        step = steps[idx]
        out = self._execute_step(step, state["query"], hints=state.get("hints"))
        logger.debug("Act: output chars=%d", len(out))
        self.memory.add_summary(out)
        # Generate and print per-act LLM thought
        try:
            step_thought = compress_outputs([out])
            logger.info("\n\n--- START LLM THOUGHT [after_act] ---\n%s\n--- END LLM THOUGHT [after_act] ---\n", step_thought)
        except Exception as e:
            logger.warning("Act: step thought generation failed: %s", e)
        outputs = state.get("outputs", []) + [out]
        return {"outputs": outputs, "idx": idx + 1}

    # Graph edge condition
    def _should_continue(self, state: AgentState):
        idx = state.get("idx", 0)
        steps = state.get("steps", [])
        decision = "act" if idx < len(steps) else "end"
        logger.debug("Continue? idx=%d steps=%d decision=%s", idx, len(steps), decision)
        if idx < len(steps):
            return "act"
        return END

    def run(self, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        """Run the agent end-to-end using LangGraph when available; fallback sequential otherwise."""
        logger.info("Run: start query='%s'", query)
        hints_local: Dict[str, Any] = dict(hints or {})
        logger.debug("Run: hints=%s", hints_local)
        pre_outputs: List[str] = []
        final_doc: str = ""
        try:
            # 自动解压流程：如果提供了归档路径，则先解压并输出树结构
            archive_path = hints_local.get("archive_path") or (hints_local.get("path") if isinstance(hints_local.get("path"), str) and hints_local.get("path").lower().endswith((".tar.gz", ".tgz", ".zip")) else None)
            if archive_path:
                logger.info("Run: auto-extract archive=%s", archive_path)
                try:
                    extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                    logger.info("Run: auto-extract ok extracted_dir=%s", extracted_dir)
                    pre_outputs.append(ex_xml)
                    self.memory.add_summary(ex_xml)
                    hints_local["extracted_root"] = extracted_dir
                    # 记录解压目录以便完成后清理
                    try:
                        self._extracted_dirs.append(extracted_dir)
                    except Exception:
                        pass
                    # 如果原始hints.path是归档文件，替换为解压目录下的首个文本文件
                    if hints_local.get("path") and isinstance(hints_local["path"], str) and hints_local["path"].lower().endswith((".tar.gz", ".tgz", ".zip")):
                        hints_local.pop("path", None)
                    if not hints_local.get("path"):
                        p = self._first_text_file_under(extracted_dir)
                        if p:
                            hints_local["path"] = p
                except Exception as e:
                    logger.warning("Run: auto-extract failed: %s", e)
                    pre_outputs.append(wrap_document(f"自动解压失败: {e}", {"type": "extraction_error"}))
            if self._app:
                logger.debug("Run: using LangGraph pipeline")
                final_state: AgentState = self._app.invoke({
                    "query": query,
                    "hints": hints_local,
                    "plan_xml": "",
                    "steps": [],
                    "idx": 0,
                    "outputs": pre_outputs,
                    "done": False,
                })
                outputs = final_state.get("outputs", [])
                logger.info("Run: outputs via graph=%d", len(outputs))
            else:
                logger.debug("Run: sequential fallback")
                plan_xml = self.plan(query)
                steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
                logger.info("Run: executing %d steps sequentially", len(steps))
                outputs: List[str] = pre_outputs[:]
                for step in steps:
                    logger.debug("Run: executing step '%s'", step)
                    out = self._execute_step(step, query, hints=hints_local)
                    outputs.append(out)
                    self.memory.add_summary(out)
            summary = compress_outputs(outputs)
            logger.debug("Run: summary chars=%d", len(summary))
            final_doc = wrap_document("".join(outputs) + summary, {"source": "log_agent"})
            logger.info("Run: final doc chars=%d", len(final_doc))
        finally:
            try:
                self._cleanup_extracted_dirs()
            except Exception as e:
                logger.warning("Run: cleanup extracted dirs failed: %s", e)
        return final_doc

    def _cleanup_extracted_dirs(self) -> None:
        base = os.path.abspath(os.path.join(settings.agent_root_dir, "_extracted"))
        for d in getattr(self, "_extracted_dirs", []):
            try:
                absd = os.path.abspath(d)
                if os.path.commonpath([absd, base]) != base:
                    logger.warning("Cleanup skipped for non-extracted path: %s", absd)
                    continue
                if os.path.isdir(absd):
                    logger.info("Cleanup: removing extracted dir: %s", absd)
                    shutil.rmtree(absd, ignore_errors=True)
            except Exception as e:
                logger.warning("Cleanup error for %s: %s", d, e)
        self._extracted_dirs = []





def demo_agent_run(query: str, hints: Optional[Dict[str, Any]] = None) -> str:
    logger.info("demo_agent_run: query='%s'", query)
    logger.debug("demo_agent_run: hints=%s", hints)
    agent = LogAnalysisAgent()
    result = agent.run(query, hints=hints)
    logger.info("demo_agent_run: result chars=%d", len(result))
    return result

# Prompt缓存（全局），用于存储配置与模板实例
_PROMPTS_CACHE: Dict[str, Dict[str, Any]] = {}
_PROMPT_TEMPLATES_CACHE: Dict[str, Any] = {}
class _BoundFallbackLLM:
    def __init__(self, primary: Any, fallback_conf: Optional[Dict[str, str]], tools: List[Any]):
        self._primary_bound = primary.bind_tools(tools) if (primary and hasattr(primary, "bind_tools")) else None
        self._fallback_conf = fallback_conf
        self._tools = tools
        # 增加日志：初始化时记录工具数量与主/备状态
        try:
            logger.info(
                "BoundFallbackLLM.init: tools=%s, primary_bound=%s, fallback_model=%s",
                [getattr(t, "name", str(t)) for t in tools],
                bool(self._primary_bound),
                (fallback_conf or {}).get("model")
            )
        except Exception:
            logger.debug("BoundFallbackLLM.init: logging failed")

    def invoke(self, prompt: str):
        if self._primary_bound:
            try:
                logger.debug("BoundFallbackLLM.invoke: using primary bound model")
                logger.info("\n\n--- START LLM PROMPT [BoundPrimary] ---\n%s\n--- END LLM PROMPT [BoundPrimary] ---\n", prompt)
                return self._primary_bound.invoke(prompt)
            except Exception as e:
                logger.warning(f"Bound primary invocation failed, switching to fallback: {e}")
        # Build and try fallback bound model
        if self._fallback_conf:
            logger.debug("BoundFallbackLLM.invoke: building fallback model and binding tools")
            fb = _make_chat_openai(
                self._fallback_conf.get("api_key", ""),
                self._fallback_conf.get("base_url", ""),
                self._fallback_conf.get("model", "")
            )
            if fb and hasattr(fb, "bind_tools"):
                fb_bound = fb.bind_tools(self._tools)
                try:
                    logger.debug("BoundFallbackLLM.invoke: using fallback bound model")
                    logger.info("\n\n--- START LLM PROMPT [BoundFallback] ---\n%s\n--- END LLM PROMPT [BoundFallback] ---\n", prompt)
                    return fb_bound.invoke(prompt)
                except Exception as e:
                    logger.warning(f"Bound fallback invocation failed: {e}")
        logger.error("BoundFallbackLLM.invoke: no available backend after retry")
        raise RuntimeError("No available LLM backend; bound invocation failed")

class LogAnalysisAgentDuplicate:
    """Main Agent orchestrating planning and tool execution via LangGraph."""
    def __init__(self):
        self.llm = get_llm()
        logger.info("LogAnalysisAgent.__init__: llm=%s", type(self.llm).__name__)
        self.memory = ShortTermMemory(window=settings.agent_short_term_window)
        self.search_backend = (
            ElasticSearchBackend(url=settings.elasticsearch_url)
            if settings.agent_search_backend == "elasticsearch"
            else RegexSearchBackend(root=settings.agent_root_dir)
        )
        logger.info("LogAnalysisAgent.__init__: backend=%s", type(self.search_backend).__name__)
        self._extracted_dirs: List[str] = []
        try:
            paths: List[str] = []
            logger.debug("Search indexing start: root=%s", settings.agent_root_dir)
            for d, _, files in os.walk(settings.agent_root_dir):
                for f in files:
                    paths.append(os.path.join(d, f))
                if len(paths) > 5000:
                    logger.warning("Indexing truncated at 5000 files to limit scope")
                    break
            self.search_backend.index(paths)
            logger.info("Search indexing done: files=%d", len(paths))
        except Exception as e:
            logger.warning("Search indexing failed: %s", e)

        # Build LangGraph (compact ReAct-style loop)
        if StateGraph:
            graph = StateGraph(AgentState)
            graph.add_node("plan", self._plan_node)
            graph.add_node("act", self._act_node)
            graph.add_edge("plan", "act")
            graph.add_conditional_edges("act", self._should_continue)
            graph.set_entry_point("plan")
            self._app = graph.compile()
        else:
            self._app = None  # Fallback: run() will degrade to sequential execution

    def _plan_node(self, state: AgentState) -> AgentState:
        """Graph node that generates plan XML and step list."""
        query = state.get("query", "")
        plan_xml = self.plan(query)
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        return {"plan_xml": plan_xml, "steps": steps}

    def _first_text_file(self) -> Optional[str]:
        for d, _, files in os.walk(settings.agent_root_dir):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found: %s', p)
                    return p
        logger.debug('First text file not found under root=%s', settings.agent_root_dir)
        return None

    def _first_text_file_under(self, root: str) -> Optional[str]:
        for d, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(('.log', '.txt')):
                    p = os.path.join(d, f)
                    logger.debug('First text file found under %s: %s', root, p)
                    return p
        logger.debug('First text file not found under root=%s', root)
        return None

    # Backward-compatible plan() API
    def plan(self, query: str) -> str:
        logger.info("Plan: start query='%s'", query[:200])
        prompt = render_prompt(
            "plan_prompt",
            memory_context=self.memory.context(),
            user_query=query,
        )
        logger.debug("Plan: prompt chars=%d", len(prompt))
        logger.info("\n\n--- START LLM PROMPT [plan] ---\n%s\n--- END LLM PROMPT [plan] ---\n", prompt)
        plan_xml: str = ""
        try:
            logger.debug("Plan: llm=%s", type(self.llm).__name__)
            if hasattr(self.llm, "predict"):
                plan_xml = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    plan_xml = response.content
                else:
                    plan_xml = str(response)
        except Exception as e:
            logger.warning("Plan LLM failed, using fallback: %s", e)
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        logger.info("\n\n--- START LLM OUTPUT [plan] ---\n%s\n--- END LLM OUTPUT [plan] ---\n", plan_xml)
        # Normalize: ensure XML structure
        steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
        if not steps:
            logger.debug("Plan: no <step> found, using fallback plan")
            plan_xml = wrap_plan(["读取日志片段", "在相关文件中执行grep搜索"])
        self.memory.add_message("user", query)
        self.memory.add_message("system", plan_xml)
        logger.info("Plan: steps=%d", len(re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)))
        return plan_xml

    # Tool routing (XML-producing, refactored)
    def _execute_step(self, step: str, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        logger.info("Execute step (refactored): %s", step)
        hints = hints or {}

        # Attempt function calling via llm.bind_tools
        try:
            tools_bound = self._build_langchain_tools(hints)
            if tools_bound and hasattr(self.llm, "bind_tools"):
                tool_map = {t.name: t for t in tools_bound}
                bound_llm = self.llm.bind_tools(tools_bound)
                fc_prompt = (
                    "你是一个日志分析Agent的工具路由器。\n"
                    "请基于提供的step、query、hints选择并调用一个工具，使用函数调用（function calling）。\n"
                    "不要输出普通文本，必须返回一个工具调用。\n"
                    f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
                )
                resp = bound_llm.invoke(fc_prompt)
                tool_calls = getattr(resp, "tool_calls", None)
                if not tool_calls and hasattr(resp, "additional_kwargs"):
                    tool_calls = resp.additional_kwargs.get("tool_calls")
                if tool_calls:
                    tc = tool_calls[0]
                    tname = tc.get("name") or tc.get("tool")
                    targs = tc.get("args") or {}
                    if isinstance(targs, list) and len(targs) == 1 and isinstance(targs[0], dict):
                        targs = targs[0]
                    if tname in tool_map:
                        logger.info("bind_tools selected '%s' with args=%s", tname, targs)
                        try:
                            return tool_map[tname].invoke(targs)
                        except Exception as e:
                            logger.warning("Tool '%s' execution via bind_tools failed: %s", tname, e)
        except Exception as e:
            logger.warning("bind_tools route failed, fallback to manual selection: %s", e)

        tool_specs: Dict[str, Dict[str, Any]] = {
            "metadata_extract": {
                "desc": "提取日志包元数据（tar.gz/zip）",
                "schema": {"archive_path": "str"},
            },
            "grep_search": {
                "desc": "在文本文件中执行模式搜索 (grep)",
                "schema": {"path": "str?", "pattern": "str", "context": "int?"},
            },
            "read_snippet": {
                "desc": "读取文件片段 (head/tail)",
                "schema": {"path": "str?", "head_lines": "int?", "tail_lines": "int?"},
            },
            "nested_extract": {
                "desc": "解压或扫描嵌套归档",
                "schema": {"nested_path": "str?", "extracted_root": "str?"},
            },
            "list_tree": {
                "desc": "列出目录树结构",
                "schema": {"root": "str?", "max_depth": "int?"},
            },
            "global_search": {
                "desc": "使用搜索后转为XML",
                "schema": {"query": "str", "k": "int?"},
            },
        }

        def _extract_json_candidate(s: str) -> Optional[Dict[str, Any]]:
            try:
                s = s.strip()
                if s.startswith("{") and s.endswith("}"):
                    return json.loads(s)
                start = s.find("{")
                end = s.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(s[start : end + 1])
            except Exception:
                return None
            return None

        def _fallback_select(step_text: str) -> Dict[str, Any]:
            st = step_text.lower()
            if ("元数据" in st) or ("metadata" in st):
                return {"tool": "metadata_extract", "args": {}}
            if ("grep" in st) or ("查找" in st) or ("搜索" in st):
                return {"tool": "grep_search", "args": {}}
            if ("读取" in st) or ("片段" in st) or ("head" in st) or ("tail" in st):
                return {"tool": "read_snippet", "args": {}}
            if ("解压" in st) or ("extract" in st) or ("decompress" in st):
                return {"tool": "nested_extract", "args": {}}
            if ("树" in st) or ("tree" in st) or ("结构" in st) or ("list" in st):
                return {"tool": "list_tree", "args": {}}
            return {"tool": "global_search", "args": {}}

        selection: Dict[str, Any] = {}
        try:
            tools_text = "\n".join([f"- {name}: {spec['desc']} schema={spec['schema']}" for name, spec in tool_specs.items()])
            prompt = (
                "你是一个日志分析Agent的工具路由器。\n"
                "基于提供的step、query、hints，从下列工具中选择最合适的一个，并给出JSON参数：\n"
                f"{tools_text}\n\n"
                "返回严格的JSON对象，不要包含解释或多余文字。格式：{\"tool\": \"<name>\", \"args\": { ... }}\n"
                f"<step>{step}</step>\n<query>{query}</query>\n<hints>{json.dumps(hints, ensure_ascii=False)}</hints>\n"
            )
            if hasattr(self.llm, "predict"):
                raw = self.llm.predict(prompt)
            else:
                response = self.llm.invoke(prompt)
                # 正确提取LangChain消息对象的content字段
                if hasattr(response, "content"):
                    raw = response.content
                else:
                    raw = str(response)
            cand = _extract_json_candidate(raw)
            if not cand:
                raise ValueError("LLM未返回可解析的JSON")
            selection = cand
        except Exception as e:
            logger.warning("Tool selection via LLM failed, using fallback: %s", e)
            selection = _fallback_select(step)

        name = str(selection.get("tool", "")).strip()
        args: Dict[str, Any] = selection.get("args", {}) if isinstance(selection.get("args", {}), dict) else {}
        if name not in tool_specs:
            logger.warning("Unknown tool '%s', fallback to global_search", name)
            name = "global_search"

        try:
            if name == "metadata_extract":
                hint_arch = hints.get("archive_path")
                hint_path = hints.get("path")
                ap = args.get("archive_path")
                path = ap or hint_arch or (
                    hint_path if isinstance(hint_path, str) and hint_path.lower().endswith((".tar.gz", ".tgz", ".zip")) else None
                ) or os.path.join(settings.agent_root_dir, "logs.tar.gz")
                logger.info("ToolCall metadata_extract: path=%s", path)
                return get_log_package_metadata_xml(path)

            if name == "grep_search":
                pattern = args.get("pattern") or hints.get("pattern") or query
                path = args.get("path") or hints.get("path") or self._first_text_file()
                context = int(args.get("context") or 2)
                logger.info(
                    "ToolCall grep_search: path=%s pattern=%s context=%d max_matches=%s max_bytes=%s",
                    path,
                    pattern,
                    context,
                    getattr(settings, "agent_max_matches", None),
                    getattr(settings, "agent_max_snippet_bytes", None),
                )
                if not path:
                    return wrap_document("未找到可搜索的文本文件", {"step": step})
                return grep_file_xml(path, pattern, context=context)

            if name == "read_snippet":
                path = args.get("path") or hints.get("path") or self._first_text_file()
                head_n = int(args.get("head_lines") or 50)
                tail_n = int(args.get("tail_lines") or 50)
                logger.info("ToolCall read_snippet: path=%s head_lines=%d tail_lines=%d", path, head_n, tail_n)
                if not path:
                    return wrap_document("未找到可读取的文本文件", {"step": step})
                head = read_head_xml(path, n_lines=head_n)
                tail = read_tail_xml(path, n_lines=tail_n)
                return f"<reads>{head}{tail}</reads>"

            if name == "nested_extract":
                nested_path = args.get("nested_path") or hints.get("nested_path")
                root = args.get("extracted_root") or hints.get("extracted_root") or settings.agent_root_dir
                logger.info("ToolCall nested_extract: nested_path=%s root=%s", nested_path, root)
                if nested_path:
                    dest, xml = extract_nested_archive_xml(nested_path, parent_root=root)
                    try:
                        self._extracted_dirs.append(dest)
                    except Exception:
                        pass
                    logger.info("ToolCall nested_extract: extracted_dir=%s", dest)
                    return xml
                else:
                    return nested_archives_xml(root)

            if name == "list_tree":
                root = args.get("root") or hints.get("extracted_root") or settings.agent_root_dir
                max_depth = int(args.get("max_depth") or 2)
                logger.info("ToolCall list_tree: root=%s max_depth=%d", root, max_depth)
                return list_tree_xml(root, max_depth=max_depth)

            if name == "global_search":
                k = int(args.get("k") or 10)
                logger.info("ToolCall global_search: backend=%s query=%s k=%d", type(self.search_backend).__name__, query, k)
                return search_to_xml(self.search_backend, query=query, k=k)

            logger.warning("Unhandled tool '%s', fallback to global_search", name)
            return search_to_xml(self.search_backend, query=query, k=10)
        except Exception as e:
            logger.warning("Tool '%s' execution failed: %s", name, e)
            label = {
                "metadata_extract": "元数据提取失败",
                "grep_search": "grep失败",
                "read_snippet": "读取失败",
                "nested_extract": "解压/扫描嵌套归档失败",
                "list_tree": "树结构生成失败",
                "global_search": "搜索失败",
            }.get(name, "工具执行失败")
            return wrap_document(f"{label}: {e}", {"step": step})

    # Graph node: act
    def _act_node(self, state: AgentState) -> AgentState:
        steps = state["steps"]
        idx = state.get("idx", 0)
        logger.info("Act: idx=%d/%d", idx, len(steps))
        if idx >= len(steps):
            logger.debug("Act: completed all steps")
            return {"done": True}
        step = steps[idx]
        out = self._execute_step(step, state["query"], hints=state.get("hints"))
        logger.debug("Act: output chars=%d", len(out))
        self.memory.add_summary(out)
        # Generate and print per-act LLM thought
        try:
            step_thought = compress_outputs([out])
            logger.info("LLM Thought [after_act]:\n%s", step_thought)
        except Exception as e:
            logger.warning("Act: step thought generation failed: %s", e)
        outputs = state.get("outputs", []) + [out]
        return {"outputs": outputs, "idx": idx + 1}

    # Graph edge condition
    def _should_continue(self, state: AgentState):
        idx = state.get("idx", 0)
        steps = state.get("steps", [])
        decision = "act" if idx < len(steps) else "end"
        logger.debug("Continue? idx=%d steps=%d decision=%s", idx, len(steps), decision)
        if idx < len(steps):
            return "act"
        return END

    def run(self, query: str, hints: Optional[Dict[str, Any]] = None) -> str:
        """Run the agent end-to-end using LangGraph when available; fallback sequential otherwise."""
        logger.info("Run: start query='%s'", query)
        hints_local: Dict[str, Any] = dict(hints or {})
        logger.debug("Run: hints=%s", hints_local)
        pre_outputs: List[str] = []
        final_doc: str = ""
        try:
            # 自动解压流程：如果提供了归档路径，则先解压并输出树结构
            archive_path = hints_local.get("archive_path") or (hints_local.get("path") if isinstance(hints_local.get("path"), str) and hints_local.get("path").lower().endswith((".tar.gz", ".tgz", ".zip")) else None)
            if archive_path:
                logger.info("Run: auto-extract archive=%s", archive_path)
                try:
                    extracted_dir, ex_xml = auto_extract_archive_xml(archive_path)
                    logger.info("Run: auto-extract ok extracted_dir=%s", extracted_dir)
                    pre_outputs.append(ex_xml)
                    self.memory.add_summary(ex_xml)
                    hints_local["extracted_root"] = extracted_dir
                    # 记录解压目录以便完成后清理
                    try:
                        self._extracted_dirs.append(extracted_dir)
                    except Exception:
                        pass
                    # 如果原始hints.path是归档文件，替换为解压目录下的首个文本文件
                    if hints_local.get("path") and isinstance(hints_local["path"], str) and hints_local["path"].lower().endswith((".tar.gz", ".tgz", ".zip")):
                        hints_local.pop("path", None)
                    if not hints_local.get("path"):
                        p = self._first_text_file_under(extracted_dir)
                        if p:
                            hints_local["path"] = p
                except Exception as e:
                    logger.warning("Run: auto-extract failed: %s", e)
                    pre_outputs.append(wrap_document(f"自动解压失败: {e}", {"type": "extraction_error"}))
            if self._app:
                logger.debug("Run: using LangGraph pipeline")
                final_state: AgentState = self._app.invoke({
                    "query": query,
                    "hints": hints_local,
                    "plan_xml": "",
                    "steps": [],
                    "idx": 0,
                    "outputs": pre_outputs,
                    "done": False,
                })
                outputs = final_state.get("outputs", [])
                logger.info("Run: outputs via graph=%d", len(outputs))
            else:
                logger.debug("Run: sequential fallback")
                plan_xml = self.plan(query)
                steps = re.findall(r"<step[^>]*>(.*?)</step>", plan_xml, flags=re.DOTALL)
                logger.info("Run: executing %d steps sequentially", len(steps))
                outputs: List[str] = pre_outputs[:]
                for step in steps:
                    logger.debug("Run: executing step '%s'", step)
                    out = self._execute_step(step, query, hints=hints_local)
                    outputs.append(out)
                    self.memory.add_summary(out)
            summary = compress_outputs(outputs)
            logger.debug("Run: summary chars=%d", len(summary))
            final_doc = wrap_document("".join(outputs) + summary, {"source": "log_agent"})
            logger.info("Run: final doc chars=%d", len(final_doc))
        finally:
            try:
                self._cleanup_extracted_dirs()
            except Exception as e:
                logger.warning("Run: cleanup extracted dirs failed: %s", e)
        return final_doc

    def _cleanup_extracted_dirs(self) -> None:
        base = os.path.abspath(os.path.join(settings.agent_root_dir, "_extracted"))
        for d in getattr(self, "_extracted_dirs", []):
            try:
                absd = os.path.abspath(d)
                if os.path.commonpath([absd, base]) != base:
                    logger.warning("Cleanup skipped for non-extracted path: %s", absd)
                    continue
                if os.path.isdir(absd):
                    logger.info("Cleanup: removing extracted dir: %s", absd)
                    shutil.rmtree(absd, ignore_errors=True)
            except Exception as e:
                logger.warning("Cleanup error for %s: %s", d, e)
        self._extracted_dirs = []





def demo_agent_run(query: str, hints: Optional[Dict[str, Any]] = None) -> str:
    logger.info("demo_agent_run: query='%s'", query)
    logger.debug("demo_agent_run: hints=%s", hints)
    agent = LogAnalysisAgent()
    result = agent.run(query, hints=hints)
    logger.info("demo_agent_run: result chars=%d", len(result))
    return result

# Prompt缓存（全局），用于存储配置与模板实例
_PROMPTS_CACHE: Dict[str, Dict[str, Any]] = {}
_PROMPT_TEMPLATES_CACHE: Dict[str, Any] = {}